"""
Guided BNO055 IMU calibration.

Run this standalone (not through the GUI) to calibrate the IMU and
save the result, so future app startups can auto-load it instead of
needing a fresh "calibration dance" every time.

    python3 calibrate_imu.py

Background (per Bosch datasheet + community guidance):
    - Gyroscope: calibrates automatically within a few seconds of the
      sensor sitting still in any position. Easiest one.
    - Magnetometer: calibrates from normal movement of the device
      (older guidance called for a strict figure-8 motion, but modern
      BNO055 units use fast magnetic compensation and calibrate from
      general movement). Keep it away from large metal objects/motors
      while doing this.
    - Accelerometer: calibrates by holding the sensor still in 6
      distinct orientations for a few seconds each (each axis facing
      up, then down): +X, -X, +Y, -Y, +Z, +Z. This is the slowest one.
      Note: the accelerometer ships factory-calibrated, so this step
      is not strictly mandatory if you just need usable (not perfect)
      accel data.

Each calibration value is 0-3 (3 = fully calibrated). This script
watches all four (system, gyro, accel, mag) and lets you finish early
if you don't need full accelerometer calibration for your use case.
"""

import time
from bno055_sensor import BNO055Sensor
import config


def print_status(cal):
    sys_c, gyro_c, accel_c, mag_c = cal
    print(
        f"\r  System={sys_c}  Gyro={gyro_c}  Accel={accel_c}  Mag={mag_c}   ",
        end="",
        flush=True,
    )


def wait_for_calibration(imu, target, label, timeout=120):
    """Polls calibration status until `target` (a function of the
    4-tuple) returns True, or timeout. Returns True if achieved."""
    start = time.time()
    while time.time() - start < timeout:
        cal = imu.get_calibration_status()
        print_status(cal)
        if None not in cal and target(cal):
            print(f"\n{label}: calibrated!")
            return True
        time.sleep(0.3)
    print(f"\n{label}: timed out waiting for calibration.")
    return False


def main():
    print("=" * 60)
    print("BNO055 IMU Calibration")
    print("=" * 60)

    imu = BNO055Sensor(auto_load_calibration=False)

    print(
        "\nStep 1: Gyroscope calibration.\n"
        "Place the sensor on a stable, still surface and leave it alone."
    )
    input("Press Enter to start...")
    wait_for_calibration(imu, lambda c: c[1] == 3, "Gyroscope")

    print(
        "\nStep 2: Magnetometer calibration.\n"
        "Gently move the sensor around in the air in various orientations\n"
        "(slow figure-8 motions work well). Keep it away from motors, large\n"
        "metal objects, or speakers."
    )
    input("Press Enter to start...")
    wait_for_calibration(imu, lambda c: c[3] == 3, "Magnetometer")

    print(
        "\nStep 3: Accelerometer calibration (optional but recommended).\n"
        "Hold the sensor still for a few seconds in each of these 6\n"
        "orientations, one at a time: +X up, -X up, +Y up, -Y up, +Z up, -Z up.\n"
        "(i.e. lay it flat, flip it over, stand it on each edge, etc.)\n"
        "This is the slowest step. Watch the Accel status climb to 3 as you\n"
        "work through positions -- it does not need to be done in a specific\n"
        "order, just needs to see each orientation held steady for a couple\n"
        "seconds."
    )
    do_accel = input("Do accelerometer calibration now? (y/n): ").strip().lower()
    if do_accel == "y":
        wait_for_calibration(imu, lambda c: c[2] == 3, "Accelerometer", timeout=180)
    else:
        print("Skipping accelerometer calibration (raw accel data still usable).")

    cal = imu.get_calibration_status()
    print(f"\nFinal calibration status: System={cal[0]} Gyro={cal[1]} Accel={cal[2]} Mag={cal[3]}")

    if cal[1] >= 2 or cal[3] >= 2:
        print("\nSaving calibration profile...")
        ok = imu.save_calibration()
        if ok:
            print(f"Saved to {config.IMU_CALIBRATION_FILE}")
            print("Future app startups will auto-load this calibration.")
        else:
            print("Could not save calibration -- try again, or check sensor connection.")
    else:
        print("\nCalibration too low to be worth saving -- try again.")

    imu.close()


if __name__ == "__main__":
    main()
