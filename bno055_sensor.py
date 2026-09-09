"""
BNO055 IMU driver, UART mode -- connected via an HW-417 (FT232RL)
USB-to-TTL converter plugged into a Pi USB port.

Wiring:
    BNO055 PS1 -> 3.3V  (this is what switches SCL/SDA pins into UART RX/TX mode)
    BNO055 RX  -> HW-417 TX
    BNO055 TX  -> HW-417 RX
    BNO055 VIN -> HW-417 3.3V or 5V (check your board's regulator)
    BNO055 GND -> HW-417 GND
    HW-417     -> plugged into a Pi USB port (appears as /dev/ttyUSB0)

Uses our own bno055_uart.py driver rather than the
adafruit-circuitpython-bno055 library. That library's UART backend has
a timing bug (100ms busy-wait window that's too tight for USB-to-TTL
converters, which add USB polling latency) that causes spurious
"UART access error" failures even with correct wiring -- confirmed via
raw protocol testing during setup, where the sensor responded
correctly to a direct chip-ID request. See bno055_uart.py for details.

If you get a "Permission denied" opening the port, your user may need
to be added to the `dialout` and/or `plugdev` group (varies by OS):
    sudo usermod -aG dialout,plugdev $USER
then log out and back in (or reboot) for it to take effect.
"""

from bno055_uart import BNO055, BNO055UARTError
import config


class BNO055Sensor:
    """Thin wrapper kept for interface compatibility with the rest of
    the app (data_logger.py, main_app.py) -- delegates to bno055_uart.BNO055."""

    def __init__(self, port=None, baud=None, auto_load_calibration=True):
        self._imu = BNO055(port=port, baud=baud)
        if auto_load_calibration:
            self.load_saved_calibration()

    def get_acceleration(self):
        """Returns (x, y, z) in m/s^2, sign-corrected so that +Z = up
        for this sensor's mounting (flat, chip facing up)."""
        return self._imu.get_acceleration()

    def get_calibration_status(self):
        """Returns (sys, gyro, accel, mag) calibration levels, 0-3 each."""
        return self._imu.get_calibration_status()

    def get_orientation_euler(self):
        """Optional: (heading, roll, pitch) in degrees."""
        return self._imu.get_orientation_euler()

    def save_calibration(self):
        """Reads the current calibration offset profile from the
        sensor and saves it to imu_calibration.json, so it can be
        auto-restored on future startups without redoing the
        calibration dance. Returns True on success."""
        offsets = self._imu.get_calibration_offsets()
        if offsets is None:
            return False
        config.save_imu_calibration(list(offsets))
        return True

    def load_saved_calibration(self):
        """Restores a previously-saved calibration offset profile, if
        one exists. Silently does nothing if no saved calibration is
        found (first run) or if the sensor rejects it. Returns True if
        offsets were successfully applied."""
        offsets = config.load_imu_calibration()
        if offsets is None:
            return False
        return self._imu.set_calibration_offsets(bytes(offsets))

    def close(self):
        self._imu.close()
