"""
Water Test Bed -- main touchscreen GUI application (PyQt5 + PyQtGraph).

During a test (max ~15s per spec):
    - Live acceleration graph (X, Y, Z vs time)
    - Live velocity graph (X, Y, Z vs time, integrated from acceleration)
    - Live load graph (grams vs time)

After a test stops:
    - Live graphs are replaced with a simple "Test Complete" screen
      showing the saved filename and instructions for downloading it
      over WiFi. No further live plotting is needed at that point --
      per spec, the CSV is the only thing needed for review/download.

To make the CSV downloadable over WiFi, run this alongside the app
(in a separate terminal/SSH session):

    cd ~/Water_Test_Bed/data
    python3 -m http.server 8000

Then from any device on the same network:  http://<pi-ip>:8000/
"""

import socket
import sys
import time
from collections import deque

from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg

import config
from hx711_sensor import HX711
from bno055_sensor import BNO055Sensor
from data_logger import DataLogger

MAX_TEST_SECONDS = 15
GRAPH_MAX_POINTS = int(MAX_TEST_SECONDS / config.SAMPLE_INTERVAL_S) + 20
DOWNLOAD_PORT = 8000


def get_local_ip():
    """Best-effort local IP lookup for the on-screen download instructions."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "<pi-ip-address>"


class SensorWorker(QtCore.QThread):
    """Runs the sample loop on a background Qt thread so the GUI never
    blocks. Emits each new sample via a signal -- the safe way to pass
    data back to widgets on the main thread."""

    sample_ready = QtCore.pyqtSignal(dict)
    test_time_limit_reached = QtCore.pyqtSignal()

    def __init__(self, logger, max_seconds=MAX_TEST_SECONDS, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.max_seconds = max_seconds
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            row = self.logger.sample_once()
            self.sample_ready.emit(row)
            if row["elapsed_s"] >= self.max_seconds:
                self.test_time_limit_reached.emit()
                break
            time.sleep(config.SAMPLE_INTERVAL_S)

    def stop(self):
        self._running = False


class WaterTestBedApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Water Test Bed")
        self.showFullScreen()

        self.times = deque(maxlen=GRAPH_MAX_POINTS)
        self.ax_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.ay_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.az_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.vx_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.vy_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.vz_vals = deque(maxlen=GRAPH_MAX_POINTS)
        self.load_vals = deque(maxlen=GRAPH_MAX_POINTS)

        self.running = False
        self.worker = None
        self.last_csv_path = None
        self._last_known_load = float("nan")  # holds forward between HX711 samples

        self._build_ui()
        self._init_sensors()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self.main_layout = QtWidgets.QVBoxLayout(central)
        central.setStyleSheet("background-color: #1e1e1e;")

        # --- Top status row (always visible) ---
        top_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Status: Initializing sensors...")
        self.status_label.setStyleSheet("color: #ffcc00; font-size: 18px; font-weight: bold;")
        top_row.addWidget(self.status_label)

        self.imu_cal_label = QtWidgets.QLabel("IMU Cal: ---")
        self.imu_cal_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        top_row.addWidget(self.imu_cal_label)
        top_row.addStretch()

        exit_btn = QtWidgets.QPushButton("Exit")
        exit_btn.setFixedSize(90, 40)
        exit_btn.clicked.connect(self.close)
        top_row.addWidget(exit_btn)
        self.main_layout.addLayout(top_row)

        # --- Main content: graphs, persistent across tests until reset ---
        self.test_view = self._build_test_view()
        self.main_layout.addWidget(self.test_view, stretch=1)

        # --- Download popup overlay (floats on top, hidden by default) ---
        self.download_popup = self._build_download_popup()

        # --- Bottom control buttons (always visible) ---
        btn_row = QtWidgets.QHBoxLayout()

        self.start_btn = QtWidgets.QPushButton("START TEST")
        self.start_btn.setMinimumHeight(70)
        self.start_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; font-size: 20px; font-weight: bold;"
        )
        self.start_btn.clicked.connect(self.on_start)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("STOP TEST")
        self.stop_btn.setMinimumHeight(70)
        self.stop_btn.setStyleSheet(
            "background-color: #c62828; color: white; font-size: 20px; font-weight: bold;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop)
        btn_row.addWidget(self.stop_btn)

        self.tare_btn = QtWidgets.QPushButton("TARE")
        self.tare_btn.setMinimumHeight(70)
        self.tare_btn.setStyleSheet(
            "background-color: #455a64; color: white; font-size: 16px;"
        )
        self.tare_btn.clicked.connect(self.on_tare)
        btn_row.addWidget(self.tare_btn)

        self.new_test_btn = QtWidgets.QPushButton("NEW TEST")
        self.new_test_btn.setMinimumHeight(70)
        self.new_test_btn.setStyleSheet(
            "background-color: #1565c0; color: white; font-size: 18px; font-weight: bold;"
        )
        self.new_test_btn.clicked.connect(self.on_new_test)
        self.new_test_btn.hide()
        btn_row.addWidget(self.new_test_btn)

        self.main_layout.addLayout(btn_row)

    def _build_test_view(self):
        """The live 3-graph view shown while a test is running (and
        idle/ready before the first test)."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        pg.setConfigOption("background", "#1e1e1e")
        pg.setConfigOption("foreground", "w")

        # Readout row -- X emphasized as the primary motion axis
        readout_row = QtWidgets.QHBoxLayout()
        self.load_label = QtWidgets.QLabel("Load: --- g  /  --- N")
        self.load_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        readout_row.addWidget(self.load_label)

        self.accel_label = QtWidgets.QLabel("Accel X: ---  (Y/Z: ---/---)")
        self.accel_label.setStyleSheet("color: white; font-size: 15px; font-weight: bold;")
        readout_row.addWidget(self.accel_label)

        self.vel_label = QtWidgets.QLabel("Vel X: ---  (Y/Z: ---/---)")
        self.vel_label.setStyleSheet("color: white; font-size: 15px; font-weight: bold;")
        readout_row.addWidget(self.vel_label)
        readout_row.addStretch()
        layout.addLayout(readout_row)

        # Acceleration graph -- X (motion axis) bold/bright, Y/Z thin/muted
        self.accel_plot = pg.PlotWidget(title="Acceleration (m/s\u00b2) -- X is motion axis")
        self.accel_plot.setLabel("bottom", "Time", units="s")
        self.accel_plot.addLegend()
        self.accel_plot.showGrid(x=True, y=True, alpha=0.3)
        self.accel_curve_y = self.accel_plot.plot(pen=pg.mkPen("#555555", width=1), name="Y")
        self.accel_curve_z = self.accel_plot.plot(pen=pg.mkPen("#555555", width=1), name="Z")
        self.accel_curve_x = self.accel_plot.plot(pen=pg.mkPen("#ff5252", width=3), name="X (motion)")
        layout.addWidget(self.accel_plot, stretch=1)

        # Velocity graph -- same emphasis pattern
        self.vel_plot = pg.PlotWidget(title="Velocity (m/s) -- X is motion axis")
        self.vel_plot.setLabel("bottom", "Time", units="s")
        self.vel_plot.addLegend()
        self.vel_plot.showGrid(x=True, y=True, alpha=0.3)
        self.vel_curve_y = self.vel_plot.plot(pen=pg.mkPen("#555555", width=1), name="Y")
        self.vel_curve_z = self.vel_plot.plot(pen=pg.mkPen("#555555", width=1), name="Z")
        self.vel_curve_x = self.vel_plot.plot(pen=pg.mkPen("#ff5252", width=3), name="X (motion)")
        layout.addWidget(self.vel_plot, stretch=1)

        # Load graph
        self.load_plot = pg.PlotWidget(title="Load (g)")
        self.load_plot.setLabel("bottom", "Time", units="s")
        self.load_plot.showGrid(x=True, y=True, alpha=0.3)
        self.load_curve = self.load_plot.plot(pen=pg.mkPen("y", width=2))
        layout.addWidget(self.load_plot, stretch=1)

        return widget

    def _build_download_popup(self):
        """A small overlay popup shown on top of the (still-visible)
        graphs after a test completes. Stays until dismissed or until
        a new test starts."""
        popup = QtWidgets.QFrame(self)
        popup.setStyleSheet(
            "QFrame { background-color: #2a2a2a; border: 2px solid #66bb6a; border-radius: 10px; }"
        )
        popup.setFixedWidth(420)

        layout = QtWidgets.QVBoxLayout(popup)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        check_label = QtWidgets.QLabel("\u2713 Test Complete")
        check_label.setStyleSheet("color: #66bb6a; font-size: 22px; font-weight: bold; border: none;")
        check_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(check_label)

        self.result_filename_label = QtWidgets.QLabel("")
        self.result_filename_label.setStyleSheet("color: white; font-size: 14px; border: none;")
        self.result_filename_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.result_filename_label)

        self.result_samples_label = QtWidgets.QLabel("")
        self.result_samples_label.setStyleSheet("color: #aaaaaa; font-size: 11px; border: none;")
        self.result_samples_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.result_samples_label)

        layout.addSpacing(10)

        download_title = QtWidgets.QLabel("Download over WiFi:")
        download_title.setStyleSheet("color: white; font-size: 13px; font-weight: bold; border: none;")
        download_title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(download_title)

        ip = get_local_ip()
        self.result_url_label = QtWidgets.QLabel(f"http://{ip}:{DOWNLOAD_PORT}/")
        self.result_url_label.setStyleSheet(
            "color: #64b5f6; font-size: 18px; font-weight: bold; padding: 6px; border: none;"
        )
        self.result_url_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.result_url_label)

        dismiss_btn = QtWidgets.QPushButton("Dismiss")
        dismiss_btn.setStyleSheet(
            "background-color: #455a64; color: white; font-size: 13px; padding: 6px;"
        )
        dismiss_btn.clicked.connect(self.on_dismiss_popup)
        layout.addWidget(dismiss_btn)

        popup.hide()
        return popup

    def _reposition_popup(self):
        """Centers the popup over the graphs area."""
        if self.download_popup.isHidden():
            return
        popup_size = self.download_popup.sizeHint()
        x = (self.width() - popup_size.width()) // 2
        y = (self.height() - popup_size.height()) // 2
        self.download_popup.setGeometry(x, y, popup_size.width(), popup_size.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "download_popup"):
            self._reposition_popup()

    # ------------------------------------------------------------------
    # Sensor init
    # ------------------------------------------------------------------
    def _init_sensors(self):
        try:
            self.hx711 = HX711()
            self.imu = BNO055Sensor()
            self.logger = DataLogger(self.hx711, self.imu)
            self.status_label.setText("Status: Sensors ready.")
            self.status_label.setStyleSheet("color: #66bb6a; font-size: 18px; font-weight: bold;")

            # Poll IMU calibration status periodically (independent of
            # the per-sample loop, since calibration changes slowly --
            # no need to check it 20x/second).
            self.cal_timer = QtCore.QTimer(self)
            self.cal_timer.timeout.connect(self._update_imu_cal_display)
            self.cal_timer.start(2000)  # every 2 seconds
            self._update_imu_cal_display()
        except Exception as e:
            self.status_label.setText(f"Status: SENSOR INIT FAILED - {e}")
            self.status_label.setStyleSheet("color: #ef5350; font-size: 18px; font-weight: bold;")
            self.hx711 = None
            self.imu = None
            self.logger = None

    def _update_imu_cal_display(self):
        if not getattr(self, "imu", None):
            return
        sys_c, gyro_c, accel_c, mag_c = self.imu.get_calibration_status()
        if sys_c is None:
            self.imu_cal_label.setText("IMU Cal: (read error)")
            self.imu_cal_label.setStyleSheet("color: #ef5350; font-size: 13px;")
            return

        text = f"IMU Cal -- Sys:{sys_c} Gyro:{gyro_c} Accel:{accel_c} Mag:{mag_c}"
        self.imu_cal_label.setText(text)

        # Color-code: green if fully usable, yellow if partial, red if poor.
        # Gyro and Mag matter most for our use case (accel is factory
        # calibrated and usable even at 0).
        if gyro_c == 3 and mag_c >= 2:
            color = "#66bb6a"  # green
        elif gyro_c >= 1 or mag_c >= 1:
            color = "#ffcc00"  # yellow
        else:
            color = "#ef5350"  # red
        self.imu_cal_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def on_tare(self):
        if not self.hx711:
            return
        self.status_label.setText("Status: Taring...")
        self.status_label.setStyleSheet("color: #ffcc00; font-size: 18px; font-weight: bold;")
        QtWidgets.QApplication.processEvents()
        self.hx711.tare()
        self.status_label.setText("Status: Tare complete.")
        self.status_label.setStyleSheet("color: #66bb6a; font-size: 18px; font-weight: bold;")

    def on_start(self):
        if self.running or self.logger is None:
            return
        self.running = True

        self.download_popup.hide()

        self.times.clear()
        self.ax_vals.clear()
        self.ay_vals.clear()
        self.az_vals.clear()
        self.vx_vals.clear()
        self.vy_vals.clear()
        self.vz_vals.clear()
        self.load_vals.clear()
        self._last_known_load = float("nan")

        path = self.logger.start()
        self.last_csv_path = path

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tare_btn.setEnabled(False)
        self.new_test_btn.hide()
        self.status_label.setText("Status: TEST RUNNING")
        self.status_label.setStyleSheet("color: #ff7043; font-size: 18px; font-weight: bold;")

        self.worker = SensorWorker(self.logger, max_seconds=MAX_TEST_SECONDS)
        self.worker.sample_ready.connect(self._on_sample)
        self.worker.test_time_limit_reached.connect(self.on_stop)
        self.worker.start()

    def on_stop(self):
        if not self.running:
            return
        self.running = False

        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None

        path = self.logger.stop()
        sample_count = self.logger.sample_count

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.tare_btn.setEnabled(True)

        self.status_label.setText("Status: Test stopped. Saved.")
        self.status_label.setStyleSheet("color: #66bb6a; font-size: 18px; font-weight: bold;")

        filename = path.split("/")[-1] if path else "(unknown)"
        self.result_filename_label.setText(f"Saved as: {filename}")
        self.result_samples_label.setText(f"{sample_count} samples recorded")

        self.download_popup.show()
        self.download_popup.raise_()
        self._reposition_popup()

        self.start_btn.hide()
        self.new_test_btn.show()

    def on_dismiss_popup(self):
        """Hides the popup but keeps the finished graphs visible."""
        self.download_popup.hide()

    def on_new_test(self):
        """Hides the popup and clears the way for a new test -- graphs
        stay visible until on_start() clears them."""
        self.download_popup.hide()
        self.new_test_btn.hide()
        self.start_btn.show()

    def closeEvent(self, event):
        if self.running:
            self.on_stop()
        if getattr(self, "hx711", None):
            self.hx711.close()
        if getattr(self, "imu", None):
            self.imu.close()
        event.accept()

    # ------------------------------------------------------------------
    # Sample handling (runs on the GUI/main thread via Qt signal)
    # ------------------------------------------------------------------
    def _on_sample(self, row):
        t = row["elapsed_s"]
        self.times.append(t)
        self.ax_vals.append(row["accel_x"] if row["accel_x"] is not None else float("nan"))
        self.ay_vals.append(row["accel_y"] if row["accel_y"] is not None else float("nan"))
        self.az_vals.append(row["accel_z"] if row["accel_z"] is not None else float("nan"))
        self.vx_vals.append(row["vel_x"])
        self.vy_vals.append(row["vel_y"])
        self.vz_vals.append(row["vel_z"])
        if row["load_g"] is not None:
            self._last_known_load = row["load_g"]
        self.load_vals.append(self._last_known_load)

        times_list = list(self.times)

        self.accel_curve_x.setData(times_list, list(self.ax_vals))
        self.accel_curve_y.setData(times_list, list(self.ay_vals))
        self.accel_curve_z.setData(times_list, list(self.az_vals))

        self.vel_curve_x.setData(times_list, list(self.vx_vals))
        self.vel_curve_y.setData(times_list, list(self.vy_vals))
        self.vel_curve_z.setData(times_list, list(self.vz_vals))

        self.load_curve.setData(times_list, list(self.load_vals))

        load_g = row["load_g"]
        load_n = row["load_N"]
        load_text = "Load: {} g  /  {} N".format(
            "---" if load_g is None else f"{load_g:.1f}",
            "---" if load_n is None else f"{load_n:.3f}",
        )
        accel_text = "Accel X: {}  (Y/Z: {}/{})".format(
            "---" if row["accel_x"] is None else f"{row['accel_x']:.2f}",
            "---" if row["accel_y"] is None else f"{row['accel_y']:.2f}",
            "---" if row["accel_z"] is None else f"{row['accel_z']:.2f}",
        )
        vel_text = "Vel X: {:.2f}  (Y/Z: {:.2f}/{:.2f})".format(
            row["vel_x"], row["vel_y"], row["vel_z"]
        )
        self.load_label.setText(load_text)
        self.accel_label.setText(accel_text)
        self.vel_label.setText(vel_text)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = WaterTestBedApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
