#include <Arduino.h>
#include <AccelStepper.h>

// --- 硬件参数配置 ---
const int pulsePin = 9;   // 脉冲引脚 (PUL)
const int dirPin = 8;     // 方向引脚 (DIR)
const int enablePin = 7;  // 使能引脚 (ENA)

// --- 滑台物理参数 (根据你的驱动器细分调整) ---
// 假设：16细分 (一圈3200步)，导程 1mm (一圈走1mm)
const float stepsPerMm = 3200.0; 

// 初始化步进电机对象 (1 表示使用专用驱动器)
AccelStepper slider(1, pulsePin, dirPin);

void setup() {
    Serial.begin(115200);
    
    // 设置使能引脚（通常低电平有效）
    pinMode(enablePin, OUTPUT);
    digitalWrite(enablePin, LOW);

    // 设置最大速度和加速度
    slider.setMaxSpeed(2000.0);      // 步/秒
    slider.setAcceleration(1000.0);  // 步/秒^2

    Serial.println("--- 普菲德 T6X1 滑台串口控制系统 ---");
    Serial.println("指令说明:");
    Serial.println("1. 直接输入数字 (如 10.5): 移动到该绝对坐标(mm)");
    Serial.println("2. 输入 'Z': 将当前位置设为零点(坐标原点)");
    Serial.println("3. 输入 'H': 停止电机并紧急刹车");
    Serial.print("系统就绪。当前位置: 0 mm");
}

void loop() {
    // 1. 实时驱动电机（必须放在 loop 中最前面）
    slider.run();

    // 2. 处理串口指令
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim(); // 去除换行符和空格

        if (input.equalsIgnoreCase("Z")) {
            // 将当前物理位置强制定义为坐标 0
            slider.setCurrentPosition(0);
            Serial.println("\n[系统] 已归零。当前位置设为 0mm");
        } 
        else if (input.equalsIgnoreCase("H")) {
            // 紧急停止
            slider.stop();
            Serial.println("\n[警告] 紧急停止！");
        }
        else if (input.length() > 0) {
            // 将输入的字符串转为浮点数（坐标）
            float targetMm = input.toFloat();
            long targetSteps = (long)(targetMm * stepsPerMm);

            Serial.print("\n[移动] 目标坐标: ");
            Serial.print(targetMm);
            Serial.print(" mm (步数: ");
            Serial.print(targetSteps);
            Serial.println(")");

            // 移动到绝对坐标
            slider.moveTo(targetSteps);
        }
    }

    // 3. 定期反馈位置（可选，每隔 500ms 打印一次）
    static unsigned long lastUpdate = 0;
    if (millis() - lastUpdate > 500 && slider.isRunning()) {
        Serial.print("当前位置: ");
        Serial.print(slider.currentPosition() / stepsPerMm);
        Serial.println(" mm");
        lastUpdate = millis();
    }
}