#include <Arduino.h>
#include <AccelStepper.h>

// --- 硬件引脚 ---
const int pulXPin = 3;
const int dirXPin = 4;

// --- 物理参数 ---
const float stepsPerMm = 1600.0;

// --- 扫描参数（由上位机通过串口写入）---
float startPosMm  = 0.0;
float endPosMm    = 50.0;
float stepSizeMm  = 1.0;
int   totalCycles = 1;

// --- 运行状态 ---
int  currentCycle  = 1;
bool movingForward = true;

AccelStepper slider(AccelStepper::DRIVER, pulXPin, dirXPin);

// ──────────────────────────────────────────────
// 移动到目标并等待上位机 'G' 握手
// ──────────────────────────────────────────────
void moveAndReport(float targetMm) {
    long targetSteps = (long)(targetMm * stepsPerMm);
    slider.moveTo(targetSteps);
    while (slider.distanceToGo() != 0) {
        slider.run();
    }

    Serial.print("X:");
    Serial.print(targetMm, 3);
    Serial.print(",N:");
    Serial.println(currentCycle);

    // 阻塞等待上位机发送 'G' / 'g' 才继续
    while (true) {
        if (Serial.available() > 0) {
            char c = Serial.read();
            if (c == 'G' || c == 'g') break;
        }
    }
}

// ──────────────────────────────────────────────
// 解析参数命令  P:<start>,<end>,<step>,<cycles>
// ──────────────────────────────────────────────
bool parseParams(const String& line) {
    // 期望格式: P:0.000,50.000,1.000,3
    if (!line.startsWith("P:")) return false;

    String body = line.substring(2); // 去掉 "P:"
    int i0 = body.indexOf(',');
    int i1 = body.indexOf(',', i0 + 1);
    int i2 = body.indexOf(',', i1 + 1);

    if (i0 < 0 || i1 < 0 || i2 < 0) return false;

    startPosMm  = body.substring(0, i0).toFloat();
    endPosMm    = body.substring(i0 + 1, i1).toFloat();
    stepSizeMm  = body.substring(i1 + 1, i2).toFloat();
    totalCycles = body.substring(i2 + 1).toInt();

    return (stepSizeMm > 0 && endPosMm > startPosMm && totalCycles > 0);
}

// ──────────────────────────────────────────────
// 执行扫描
// ──────────────────────────────────────────────
void startScan() {
    currentCycle  = 1;
    movingForward = true;

    while (currentCycle <= totalCycles) {
        if (movingForward) {
            for (float p = startPosMm; p <= endPosMm + 1e-6f; p += stepSizeMm) {
                moveAndReport(p);
            }
            movingForward = false;
        } else {
            for (float p = endPosMm; p >= startPosMm - 1e-6f; p -= stepSizeMm) {
                moveAndReport(p);
            }
            movingForward = true;
            currentCycle++;
        }
    }

    Serial.println("SCAN_FINISHED");
}

// ──────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    slider.setMaxSpeed(4000.0);
    slider.setAcceleration(3000.0);
    slider.setCurrentPosition(0);
}

void loop() {
    if (Serial.available() > 0) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();

        if (cmd.startsWith("P:")) {
            if (parseParams(cmd)) {
                Serial.println("PARAM_OK");
            } else {
                Serial.println("PARAM_ERR");
            }
        } else if (cmd == "S" || cmd == "s") {
            startScan();
        } else if (cmd == "Z" || cmd == "z") {
            slider.setCurrentPosition(0);
            Serial.println("ZERO_OK");
        }
    }
}
