"""
Lightweight BNO055 UART driver.

Written to replace adafruit-circuitpython-bno055's UART backend, which
has a timing bug in _read_register(): it busy-waits on in_waiting with
only a 100ms window, which is too tight for USB-to-TTL converters
(like the HW-417/FT232RL used here) where USB polling latency can
push responses just past that window, causing spurious
"UART access error" failures even though the sensor and wiring are
completely fine.

This driver uses simple blocking reads with a generous timeout instead,
matching the approach that worked reliably in raw protocol testing.

BNO055 UART protocol (Bosch datasheet, section 4.5.3):
    Write:  TX  0xAA 0x00 [reg] [len] [data...]
            RX  0xEE 0x01                          (success)
                0xEE [error_code]                  (failure)
    Read:   TX  0xAA 0x01 [reg] [len]
            RX  0xBB [len] [data...]               (success)
                0xEE [error_code]                  (failure)
"""

import struct
import time

import serial

import config

CHIP_ID_REGISTER = 0x00
EXPECTED_CHIP_ID = 0xA0

PAGE_REGISTER = 0x07
OPR_MODE_REGISTER = 0x3D
CALIB_STAT_REGISTER = 0x35

ACCEL_DATA_REGISTER = 0x08   # 6 bytes: X, Y, Z as signed 16-bit, LSB=1/100 m/s^2
EULER_DATA_REGISTER = 0x1A   # 6 bytes: heading, roll, pitch, signed 16-bit, LSB=1/16 degree

# Calibration offset/radius registers (Bosch datasheet section 4.3.61-4.3.66).
# Only readable/writable while in CONFIG mode. 22 bytes total:
# accel offset (6) + mag offset (6) + gyro offset (6) + accel radius (2) + mag radius (2)
CALIB_OFFSET_START_REGISTER = 0x55
CALIB_OFFSET_LENGTH = 22

MODE_CONFIG = 0x00
MODE_NDOF = 0x0C  # full sensor fusion mode (accel+gyro+mag), matches Adafruit library default

READ_RESPONSE_OK = 0xBB
WRITE_RESPONSE_OK = 0xEE
WRITE_SUCCESS_CODE = 0x01

# Axis sign correction -- see bno055_sensor.py for why (mounting-dependent)
ACCEL_SIGN = (1, 1, -1)  # (x_sign, y_sign, z_sign)


class BNO055UARTError(Exception):
    pass


class BNO055:
    def __init__(self, port=None, baud=None, timeout=0.3, retries=3):
        port = port or config.BNO055_UART_PORT
        baud = baud or config.BNO055_UART_BAUD
        self.timeout = timeout
        self.retries = retries

        self._ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(1.0)  # let the USB-serial adapter settle after opening
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()

        chip_id = self._read(CHIP_ID_REGISTER, 1)
        if chip_id is None or chip_id[0] != EXPECTED_CHIP_ID:
            raise BNO055UARTError(
                f"Unexpected or missing chip ID response: {chip_id}"
            )

        # Switch to NDOF mode (full sensor fusion) -- matches what the
        # Adafruit library sets up by default.
        self._write(OPR_MODE_REGISTER, bytes([MODE_NDOF]))
        time.sleep(0.03)  # BNO055 needs ~19-20ms to switch into a fusion mode

    def _read(self, register, length):
        """Low-level read. Returns bytes of the requested length, or
        None if all retries failed."""
        for _attempt in range(self.retries):
            self._ser.reset_input_buffer()
            cmd = bytes([0xAA, 0x01, register, length])
            self._ser.write(cmd)
            header = self._ser.read(2)
            if config.DEBUG_BNO055:
                print(f"[debug] sent={cmd.hex(' ')} header={header.hex(' ') if header else '(none)'}")
            if len(header) < 2:
                continue  # timeout, retry
            if header[0] == READ_RESPONSE_OK:
                resp_len = header[1]
                data = self._ser.read(resp_len)
                if config.DEBUG_BNO055:
                    print(f"[debug] resp_len={resp_len} data={data.hex(' ') if data else '(none)'}")
                # Validate against the length we actually asked for, not
                # just internal consistency between header and data --
                # a desynced/corrupted response could claim a different
                # resp_len than requested and still be "internally
                # consistent" while being wrong for the caller.
                if len(data) == resp_len and resp_len == length:
                    return data
                continue  # short read or unexpected length, retry
            elif header[0] == WRITE_RESPONSE_OK:
                # sensor sent an error response (0xEE [error_code])
                if config.DEBUG_BNO055:
                    print(f"[debug] error response, code={header[1] if len(header) > 1 else '?'}")
                continue  # retry
            # unrecognized response, retry
        return None

    def _write(self, register, data):
        """Low-level write. Returns True on success, False on failure."""
        if not isinstance(data, (bytes, bytearray)):
            data = bytes([data])
        for _attempt in range(self.retries):
            self._ser.reset_input_buffer()
            self._ser.write(bytes([0xAA, 0x00, register, len(data)]) + data)
            resp = self._ser.read(2)
            if len(resp) == 2 and resp[0] == WRITE_RESPONSE_OK and resp[1] == WRITE_SUCCESS_CODE:
                return True
        return False

    def get_acceleration(self):
        """Returns (x, y, z) in m/s^2, sign-corrected so +Z = up for
        this sensor's mounting. Returns (None, None, None) on failure."""
        data = self._read(ACCEL_DATA_REGISTER, 6)
        if data is None or len(data) != 6:
            return (None, None, None)
        x_raw, y_raw, z_raw = struct.unpack("<hhh", data)
        # BNO055 accel output: 1 LSB = 1/100 m/s^2 in this fusion mode
        x = x_raw / 100.0
        y = y_raw / 100.0
        z = z_raw / 100.0
        sx, sy, sz = ACCEL_SIGN
        return (x * sx, y * sy, z * sz)

    def get_calibration_status(self):
        """Returns (sys, gyro, accel, mag), each 0-3. Returns
        (None, None, None, None) on failure."""
        data = self._read(CALIB_STAT_REGISTER, 1)
        if data is None or len(data) != 1:
            return (None, None, None, None)
        byte = data[0]
        sys_cal = (byte >> 6) & 0x03
        gyro_cal = (byte >> 4) & 0x03
        accel_cal = (byte >> 2) & 0x03
        mag_cal = byte & 0x03
        return (sys_cal, gyro_cal, accel_cal, mag_cal)

    def get_orientation_euler(self):
        """Returns (heading, roll, pitch) in degrees, or
        (None, None, None) on failure."""
        data = self._read(EULER_DATA_REGISTER, 6)
        if data is None or len(data) != 6:
            return (None, None, None)
        h_raw, r_raw, p_raw = struct.unpack("<hhh", data)
        # BNO055 euler output: 1 LSB = 1/16 degree
        return (h_raw / 16.0, r_raw / 16.0, p_raw / 16.0)

    def get_calibration_offsets(self):
        """Reads the full 22-byte calibration offset/radius profile.
        Must be called while calibration is good (ideally sys=3) for
        the values to be meaningful. Switches to CONFIG mode to read
        (required by the sensor), then back to NDOF. Returns raw bytes,
        or None on failure."""
        self._write(OPR_MODE_REGISTER, bytes([MODE_CONFIG]))
        time.sleep(0.03)
        data = self._read(CALIB_OFFSET_START_REGISTER, CALIB_OFFSET_LENGTH)
        self._write(OPR_MODE_REGISTER, bytes([MODE_NDOF]))
        time.sleep(0.03)
        return data

    def set_calibration_offsets(self, offset_bytes):
        """Writes a previously-saved 22-byte calibration offset profile
        back to the sensor. Call this right after connecting, before
        relying on calibrated data, to skip re-doing the calibration
        dance every session. Switches to CONFIG mode to write (required),
        then back to NDOF. Returns True on success."""
        if offset_bytes is None or len(offset_bytes) != CALIB_OFFSET_LENGTH:
            return False
        self._write(OPR_MODE_REGISTER, bytes([MODE_CONFIG]))
        time.sleep(0.03)
        ok = self._write(CALIB_OFFSET_START_REGISTER, bytes(offset_bytes))
        self._write(OPR_MODE_REGISTER, bytes([MODE_NDOF]))
        time.sleep(0.03)
        return ok

    def close(self):
        try:
            self._ser.close()
        except Exception:
            pass
