#include <Arduino.h>
#include <AccelStepper.h>

// --- 硬件引脚 (根据你的老师例程修改为 3, 4) ---
const int pulXPin = 3;
const int dirXPin = 4;

// --- 物理参数 ---
const float stepsPerMm = 1600.0; // 根据你的驱动器 Pulse/rev 调整

// --- 扫描任务变量 ---
float startPosMm = 0.0;    // 扫描起点
float endPosMm = 50.0;     // 扫描终点
float stepSizeMm = 1.0;    // 步长
int totalCycles = 5;       // 往复次数
int currentCycle = 1;      // 当前第几次往复
bool isScanning = false;   // 扫描状态控制
bool movingForward = true; // 运动方向：true往终点，false往起点

AccelStepper slider(1, pulXPin, dirXPin);

void setup() {
    Serial.begin(115200); // 建议使用高波特率，减少串口阻塞
    
    slider.setMaxSpeed(2000.0);
    slider.setAcceleration(1000.0);
    
    // 初始位置设为 0 (假设开机前已手动归位)
    slider.setCurrentPosition(0);
}

// 执行一步并上报坐标
void moveAndReport(float targetMm) {
    long targetSteps = (long)(targetMm * stepsPerMm);
    slider.moveTo(targetSteps);
    while (slider.distanceToGo() != 0) { slider.run(); }

    // 1. 到达位置，发送坐标
    Serial.print("X:");
    Serial.print(targetMm, 3);
    Serial.print(",N:");
    Serial.println(currentCycle);

    // 2. 等待上位机发送指令后再继续 (阻塞)
    // 只有收到 'G' (Go) 字符才会退出此循环
    while (true) {
        if (Serial.available() > 0) {
            char c = Serial.read();
            if (c == 'G' || c == 'g') break; 
        }
    }
}

void startScan() {
    isScanning = true;
    currentCycle = 1;
    
    while (currentCycle <= totalCycles) {
        if (movingForward) {
            // 从起点向终点步进
            for (float p = startPosMm; p <= endPosMm; p += stepSizeMm) {
                moveAndReport(p);
                // 在此处上位机接收到串口信号后，会去读取光子计数器
            }
            movingForward = false; // 调转方向
        } else {
            // 从终点向起点步进
            for (float p = endPosMm; p >= startPosMm; p -= stepSizeMm) {
                moveAndReport(p);
            }
            movingForward = true; // 调转方向
            currentCycle++;       // 完成一次完整往复
        }
    }
    isScanning = false;
    Serial.println("SCAN_FINISHED");
}

void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        
        // 解析上位机指令
        // S: 开始扫描
        // Z: 强制归零
        if (cmd == 'S' || cmd == 's') {
            startScan();
        } else if (cmd == 'Z' || cmd == 'z') {
            slider.setCurrentPosition(0);
            Serial.println("ZERO_OK");
        }
        // 如果需要在线设置参数，可以扩展 Serial.parseFloat 等逻辑
    }
}