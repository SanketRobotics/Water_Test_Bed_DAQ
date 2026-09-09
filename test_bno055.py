"""
Standalone BNO055 test -- confirms UART communication is working
and verifies the Z-axis sign correction (should read ~+9.8 m/s^2
when the sensor sits flat and still, chip facing up).

Run:
    python3 test_bno055.py
"""

import time
from bno055_sensor import BNO055Sensor

print("BNO055 UART test (using corrected BNO055Sensor class)")

try:
    imu = BNO055Sensor()
except Exception as e:
    print(f"FAILED to initialize BNO055: {e}")
    print("Check: HW-417 plugged in? Correct port in config.py? Wiring OK?")
    raise SystemExit(1)

print("BNO055 ready. Reading data for 15 seconds...\n")
print("Expect Z to read close to +9.8 m/s^2 while flat and still.")
print("(Calibration status shown as sys,gyro,accel,mag -- each 0-3,")
print(" 3=fully calibrated. Normal to start at 0 and rise as you")
print(" move the sensor around during this test.)\n")

try:
    start = time.time()
    while time.time() - start < 15:
        ax, ay, az = imu.get_acceleration()
        cal = imu.get_calibration_status()

        if ax is None:
            print("No valid acceleration data yet...")
        else:
            print(
                f"Accel: X={ax:7.3f}  Y={ay:7.3f}  Z={az:7.3f} m/s^2   "
                f"Calib(sys,gyro,acc,mag)={cal}"
            )
        time.sleep(0.2)
except KeyboardInterrupt:
    pass

print("\nTest complete.")
imu.close()
        
