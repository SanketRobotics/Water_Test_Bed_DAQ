"""
Combines load cell + IMU readings into synchronized CSV rows, and
integrates acceleration into velocity over the course of a test.

Velocity is computed via trapezoidal integration of each axis's
acceleration, reset to zero at the start of every test.

IMPORTANT -- gravity/tilt baseline subtraction:
The BNO055's raw acceleration always includes gravity plus whatever
constant tilt the sensor's mounting has. Integrating that raw signal
directly would produce a velocity that climbs forever even when the
sensor is perfectly still, since gravity never goes away. To avoid
this, start() captures a brief baseline average of acceleration on
each axis (assumes the sensor is still and at its resting orientation
at test start), and velocity integration uses acceleration MINUS that
baseline. Raw acceleration in the CSV is unaffected -- baseline
subtraction only applies to the velocity calculation.

This approach assumes the sensor's orientation stays constant
throughout the test (no significant tilting/rotating) -- if the
mounting orientation changes during a test, gravity's contribution to
each axis changes too, and this fixed-baseline approach will no longer
fully cancel it out. Tests are short (max ~15s per spec), so drift
from any small residual bias is limited but not zero.
"""

import csv
import os
import time
from datetime import datetime

import config

BASELINE_SAMPLES = 5  # quick readings averaged at test start for gravity/tilt baseline


class DataLogger:
    def __init__(self, hx711, imu):
        self.hx711 = hx711
        self.imu = imu
        self.csv_path = None
        self._file = None
        self._writer = None
        self.sample_count = 0
        self.start_time = None
        self._last_sample_time = None

        # Running velocity estimate per axis (m/s), integrated from
        # BASELINE-SUBTRACTED acceleration. Reset at the start of each test.
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self._prev_ax = None
        self._prev_ay = None
        self._prev_az = None

        # Gravity/tilt baseline, captured fresh at the start of each test
        self._baseline_ax = 0.0
        self._baseline_ay = 0.0
        self._baseline_az = 0.0

    def _capture_baseline(self, samples=BASELINE_SAMPLES):
        """Averages a few quick acceleration readings to establish the
        resting gravity/tilt baseline for this test. Sensor should be
        still at its normal test-start orientation when this runs."""
        xs, ys, zs = [], [], []
        for _ in range(samples):
            ax, ay, az = self.imu.get_acceleration()
            if ax is not None:
                xs.append(ax)
                ys.append(ay)
                zs.append(az)
            time.sleep(0.02)
        if xs:
            self._baseline_ax = sum(xs) / len(xs)
            self._baseline_ay = sum(ys) / len(ys)
            self._baseline_az = sum(zs) / len(zs)
        else:
            self._baseline_ax = 0.0
            self._baseline_ay = 0.0
            self._baseline_az = 0.0

    def start(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_{timestamp}.csv"
        self.csv_path = os.path.join(config.DATA_DIR, filename)
        self._file = open(self.csv_path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(
            [
                "timestamp",
                "elapsed_s",
                "load_g",
                "load_N",
                "accel_x",
                "accel_y",
                "accel_z",
                "vel_x",
                "vel_y",
                "vel_z",
            ]
        )
        self.sample_count = 0
        self.start_time = time.time()
        self._last_sample_time = self.start_time

        # Reset velocity integration state for this test
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self._prev_ax = None
        self._prev_ay = None
        self._prev_az = None

        # Capture this test's gravity/tilt baseline before timing starts
        # counting samples -- assumes sensor is at rest right now.
        self._capture_baseline()
        self.start_time = time.time()
        self._last_sample_time = self.start_time

        return self.csv_path

    def _integrate_velocity(self, ax, ay, az, dt):
        """Trapezoidal integration of BASELINE-SUBTRACTED acceleration:
        v += avg(prev_a, current_a) * dt. Falls back to rectangular
        integration on the very first reading. Any axis with a None
        reading holds its previous velocity steady rather than
        integrating garbage."""
        if ax is not None:
            a_net = ax - self._baseline_ax
            prev = self._prev_ax if self._prev_ax is not None else a_net
            self.vx += 0.5 * (prev + a_net) * dt
            self._prev_ax = a_net
        if ay is not None:
            a_net = ay - self._baseline_ay
            prev = self._prev_ay if self._prev_ay is not None else a_net
            self.vy += 0.5 * (prev + a_net) * dt
            self._prev_ay = a_net
        if az is not None:
            a_net = az - self._baseline_az
            prev = self._prev_az if self._prev_az is not None else a_net
            self.vz += 0.5 * (prev + a_net) * dt
            self._prev_az = a_net

    def sample_once(self):
        """Reads both sensors once, integrates velocity, writes one
        row, and returns the row's values as a dict (used by the GUI
        to update live graphs without re-reading the sensors)."""
        if self._writer is None:
            raise RuntimeError("DataLogger.start() must be called before sampling")

        now_dt = datetime.now()
        now_iso = now_dt.isoformat(timespec="milliseconds")
        now_t = time.time()
        elapsed = now_t - self.start_time
        dt = now_t - self._last_sample_time
        self._last_sample_time = now_t

        try:
            grams = self.hx711.get_grams()
        except Exception:
            grams = None
        newtons = None
        if grams is not None:
            newtons = (grams / 1000.0) * config.GRAVITY_MS2

        try:
            ax, ay, az = self.imu.get_acceleration()
        except Exception:
            # Any unexpected sensor/driver error (e.g. a malformed or
            # desynced response) degrades to a missed sample rather
            # than crashing the whole test -- a test in progress is
            # more valuable with an occasional gap than aborted entirely.
            ax, ay, az = None, None, None
        self._integrate_velocity(ax, ay, az, dt)

        self._writer.writerow(
            [
                now_iso,
                round(elapsed, 3),
                "" if grams is None else round(grams, 3),
                "" if newtons is None else round(newtons, 4),
                "" if ax is None else round(ax, 4),
                "" if ay is None else round(ay, 4),
                "" if az is None else round(az, 4),
                round(self.vx, 4),
                round(self.vy, 4),
                round(self.vz, 4),
            ]
        )
        self._file.flush()
        self.sample_count += 1

        return {
            "timestamp": now_iso,
            "elapsed_s": elapsed,
            "load_g": grams,
            "load_N": newtons,
            "accel_x": ax,
            "accel_y": ay,
            "accel_z": az,
            "vel_x": self.vx,
            "vel_y": self.vy,
            "vel_z": self.vz,
        }

    def stop(self):
        if self._file is not None:
            self._file.close()
        path = self.csv_path
        self._file = None
        self._writer = None
        return path


if __name__ == "__main__":
    # Quick standalone test: logs for 10 seconds, prints progress.
    from hx711_sensor import HX711
    from bno055_sensor import BNO055Sensor

    print("Initializing sensors...")
    hx711 = HX711()
    imu = BNO055Sensor()

    print("Taring load cell (keep empty)...")
    hx711.tare()

    logger = DataLogger(hx711, imu)
    print("Capturing baseline -- keep sensor still...")
    path = logger.start()
    print(f"Logging to {path} for 10 seconds...")

    try:
        end_time = time.time() + 10
        while time.time() < end_time:
            row = logger.sample_once()
            print(row)
            time.sleep(config.SAMPLE_INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        logger.stop()
        hx711.close()
        imu.close()
        print("Done.")
