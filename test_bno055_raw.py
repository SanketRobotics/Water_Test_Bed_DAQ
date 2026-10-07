"""
Raw serial diagnostic for BNO055 -- bypasses the Adafruit library's
initialization handshake to check if the sensor responds to raw bytes
at all. Helps distinguish a wiring/power problem from a library-level
handshake issue.

BNO055 UART protocol basics:
    Read register:  0xAA 0x01 [reg] [len]
    Good response:  0xBB [len] [data...]
    Error response: 0xEE [error_code]

We'll try reading register 0x00 (CHIP_ID), which should always
return 0xA0 if the sensor is alive and communicating correctly.
"""

import serial
import time

PORT = "/dev/serial0"
BAUD = 115200

print(f"Opening {PORT} at {BAUD} baud...")
ser = serial.Serial(PORT, BAUD, timeout=1.0)
time.sleep(1.0)  # let the port settle

# Clear any junk in the buffers
ser.reset_input_buffer()
ser.reset_output_buffer()

# BNO055 UART read command: 0xAA 0x01 [register] [length]
# Reading CHIP_ID register (0x00), 1 byte
read_chip_id = bytes([0xAA, 0x01, 0x00, 0x01])

print(f"Sending: {read_chip_id.hex(' ')}")
ser.write(read_chip_id)
time.sleep(0.1)

response = ser.read(10)  # read whatever comes back, up to 10 bytes

print(f"Received ({len(response)} bytes): {response.hex(' ') if response else '(nothing)'}")

if len(response) == 0:
    print("\n>>> NO RESPONSE AT ALL.")
    print(">>> This points to a wiring or power issue, not a library issue:")
    print("    - Check BNO055 VIN is actually powered (measure with multimeter)")
    print("    - Check GND is common between HW-417 and BNO055")
    print("    - Check PS1 is wired to 3.3V (required for UART mode)")
    print("    - Check RX/TX are CROSSED: BNO055 RX -> HW-417 TX, BNO055 TX -> HW-417 RX")
    print("    - Try swapping RX/TX if unsure which is which -- a common mixup")
elif len(response) >= 2 and response[0] == 0xBB:
    chip_id = response[2] if len(response) > 2 else response[1]
    print(f"\n>>> GOOD RESPONSE. Chip ID byte: 0x{chip_id:02X}")
    if chip_id == 0xA0:
        print(">>> This matches the expected BNO055 chip ID (0xA0). Sensor is alive!")
    else:
        print(">>> Unexpected chip ID -- got a response, but not what we expected.")
elif len(response) >= 2 and response[0] == 0xEE:
    print(f"\n>>> ERROR RESPONSE from sensor. Error code: 0x{response[1]:02X}")
    print(">>> Sensor is alive and communicating, but reported an error.")
else:
    print("\n>>> UNRECOGNIZED RESPONSE. Got some bytes back, but not in the")
    print(">>> expected format. Could be a baud rate mismatch or noise on the line.")

ser.close()
