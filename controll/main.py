import sys
import csv
import time
import serial
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QCheckBox,
    QGroupBox,
    QSplitter,
    QMessageBox,
    QFileDialog,
    QStatusBar,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

import matplotlib

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

BAUD_RATE = 115200
OUTPUT_FILE = "scan_data.csv"


# ══════════════════════════════════════════════
# 点动工作线程
# ══════════════════════════════════════════════


class JogWorker(QThread):
    status_msg = pyqtSignal(str)
    error_msg = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, ser: serial.Serial, command: str, expect: str):
        super().__init__()
        self.ser = ser
        self.command = command  # 已编码的字节字符串（str，run 内编码）
        self.expect = expect    # 期待的响应关键字

    def run(self):
        try:
            self.ser.reset_input_buffer()
            self.ser.write(self.command.encode("utf-8"))
            deadline = time.time() + 30.0
            while time.time() < deadline:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if self.expect in line:
                    self.status_msg.emit(f"完成: {line}")
                    return
            self.error_msg.emit("等待 Arduino 响应超时")
        except serial.SerialException as e:
            self.error_msg.emit(f"串口错误: {e}")
        finally:
            self.finished.emit()


# ══════════════════════════════════════════════
# 扫描工作线程
# ══════════════════════════════════════════════


class ScanWorker(QThread):
    data_point = pyqtSignal(int, int, int)  # cycle, pos_steps, photon
    status_msg = pyqtSignal(str)
    error_msg = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, port_slider, port_detector, start_steps, end_steps, step_steps, cycles):
        super().__init__()
        self.port_slider = port_slider
        self.port_detector = port_detector
        self.start_steps = start_steps
        self.end_steps = end_steps
        self.step_steps = step_steps
        self.cycles = cycles
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def _read_photon(self, ser_det):
        """清空缓冲区，丢弃第一个有效行，返回第二个有效整数。"""
        ser_det.reset_input_buffer()
        # 丢弃第一个
        while not self._stop_flag:
            raw = ser_det.readline().decode("utf-8", errors="ignore").strip()
            if raw:
                break
        # 读取第二个
        while not self._stop_flag:
            raw = ser_det.readline().decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            try:
                return int(raw)
            except ValueError:
                continue
        return None

    def run(self):
        ser_slider = None
        ser_det = None
        try:
            ser_slider = serial.Serial(self.port_slider, BAUD_RATE, timeout=5)
            ser_det = serial.Serial(self.port_detector, BAUD_RATE, timeout=5)

            self.status_msg.emit("等待 Arduino 复位 (2s)...")
            time.sleep(2)
            ser_slider.reset_input_buffer()

            # 发送扫描参数
            cmd = (
                f"P:{self.start_steps},{self.end_steps},"
                f"{self.step_steps},{self.cycles}\n"
            )
            ser_slider.write(cmd.encode("utf-8"))
            self.status_msg.emit(f"已发送参数: {cmd.strip()}")

            deadline = time.time() + 5.0
            param_ok = False
            while time.time() < deadline and not self._stop_flag:
                line = ser_slider.readline().decode("utf-8", errors="ignore").strip()
                if line == "PARAM_OK":
                    param_ok = True
                    break
            if not param_ok:
                self.status_msg.emit("[警告] 未收到参数确认，继续...")

            # 发送开始指令
            ser_slider.write(b"S\n")
            self.status_msg.emit("扫描进行中...")

            while not self._stop_flag:
                line = ser_slider.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if "SCAN_FINISHED" in line:
                    self.status_msg.emit("扫描完成！")
                    break

                if line.startswith("X:"):
                    try:
                        parts = line.split(",")
                        pos_steps = int(parts[0].split(":")[1])
                        cycle_n = int(parts[1].split(":")[1])
                    except (IndexError, ValueError):
                        ser_slider.write(b"G\n")
                        continue

                    self.status_msg.emit(
                        f"[第 {cycle_n} 次]  {pos_steps} 步 — 读取光子数..."
                    )

                    photon = self._read_photon(ser_det)
                    if photon is None:
                        break

                    self.data_point.emit(cycle_n, pos_steps, photon)
                    ser_slider.write(b"G\n")

        except serial.SerialException as e:
            self.error_msg.emit(f"串口错误: {e}")
        finally:
            if ser_slider:
                ser_slider.close()
            if ser_det:
                ser_det.close()
            self.finished.emit()


# ══════════════════════════════════════════════
# Matplotlib 画布
# ══════════════════════════════════════════════


class ScanCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure(tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self._data: dict[int, tuple[list, list]] = {}  # {cycle: ([x], [y])}
        self._log_scale = False
        self._setup_axes()

    def _setup_axes(self):
        self.ax.set_xlabel("位置 (步)", fontsize=11)
        self.ax.set_ylabel("光子数", fontsize=11)
        self.ax.set_title("实时扫描数据", fontsize=12)
        self.ax.grid(True, which="both", linestyle="--", alpha=0.5)

    def clear_data(self):
        self._data.clear()
        self.ax.cla()
        self._setup_axes()
        self.draw()

    def add_point(self, cycle: int, pos_steps: int, photon: int):
        if cycle not in self._data:
            self._data[cycle] = ([], [])
        self._data[cycle][0].append(pos_steps)
        self._data[cycle][1].append(photon)
        self._redraw()

    def set_log_scale(self, enabled: bool):
        self._log_scale = enabled
        self._redraw()

    def _redraw(self):
        self.ax.cla()
        self._setup_axes()

        try:
            cmap = matplotlib.colormaps["tab10"]
        except AttributeError:
            cmap = matplotlib.cm.get_cmap("tab10")  # matplotlib < 3.7 兼容

        for cycle, (xs, ys) in sorted(self._data.items()):
            color = cmap(((cycle - 1) % 10) / 10)
            self.ax.scatter(xs, ys, s=20, color=color, label=f"第 {cycle} 次", zorder=3)

        # 对数坐标：用 symlog 避免 0 值报错
        if self._log_scale:
            self.ax.set_yscale("symlog", linthresh=1)
            self.ax.set_ylabel("光子数 (对数)", fontsize=11)
        else:
            self.ax.set_yscale("linear")
            self.ax.set_ylabel("光子数", fontsize=11)

        if len(self._data) > 1:
            self.ax.legend(fontsize=9, loc="best")

        self.ax.grid(True, which="both", linestyle="--", alpha=0.5)
        self.draw()


# ══════════════════════════════════════════════
# 主窗口
# ══════════════════════════════════════════════


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("光子计数扫描系统")
        self.resize(1150, 680)
        self.worker = None
        self.csv_file = None
        self.csv_writer = None
        self._jog_ser: serial.Serial | None = None
        self._jog_worker: JogWorker | None = None
        self._build_ui()

    # ── 界面构建 ────────────────────────────────

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._panel_left())
        splitter.addWidget(self._panel_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([295, 855])
        self.setCentralWidget(splitter)

        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪")

    def _panel_left(self):
        panel = QWidget()
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(self._group_ports())
        layout.addWidget(self._group_calibration())
        layout.addWidget(self._group_params())
        layout.addWidget(self._group_output())
        layout.addStretch()
        layout.addWidget(self._btn_start())
        return panel

    def _group_ports(self):
        group = QGroupBox("串口配置")
        layout = QFormLayout(group)
        layout.setSpacing(6)

        self.combo_slider = QComboBox()
        btn_s = QPushButton("扫描")
        btn_s.setFixedWidth(48)
        btn_s.clicked.connect(lambda: self._refresh_ports(self.combo_slider))
        row_s = QHBoxLayout()
        row_s.addWidget(self.combo_slider)
        row_s.addWidget(btn_s)
        layout.addRow("滑台:", row_s)

        self.combo_det = QComboBox()
        btn_d = QPushButton("扫描")
        btn_d.setFixedWidth(48)
        btn_d.clicked.connect(lambda: self._refresh_ports(self.combo_det))
        row_d = QHBoxLayout()
        row_d.addWidget(self.combo_det)
        row_d.addWidget(btn_d)
        layout.addRow("探测器:", row_d)

        # 启动时自动扫描一次
        self._refresh_ports(self.combo_slider)
        self._refresh_ports(self.combo_det)
        return group

    def _group_calibration(self):
        group = QGroupBox("校准零点")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 连接/断开按钮
        self.btn_jog_connect = QPushButton("连接滑台")
        self.btn_jog_connect.setCheckable(True)
        self.btn_jog_connect.clicked.connect(self._on_jog_connect)
        layout.addWidget(self.btn_jog_connect)

        # 步数输入
        row_steps = QHBoxLayout()
        row_steps.addWidget(QLabel("步数:"))
        self.edit_jog_steps = QLineEdit("1600")
        self.edit_jog_steps.setFixedWidth(80)
        row_steps.addWidget(self.edit_jog_steps)
        row_steps.addStretch()
        layout.addLayout(row_steps)

        # 前进 / 后退
        row_move = QHBoxLayout()
        self.btn_backward = QPushButton("← 后退")
        self.btn_forward = QPushButton("前进 →")
        self.btn_backward.clicked.connect(lambda: self._do_jog(forward=False))
        self.btn_forward.clicked.connect(lambda: self._do_jog(forward=True))
        row_move.addWidget(self.btn_backward)
        row_move.addWidget(self.btn_forward)
        layout.addLayout(row_move)

        # 设为零点
        self.btn_set_zero = QPushButton("设为零点")
        self.btn_set_zero.clicked.connect(self._do_set_zero)
        layout.addWidget(self.btn_set_zero)

        self._set_jog_controls_enabled(False)
        return group

    def _group_params(self):
        group = QGroupBox("扫描参数")
        layout = QFormLayout(group)
        layout.setSpacing(6)

        self.edit_start = QLineEdit("0")
        self.edit_end = QLineEdit("80000")
        self.edit_step = QLineEdit("1600")
        self.edit_cycles = QLineEdit("1")

        layout.addRow("起始 (步):", self.edit_start)
        layout.addRow("终止 (步):", self.edit_end)
        layout.addRow("步长 (步):", self.edit_step)
        layout.addRow("往复次数:", self.edit_cycles)
        return group

    def _group_output(self):
        group = QGroupBox("输出 & 显示")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.edit_file = QLineEdit(OUTPUT_FILE)
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_file)
        row.addWidget(self.edit_file)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        self.chk_log = QCheckBox("Y 轴对数坐标")
        self.chk_log.toggled.connect(self.canvas_widget_ref_placeholder)  # 延迟绑定
        layout.addWidget(self.chk_log)
        return group

    def _btn_start(self):
        self.btn_start = QPushButton("开始扫描")
        self.btn_start.setFixedHeight(46)
        f = self.btn_start.font()
        f.setPointSize(12)
        f.setBold(True)
        self.btn_start.setFont(f)
        self.btn_start.clicked.connect(self._on_start_stop)
        return self.btn_start

    def _panel_right(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self.canvas = ScanCanvas()
        self.toolbar = NavigationToolbar(self.canvas, widget)

        # 现在 canvas 已创建，绑定对数切换信号
        self.chk_log.toggled.connect(self.canvas.set_log_scale)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        return widget

    # ── 串口扫描 ────────────────────────────────

    def _refresh_ports(self, combo: QComboBox):
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
        current = combo.currentData()
        combo.clear()
        for p in ports:
            combo.addItem(f"{p.device}  —  {p.description}", userData=p.device)
        idx = combo.findData(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    # ── 校准零点 ────────────────────────────────

    def _set_jog_controls_enabled(self, enabled: bool):
        self.btn_backward.setEnabled(enabled)
        self.btn_forward.setEnabled(enabled)
        self.btn_set_zero.setEnabled(enabled)
        self.edit_jog_steps.setEnabled(enabled)

    def _on_jog_connect(self, checked: bool):
        if checked:
            port = self.combo_slider.currentData()
            if not port:
                QMessageBox.warning(self, "串口错误", "请先选择滑台串口")
                self.btn_jog_connect.setChecked(False)
                return
            try:
                self._jog_ser = serial.Serial(port, BAUD_RATE, timeout=5)
                self.btn_jog_connect.setText("断开滑台")
                self.statusbar.showMessage("等待 Arduino 复位 (2s)...")
                # 在后台等待，不阻塞 UI
                QThread.msleep(2000)
                self._jog_ser.reset_input_buffer()
                self._set_jog_controls_enabled(True)
                self.statusbar.showMessage("滑台已连接，可开始校准")
            except serial.SerialException as e:
                self._jog_ser = None
                self.btn_jog_connect.setChecked(False)
                QMessageBox.critical(self, "连接失败", str(e))
        else:
            self._disconnect_jog()

    def _disconnect_jog(self):
        if self._jog_ser and self._jog_ser.is_open:
            self._jog_ser.close()
        self._jog_ser = None
        self.btn_jog_connect.setChecked(False)
        self.btn_jog_connect.setText("连接滑台")
        self._set_jog_controls_enabled(False)
        self.statusbar.showMessage("滑台已断开")

    def _run_jog_command(self, command: str, expect: str):
        if not self._jog_ser or not self._jog_ser.is_open:
            return
        if self._jog_worker and self._jog_worker.isRunning():
            return  # 上一条指令还在执行

        self._set_jog_controls_enabled(False)
        self.btn_jog_connect.setEnabled(False)

        self._jog_worker = JogWorker(self._jog_ser, command, expect)
        self._jog_worker.status_msg.connect(self.statusbar.showMessage)
        self._jog_worker.error_msg.connect(
            lambda msg: QMessageBox.critical(self, "错误", msg)
        )
        self._jog_worker.finished.connect(self._on_jog_finished)
        self._jog_worker.start()

    def _on_jog_finished(self):
        self._set_jog_controls_enabled(True)
        self.btn_jog_connect.setEnabled(True)

    def _do_jog(self, forward: bool):
        try:
            steps = int(self.edit_jog_steps.text())
        except ValueError:
            QMessageBox.warning(self, "输入错误", "步数必须为整数")
            return
        if steps <= 0:
            QMessageBox.warning(self, "输入错误", "步数必须大于 0")
            return
        delta = steps if forward else -steps
        self._run_jog_command(f"J:{delta}\n", "JOG_OK")
        self.statusbar.showMessage(f"点动 {'前进' if forward else '后退'} {steps} 步...")

    def _do_set_zero(self):
        self._run_jog_command("Z\n", "ZERO_OK")
        self.statusbar.showMessage("正在设置零点...")

    # ── 事件处理 ────────────────────────────────

    def _browse_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存数据文件", self.edit_file.text(), "CSV (*.csv)"
        )
        if path:
            self.edit_file.setText(path)

    def _on_start_stop(self):
        if self.worker and self.worker.isRunning():
            self._stop_scan()
        else:
            self._start_scan()

    def _start_scan(self):
        # 参数校验
        try:
            start_steps = int(self.edit_start.text())
            end_steps = int(self.edit_end.text())
            step_steps = int(self.edit_step.text())
            cycles = int(self.edit_cycles.text())
        except ValueError:
            QMessageBox.warning(self, "输入错误", "请检查扫描参数格式")
            return
        if start_steps >= end_steps:
            QMessageBox.warning(self, "输入错误", "起始位置必须小于终止位置")
            return
        if step_steps <= 0:
            QMessageBox.warning(self, "输入错误", "步长必须大于 0")
            return

        port_slider = self.combo_slider.currentData()
        port_det = self.combo_det.currentData()
        if not port_slider or not port_det:
            QMessageBox.warning(self, "串口错误", "请先扫描并选择串口")
            return

        # 校准连接占用同一串口，扫描前自动断开
        if self._jog_ser and self._jog_ser.is_open:
            self._disconnect_jog()

        out_file = self.edit_file.text().strip() or OUTPUT_FILE
        try:
            self.csv_file = open(out_file, "w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["Cycle", "Position_steps", "Photon_Count"])
        except OSError as e:
            QMessageBox.critical(self, "文件错误", str(e))
            return

        self.canvas.clear_data()
        self.btn_start.setText("停止扫描")

        self.worker = ScanWorker(
            port_slider, port_det, start_steps, end_steps, step_steps, cycles
        )
        self.worker.data_point.connect(self._on_data_point)
        self.worker.status_msg.connect(self.statusbar.showMessage)
        self.worker.error_msg.connect(
            lambda msg: QMessageBox.critical(self, "错误", msg)
        )
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.start()

    def _stop_scan(self):
        if self.worker:
            self.worker.stop()
        self.statusbar.showMessage("正在停止...")

    def _on_data_point(self, cycle: int, pos_steps: int, photon: int):
        self.canvas.add_point(cycle, pos_steps, photon)
        if self.csv_writer:
            self.csv_writer.writerow([cycle, pos_steps, photon])
            self.csv_file.flush()

    def _on_scan_finished(self):
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
        self.btn_start.setText("开始扫描")
        self.worker = None

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        if self._jog_ser and self._jog_ser.is_open:
            self._jog_ser.close()
        if self.csv_file:
            self.csv_file.close()
        event.accept()

    # 占位，_panel_right 之前 canvas 尚未创建时使用
    def canvas_widget_ref_placeholder(self, _):
        pass


# ══════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
