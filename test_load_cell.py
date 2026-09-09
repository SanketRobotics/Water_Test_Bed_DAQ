"""
Quick standalone check: load cell only, using the saved calibration.

Run:
    python3 test_load_cell.py

Prints live grams/Newtons continuously. Ctrl+C to stop.
"""

import time
from hx711_sensor import HX711

print("Load cell test (using saved calibration.json)")
hx = HX711()
print(f"Tare offset: {hx.tare_offset:.1f}")
print(f"Calibration factor: {hx.calibration_factor:.4f}")
print("\nReading live values. Ctrl+C to stop.\n")

try:
    while True:
        grams = hx.get_grams()
        if grams is None:
            print("No reading (timeout or noise rejected)")
        else:
            newtons = (grams / 1000.0) * 9.80665
            print(f"Load: {grams:8.1f} g   {newtons:7.3f} N")
        time.sleep(0.2)
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    hx.close()
