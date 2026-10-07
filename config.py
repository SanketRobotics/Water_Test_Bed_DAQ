"""
Central configuration for the Water Test Bed data acquisition system.
Edit values here rather than hunting through other files.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CALIBRATION_FILE = os.path.join(BASE_DIR, "calibration.json")
IMU_CALIBRATION_FILE = os.path.join(BASE_DIR, "imu_calibration.json")

os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------
# HX711 Load Cell (YZC-131, 1kg + SparkFun SEN-13879 amp)
# ---------------------------------------------------------------------
HX711_CHIP = "/dev/gpiochip0"
HX711_DOUT_PIN = 5   # DAT -> GPIO 5 (physical pin 29) -- confirmed by tracing wire
HX711_SCK_PIN = 6    # CLK -> GPIO 6 (physical pin 31)

# Max allowed jump (raw counts) between consecutive readings before a
# reading is treated as noise and rejected.
#
# Raised from 20,000 to 200,000 after testing showed legitimate fast
# weight changes (e.g. placing a weight on the cell) could produce
# single-sample jumps larger than 20,000 raw counts, causing valid
# readings to be wrongly rejected as noise. True electrical glitches
# observed during testing jump into the millions (often landing
# exactly on 2^n-1 values like 8388607), so there's a wide margin
# between real dynamic signal changes and actual noise -- 200,000
# comfortably passes the former while still catching the latter.
HX711_MAX_JUMP = 200000
HX711_READ_TIMEOUT = 2.0  # seconds to wait for a ready signal before giving up

# Standard gravity, used to convert grams to Newtons (F = m * g)
GRAVITY_MS2 = 9.80665

# ---------------------------------------------------------------------
# BNO055 IMU (UART mode, via HW-417 USB-to-TTL converter)
# ---------------------------------------------------------------------
# The BNO055 is connected through an HW-417 (FT232RL-based) USB-to-TTL
# converter plugged into a USB port -- NOT the Pi's GPIO UART pins.
# This means the device shows up as a USB serial port, typically
# /dev/ttyUSB0, rather than /dev/serial0.
BNO055_UART_PORT = "/dev/serial0"
BNO055_UART_BAUD = 115200

# ---------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------
SAMPLE_INTERVAL_S = 0.05  # 20 Hz loop rate

# ---------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------
DEBUG_BNO055 = False  # set True temporarily if BNO055 communication issues resurface


# ---------------------------------------------------------------------
# Calibration persistence
# ---------------------------------------------------------------------
def load_calibration():
    """Returns dict with 'tare_offset' and 'calibration_factor', or
    defaults if no calibration file exists yet."""
    defaults = {"tare_offset": 0.0, "calibration_factor": 1.0}
    if not os.path.exists(CALIBRATION_FILE):
        return defaults
    try:
        with open(CALIBRATION_FILE, "r") as f:
            data = json.load(f)
        defaults.update(data)
        return defaults
    except (json.JSONDecodeError, OSError):
        return defaults


def save_calibration(tare_offset, calibration_factor):
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(
            {"tare_offset": tare_offset, "calibration_factor": calibration_factor},
            f,
            indent=2,
        )


def load_imu_calibration():
    """Returns a list of 22 ints (the saved BNO055 offset/radius
    profile), or None if no saved calibration exists yet."""
    if not os.path.exists(IMU_CALIBRATION_FILE):
        return None
    try:
        with open(IMU_CALIBRATION_FILE, "r") as f:
            data = json.load(f)
        offsets = data.get("offsets")
        if isinstance(offsets, list) and len(offsets) == 22:
            return offsets
        return None
    except (json.JSONDecodeError, OSError):
        return None


def save_imu_calibration(offsets):
    """Saves a 22-byte BNO055 calibration offset profile (as a list of
    ints) so it can be auto-restored on future startups."""
    with open(IMU_CALIBRATION_FILE, "w") as f:
        json.dump({"offsets": list(offsets)}, f, indent=2)
