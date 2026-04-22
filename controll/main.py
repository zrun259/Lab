import serial
import time
import csv
import sys

# --- 默认配置 ---
PORT_SLIDER = "COM5"   # 滑台 Arduino 串口
PORT_DETECTOR = "COM8" # 探测器串口
BAUD_RATE = 115200
OUTPUT_FILE = "scan_data.csv"


def get_float(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        print("输入无效，使用默认值")
        return default


def get_int(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    if s == "":
        return default
    try:
        return int(s)
    except ValueError:
        print("输入无效，使用默认值")
        return default


def get_str(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    return s if s else default


def read_photon(ser_det):
    """抛弃第一个数据，返回第二个有效光子计数（int）。"""
    # 清空缓冲区，确保下面读到的是最新数据
    ser_det.reset_input_buffer()

    # 丢弃第一个
    while True:
        line = ser_det.readline().decode("utf-8", errors="ignore").strip()
        if line:
            break

    # 读取第二个有效值
    while True:
        line = ser_det.readline().decode("utf-8", errors="ignore").strip()
        if line:
            try:
                return int(line)
            except ValueError:
                # 收到非数字行，继续等
                continue


def configure():
    print("=" * 50)
    print("  光子计数扫描系统  上位机配置")
    print("=" * 50)

    port_slider   = get_str("滑台串口号", PORT_SLIDER)
    port_detector = get_str("探测器串口号", PORT_DETECTOR)
    output_file   = get_str("输出文件名", OUTPUT_FILE)
    start_mm      = get_float("起始位置 (mm)", 0.0)
    end_mm        = get_float("终止位置 (mm)", 50.0)
    step_mm       = get_float("步长 (mm)", 1.0)
    cycles        = get_int("往复次数", 1)

    if start_mm >= end_mm:
        print("错误：起始位置必须小于终止位置")
        sys.exit(1)
    if step_mm <= 0:
        print("错误：步长必须大于 0")
        sys.exit(1)

    print()
    print("--- 扫描参数确认 ---")
    print(f"  串口（滑台）  : {port_slider}")
    print(f"  串口（探测器）: {port_detector}")
    print(f"  起始位置      : {start_mm} mm")
    print(f"  终止位置      : {end_mm} mm")
    print(f"  步长          : {step_mm} mm")
    print(f"  往复次数      : {cycles}")
    print(f"  输出文件      : {output_file}")
    print()

    confirm = input("确认开始扫描？(y/n) [y]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("已取消")
        sys.exit(0)

    return port_slider, port_detector, output_file, start_mm, end_mm, step_mm, cycles


def run_experiment(port_slider, port_detector, output_file,
                   start_mm, end_mm, step_mm, cycles):
    try:
        ser_slider = serial.Serial(port_slider, BAUD_RATE, timeout=5)
        ser_det    = serial.Serial(port_detector, BAUD_RATE, timeout=5)
        time.sleep(2)  # 等待 Arduino 复位完成

        print(f"\n串口已连接，数据将保存至 {output_file}")
        print("按 Ctrl+C 可随时终止\n")

        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Cycle", "Position_mm", "Photon_Count"])

            # 向 Arduino 发送开始指令
            ser_slider.reset_input_buffer()
            ser_slider.write(b"S")

            while True:
                line = ser_slider.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if "SCAN_FINISHED" in line:
                    print("\n扫描任务完成！")
                    break

                if line.startswith("X:"):
                    # 格式: X:10.500,N:1
                    try:
                        parts      = line.split(",")
                        pos_mm     = float(parts[0].split(":")[1])
                        cycle_n    = int(parts[1].split(":")[1])
                    except (IndexError, ValueError):
                        print(f"  [警告] 无法解析位置行: {line}")
                        ser_slider.write(b"G")
                        continue

                    print(f"[第{cycle_n:2d}次] 到达 {pos_mm:7.3f} mm — 读取光子数…", end="", flush=True)

                    photon = read_photon(ser_det)

                    print(f" {photon}")

                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([timestamp, cycle_n, f"{pos_mm:.3f}", photon])
                    f.flush()

                    # 通知 Arduino 可以继续移动
                    ser_slider.write(b"G")

    except serial.SerialException as e:
        print(f"\n串口错误: {e}")
    except KeyboardInterrupt:
        print("\n用户手动停止扫描")
    finally:
        if "ser_slider" in dir():
            ser_slider.close()
        if "ser_det" in dir():
            ser_det.close()
        print("串口已关闭，程序退出")


if __name__ == "__main__":
    params = configure()
    run_experiment(*params)
