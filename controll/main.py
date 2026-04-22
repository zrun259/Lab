import serial
import serial.tools.list_ports
import csv
import sys

# --- 默认配置 ---
BAUD_RATE = 115200
OUTPUT_FILE = "scan_data.csv"


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def get_float(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        print("输入无效，使用默认值")
        return default


def get_int(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        print("输入无效，使用默认值")
        return default


def get_str(prompt, default):
    s = input(f"{prompt} [默认 {default}]: ").strip()
    return s if s else default


# ──────────────────────────────────────────────
# 串口扫描与选择
# ──────────────────────────────────────────────

def scan_ports():
    """返回当前系统可用串口列表 [(port, description), ...]"""
    ports = serial.tools.list_ports.comports()
    return sorted(ports, key=lambda p: p.device)


def select_port(role):
    """交互式选择串口，返回端口名称字符串（如 'COM5'）。"""
    while True:
        ports = scan_ports()
        if not ports:
            print("  未检测到任何串口，请检查连接后按回车重新扫描...")
            input()
            continue

        print(f"\n  可用串口列表（选择{role}）：")
        for i, p in enumerate(ports):
            print(f"    [{i}] {p.device:10s}  {p.description}")
        print(f"    [r] 重新扫描")

        choice = input("  请输入编号: ").strip().lower()
        if choice == "r":
            continue
        try:
            idx = int(choice)
            if 0 <= idx < len(ports):
                return ports[idx].device
        except ValueError:
            pass
        print("  输入无效，请重试")


# ──────────────────────────────────────────────
# 探测器读数
# ──────────────────────────────────────────────

def read_photon(ser_det):
    """
    清空缓冲区后，丢弃第一个有效数据行，返回第二个有效整数光子计数。
    探测器输出格式示例（每行一个整数，前后可能有空格）：
         2
         1
         0
    """
    ser_det.reset_input_buffer()

    # 丢弃第一个有效行
    while True:
        raw = ser_det.readline().decode("utf-8", errors="ignore").strip()
        if raw:
            break

    # 读取第二个有效整数
    while True:
        raw = ser_det.readline().decode("utf-8", errors="ignore").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue  # 非数字行跳过


# ──────────────────────────────────────────────
# 参数配置
# ──────────────────────────────────────────────

def configure():
    print("=" * 52)
    print("    光子计数扫描系统  上位机")
    print("=" * 52)

    print("\n--- 步骤 1/2：选择串口 ---")
    port_slider   = select_port("滑台 Arduino")
    port_detector = select_port("探测器")

    output_file = get_str("\n输出文件名", OUTPUT_FILE)
    start_mm    = get_float("起始位置 (mm)", 0.0)
    end_mm      = get_float("终止位置 (mm)", 50.0)
    step_mm     = get_float("步长 (mm)", 1.0)
    cycles      = get_int("往复次数", 1)

    if start_mm >= end_mm:
        print("错误：起始位置必须小于终止位置")
        sys.exit(1)
    if step_mm <= 0:
        print("错误：步长必须大于 0")
        sys.exit(1)

    steps = int((end_mm - start_mm) / step_mm) + 1
    total_points = steps * 2 * cycles  # 每次往复 = 去 + 回

    print()
    print("--- 步骤 2/2：参数确认 ---")
    print(f"  串口（滑台）  : {port_slider}")
    print(f"  串口（探测器）: {port_detector}")
    print(f"  起始位置      : {start_mm} mm")
    print(f"  终止位置      : {end_mm} mm")
    print(f"  步长          : {step_mm} mm")
    print(f"  往复次数      : {cycles}")
    print(f"  预计采集点数  : ~{total_points} 点")
    print(f"  输出文件      : {output_file}")
    print()

    confirm = input("确认开始扫描？(y/n) [y]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("已取消")
        sys.exit(0)

    return port_slider, port_detector, output_file, start_mm, end_mm, step_mm, cycles


# ──────────────────────────────────────────────
# 主扫描流程
# ──────────────────────────────────────────────

def send_params(ser_slider, start_mm, end_mm, step_mm, cycles):
    """
    向 Arduino 发送扫描参数，格式：
      P:<start>,<end>,<step>,<cycles>\n
    等待 Arduino 回复 "PARAM_OK" 确认收到。
    """
    cmd = f"P:{start_mm:.3f},{end_mm:.3f},{step_mm:.3f},{cycles}\n"
    ser_slider.write(cmd.encode("utf-8"))
    print(f"  已发送参数: {cmd.strip()}")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        line = ser_slider.readline().decode("utf-8", errors="ignore").strip()
        if line == "PARAM_OK":
            print("  Arduino 参数确认成功")
            return
    print("  [警告] 未收到 Arduino 参数确认，继续尝试...")


def run_experiment(port_slider, port_detector, output_file,
                   start_mm, end_mm, step_mm, cycles):
    ser_slider = None
    ser_det = None
    try:
        print("\n正在连接串口...")
        ser_slider = serial.Serial(port_slider, BAUD_RATE, timeout=5)
        ser_det    = serial.Serial(port_detector, BAUD_RATE, timeout=5)

        # 等待 Arduino 完成复位（DTR 拉低会触发复位）
        print("等待 Arduino 复位...", end="", flush=True)
        time.sleep(2)
        ser_slider.reset_input_buffer()
        print(" 就绪")

        print(f"数据将保存至 {output_file}")
        print("按 Ctrl+C 可随时终止\n")

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Cycle", "Position_mm", "Photon_Count"])

            # 1. 先发参数
            send_params(ser_slider, start_mm, end_mm, step_mm, cycles)

            # 2. 发开始指令
            ser_slider.write(b"S\n")
            print("已发送开始指令，等待滑台响应...\n")

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
                        parts   = line.split(",")
                        pos_mm  = float(parts[0].split(":")[1])
                        cycle_n = int(parts[1].split(":")[1])
                    except (IndexError, ValueError):
                        print(f"  [警告] 无法解析位置行: {line}")
                        ser_slider.write(b"G\n")
                        continue

                    print(f"[第{cycle_n:2d}次] {pos_mm:7.3f} mm — 读取光子数...",
                          end="", flush=True)

                    photon = read_photon(ser_det)
                    print(f" {photon}")

                    writer.writerow([cycle_n, f"{pos_mm:.3f}", photon])
                    f.flush()

                    # 通知 Arduino 继续移动
                    ser_slider.write(b"G\n")

    except serial.SerialException as e:
        print(f"\n串口错误: {e}")
    except KeyboardInterrupt:
        print("\n用户手动停止扫描")
    finally:
        if ser_slider is not None:
            ser_slider.close()
        if ser_det is not None:
            ser_det.close()
        print("串口已关闭，程序退出")


# ──────────────────────────────────────────────

if __name__ == "__main__":
    params = configure()
    run_experiment(*params)
