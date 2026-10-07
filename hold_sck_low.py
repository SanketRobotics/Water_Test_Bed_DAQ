import gpiod, time
from gpiod.line import Direction, Value
import config
req = gpiod.request_lines(config.HX711_CHIP, consumer="hold-sck",
    config={config.HX711_SCK_PIN: gpiod.LineSettings(
        direction=Direction.OUTPUT, output_value=Value.INACTIVE)})
print("Holding SCK LOW. Measure DAT pad vs GND. Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    req.release()
