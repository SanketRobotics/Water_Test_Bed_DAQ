"""
Bypasses the outlier filter entirely -- shows the RAW HX711 reading
every cycle, plus whether it timed out. Use this to see what's
actually coming off the sensor right now.

Run:
    python3 test_load_cell_raw.py
"""

import time
from hx711_sensor import HX711

hx = HX711()
print(f"Tare offset (from calibration.json): {hx.tare_offset:.1f}")
print(f"Calibration factor: {hx.calibration_factor:.4f}")
print("\nRaw readings (bypassing filter). Ctrl+C to stop.\n")

try:
    while True:
        raw = hx.read_raw()
        if raw is None:
            print("TIMEOUT -- no ready signal from HX711")
        else:
            diff = raw - hx.tare_offset
            grams = diff / hx.calibration_factor
            print(f"raw={raw:>10}   diff_from_tare={diff:>10.1f}   grams={grams:>8.1f}")
        time.sleep(0.2)
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    hx.close()
