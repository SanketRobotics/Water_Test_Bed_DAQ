#!/usr/bin/env bash
# One-shot setup for a fresh Raspberry Pi (Raspberry Pi OS).
set -e

echo "==> Installing system packages (PyQt5 must come from apt, not pip)"
sudo apt update
sudo apt install -y git python3-venv python3-dev swig libgpiod-dev \
    python3-pyqt5 python3-pyqtgraph

echo "==> Creating virtual environment (with system site packages)"
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

echo "==> Installing Python packages"
# PyQt5 and pyqtgraph come from apt above; do NOT pip-install them.
pip install gpiod pyserial

echo "==> Adding user to serial/USB groups"
sudo usermod -aG dialout,plugdev "$USER"

mkdir -p data

echo
echo "Setup done. REBOOT now so group changes apply:  sudo reboot"
echo "After reboot:"
echo "  cd ~/Water_Test_Bed && source .venv/bin/activate"
echo "  ls /dev/ttyUSB*        # confirm IMU port, edit config.py if not ttyUSB0"
echo "  python3 calibrate.py       # load cell"
echo "  python3 calibrate_imu.py   # IMU"
echo "  python3 main_app.py"
