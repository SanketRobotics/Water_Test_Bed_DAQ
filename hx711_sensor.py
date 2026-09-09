"""
HX711 load cell driver (YZC-131 1kg load cell + SparkFun SEN-13879 amp).

Wiring (confirmed by tracing physical wires):
    DAT (DOUT) -> GPIO 5  (physical pin 29)
    CLK (SCK)  -> GPIO 6  (physical pin 31)
    VCC        -> 5V
    GND        -> GND

Uses libgpiod (python gpiod bindings) for GPIO access.
"""

import time
import gpiod

import config

HIGH = gpiod.line.Value.ACTIVE
LOW = gpiod.line.Value.INACTIVE

FULL_SCALE_GLITCH_HIGH = 8388607    # 0x7FFFFF
FULL_SCALE_GLITCH_LOW = -8388608    # -0x800000


def _median(vals):
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


class OutlierFilter:
    """Rejects readings that jump too far from the recent median --
    catches noise-induced garbage values from marginal wiring/power,
    not just the exact full-scale glitch value.

    Includes a "stuck" recovery: if several readings in a row get
    rejected, the reference median is treated as stale (e.g. a real,
    fast weight change happened while a burst of glitches also
    occurred, so the filter never got to update its reference) and
    the next reading is accepted unconditionally, resyncing history
    to the current signal instead of staying anchored to old data."""

    def __init__(self, window=10, max_jump=config.HX711_MAX_JUMP, max_consecutive_rejects=5):
        self.window = window
        self.max_jump = max_jump
        self.max_consecutive_rejects = max_consecutive_rejects
        self.history = []
        self._consecutive_rejects = 0

    def seed(self, value):
        self.history = [value]
        self._consecutive_rejects = 0

    def check(self, value):
        if value is None:
            return None
        if value == FULL_SCALE_GLITCH_HIGH or value == FULL_SCALE_GLITCH_LOW:
            self._consecutive_rejects += 1
            return None
        if not self.history:
            self.history.append(value)
            self._consecutive_rejects = 0
            return value
        ref = _median(self.history)
        if abs(value - ref) > self.max_jump:
            self._consecutive_rejects += 1
            if self._consecutive_rejects >= self.max_consecutive_rejects:
                # Reference is stale -- resync to current signal rather
                # than keep rejecting against an outdated median.
                self.history = [value]
                self._consecutive_rejects = 0
                return value
            return None
        self._consecutive_rejects = 0
        self.history.append(value)
        if len(self.history) > self.window:
            self.history.pop(0)
        return value


class HX711:
    def __init__(self):
        self.chip = gpiod.Chip(config.HX711_CHIP)
        self.dout = self.chip.request_lines(
            consumer="hx711-dout",
            config={
                config.HX711_DOUT_PIN: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT
                )
            },
        )
        self.sck = self.chip.request_lines(
            consumer="hx711-sck",
            config={
                config.HX711_SCK_PIN: gpiod.LineSettings(
                    direction=gpiod.line.Direction.OUTPUT,
                    output_value=LOW,
                )
            },
        )

        cal = config.load_calibration()
        self.tare_offset = cal["tare_offset"]
        self.calibration_factor = cal["calibration_factor"]

        self.filter = OutlierFilter()
        # NOTE: deliberately NOT seeding the filter with tare_offset here.
        # tare_offset comes from calibration.json and may be from a
        # previous session -- the sensor's raw baseline can drift by
        # more than HX711_MAX_JUMP between sessions (confirmed during
        # testing), which would cause every live reading to be
        # incorrectly rejected as an outlier. The filter instead seeds
        # itself from the first live reading it actually sees.
        #
        # However, letting the filter's FIRST-EVER reading come from a
        # single unchecked read_raw() call is risky: if that one sample
        # happens to be a glitch (still occurs occasionally even on
        # good power), the filter's entire reference point for the
        # session starts corrupted, and it can take several seconds of
        # resync cycles to recover (confirmed during testing -- a test
        # run showed ~9 seconds of wildly wrong readings before
        # settling). So instead, warm up the filter here using a
        # robust averaged reading (same read_average() logic already
        # trusted for tare/calibration) before any real reading is
        # ever requested by the app.
        warmup = self.read_average(times=5)
        if warmup is not None:
            self.filter.seed(warmup)

    def _is_ready(self):
        return self.dout.get_value(config.HX711_DOUT_PIN) == LOW

    def read_raw(self, timeout=None):
        """Read one 24-bit signed value (Channel A, gain 128). Returns
        None on timeout waiting for the HX711 ready signal."""
        if timeout is None:
            timeout = config.HX711_READ_TIMEOUT

        start = time.time()
        while not self._is_ready():
            if time.time() - start > timeout:
                return None
            time.sleep(0.001)

        value = 0
        for _ in range(24):
            self.sck.set_value(config.HX711_SCK_PIN, HIGH)
            bit = 1 if self.dout.get_value(config.HX711_DOUT_PIN) == HIGH else 0
            self.sck.set_value(config.HX711_SCK_PIN, LOW)
            value = (value << 1) | bit

        # 25th pulse: sets next conversion to Channel A, gain 128
        self.sck.set_value(config.HX711_SCK_PIN, HIGH)
        self.sck.set_value(config.HX711_SCK_PIN, LOW)

        if value & 0x800000:
            value -= 0x1000000

        return value

    def read_filtered(self):
        """Read one value and pass it through the outlier filter.
        Returns None if the reading times out OR is rejected as noise."""
        raw = self.read_raw()
        return self.filter.check(raw)

    def read_average(self, times=15, timeout_per_read=None):
        """Take several filtered readings and average them. Used for
        taring and calibration, where we want a stable number."""
        temp_filter = OutlierFilter(window=times)
        vals = []
        attempts = 0
        max_attempts = times * 4
        while len(vals) < times and attempts < max_attempts:
            attempts += 1
            raw = self.read_raw(timeout=timeout_per_read)
            good = temp_filter.check(raw)
            if good is not None:
                vals.append(good)
            time.sleep(0.05)
        if not vals:
            return None
        return sum(vals) / len(vals)

    def tare(self, times=15):
        """Zero the scale. Averages several readings with nothing on
        the load cell and stores the result as the new zero point."""
        offset = self.read_average(times=times)
        if offset is not None:
            self.tare_offset = offset
            self.filter.seed(offset)
        return offset

    def calibrate(self, known_weight_grams, times=15):
        """Call this with a known weight ALREADY PLACED on the load
        cell. Computes and stores the calibration factor using the
        current tare_offset. Returns the new calibration factor."""
        raw_with_weight = self.read_average(times=times)
        if raw_with_weight is None:
            return None
        diff = raw_with_weight - self.tare_offset
        if diff == 0:
            return None
        factor = diff / known_weight_grams
        self.calibration_factor = factor
        config.save_calibration(self.tare_offset, factor)
        return factor

    def get_grams(self):
        """Returns current filtered weight in grams, or None if the
        reading timed out or was rejected as noise."""
        raw = self.read_filtered()
        if raw is None:
            return None
        return (raw - self.tare_offset) / self.calibration_factor

    def get_newtons(self):
        grams = self.get_grams()
        if grams is None:
            return None
        return (grams / 1000.0) * config.GRAVITY_MS2

    def close(self):
        self.dout.release()
        self.sck.release()
