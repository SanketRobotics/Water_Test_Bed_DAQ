# Water Test Bed: Data Acquisition System

Logs load cell (HX711 + YZC-131) and IMU (BNO055, UART) data on a
Raspberry Pi 4B, shows live graphs on a touchscreen (PyQt5 + PyQtGraph),
and saves timestamped CSVs downloadable over WiFi.

See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md) for hardware, wiring,
install, calibration, architecture, and known issues.

Run: `python3 main_app.py`
