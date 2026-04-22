import serial
import time
import csv

# --- 配置参数 ---
PORT_SLIDER = "COM3"      # 滑台 Arduino 串口号
PORT_DETECTOR = "COM4"    # 探测器串口号
BAUD_RATE = 115200
OUTPUT_FILE = "scan_data.csv"

def run_experiment():
    try:
        # 初始化串口
        ser_slider = serial.Serial(PORT_SLIDER, BAUD_RATE, timeout=1)
        ser_det = serial.Serial(PORT_DETECTOR, 115200, timeout=1) # 探测器波特率通常较低
        
        print(f"成功连接串口。数据将保存至 {OUTPUT_FILE}")
        
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Cycle", "Position_mm", "Photon_Count"])
            
            # 发送开始扫描指令
            ser_slider.write(b'S')
            
            while True:
                # 1. 等待并读取滑台位置信息
                line_slider = ser_slider.readline().decode('utf-8').strip()
                
                if "SCAN_FINISHED" in line_slider:
                    print("扫描任务已完成！")
                    break
                
                if line_slider.startswith("X:"):
                    # 解析格式 X:10.500,N:1
                    parts = line_slider.split(',')
                    pos_mm = parts[0].split(':')[1]
                    cycle_n = parts[1].split(':')[1]
                    
                    print(f"到达位置: {pos_mm} mm (第 {cycle_n} 次往返)")
                    
                    # 2. 探测器逻辑：抛弃第一个数据
                    # 等待第一个数据
                    ser_det.reset_input_buffer() # 清空旧缓存确保实时
                    val1 = ser_det.readline().decode('utf-8').strip()
                    # print(f"  [调试] 抛弃移动干扰数据: {val1}")
                    
                    # 读取第二个数据（准确数据）
                    val2 = ser_det.readline().decode('utf-8').strip()
                    while not val2: # 防止超时读到空字符串
                        val2 = ser_det.readline().decode('utf-8').strip()
                    
                    print(f"  [采集] 准确光子数: {val2}")
                    
                    # 3. 记录数据
                    writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), cycle_n, pos_mm, val2])
                    f.flush() # 实时刷入硬盘防止丢数据
                    
                    # 4. 发送握手信号，允许滑台移动到下一个点
                    ser_slider.write(b'G')
                    
    except serial.SerialException as e:
        print(f"串口错误: {e}")
    except KeyboardInterrupt:
        print("程序被手动停止")
    finally:
        if 'ser_slider' in locals(): ser_slider.close()
        if 'ser_det' in locals(): ser_det.close()

if __name__ == "__main__":
    run_experiment()
