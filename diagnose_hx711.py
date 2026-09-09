import gpiod
import time

CHIP = "/dev/gpiochip0"
DOUT = 5   # DAT  -- confirmed by tracing physical wire: DAT -> GPIO 5 (pin 29)
SCK  = 6   # CLK  -- CLK -> GPIO 6 (pin 31)

chip = gpiod.Chip(CHIP)

dout = chip.request_lines(
    consumer="hx711-dout-diag",
    config={
        DOUT: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)
    }
)
sck = chip.request_lines(
    consumer="hx711-sck-diag",
    config={
        SCK: gpiod.LineSettings(
            direction=gpiod.line.Direction.OUTPUT,
            output_value=gpiod.line.Value.INACTIVE
        )
    }
)

print("Holding SCK LOW (normal idle state).")
print("Watching DOUT for 5 seconds -- it should go LOW on its own")
print("within ~100ms if the HX711 is powered and wired correctly.\n")

sck.set_value(SCK, gpiod.line.Value.INACTIVE)  # ensure SCK idle low

start = time.time()
went_low = False
while time.time() - start < 5:
    val = dout.get_value(DOUT)
    state = "HIGH" if val == gpiod.line.Value.ACTIVE else "LOW"
    print(f"t={time.time()-start:5.2f}s  DOUT={state}")
    if val == gpiod.line.Value.INACTIVE:
        went_low = True
        print("\n>>> DOUT went LOW -- HX711 is signaling data ready. Good sign!")
        break
    time.sleep(0.1)

if not went_low:
    print("\n>>> DOUT NEVER went LOW in 5 seconds.")
    print(">>> This points to a wiring/power issue, NOT a code/timing issue:")
    print("    - Check HX711 VCC has real 5V (measure with multimeter if possible)")
    print("    - Check GND is common between Pi and HX711 board")
    print("    - Check DOUT wire is actually connected to GPIO 5 physically")
    print("    - Check load cell wires are connected to E+/E-/A+/A- pads, not swapped/loose")
    print("    - Try a different HX711 board if you have one (they do fail)")

dout.release()
sck.release()
