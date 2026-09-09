# Water Test Bed: Data Acquisition System

Logs load cell (HX711 + YZC-131) and IMU (BNO055, UART) data on a
Raspberry Pi 4B, shows live graphs on a touchscreen (PyQt5 + PyQtGraph),
and saves timestamped CSVs downloadable over WiFi.

## Hardware
- Raspberry Pi 4B with the **official 5V/3A power supply** (generic adapters caused severe HX711 noise)
- HX711 amp: DAT -> GPIO 5 (pin 29), CLK -> GPIO 6 (pin 31), VCC 5V, GND
- BNO055 via HW-417 USB-to-TTL (plugs into a Pi USB port, appears as /dev/ttyUSB0)
  - PS1 -> 3.3V is **required** (selects UART mode)
  - BNO055 RX <-> HW-417 TX, TX <-> RX, VIN, GND
  - Mount flat, chip facing up; motion axis = X

## Setup on a new Pi
```bash
git clone git@github.com:SanketRobotics/Water_Test_Bed_DAQ.git ~/Water_Test_Bed
cd ~/Water_Test_Bed
./setup.sh
sudo reboot
```
After reboot:
```bash
cd ~/Water_Test_Bed && source .venv/bin/activate
ls /dev/ttyUSB*            # if not ttyUSB0, edit BNO055_UART_PORT in config.py
python3 calibrate.py       # load cell: tare, then known weight
python3 calibrate_imu.py   # IMU: gyro, mag, (optional) accel
python3 main_app.py
```

## Download CSVs over WiFi
In a second terminal: `cd ~/Water_Test_Bed/data && python3 -m http.server 8000`

## Known open issues
- Load cell baseline drift (re-tare right before each test)
- Y/Z velocity drift from naive accelerometer integration
- Occasional multi-second sample gaps
