/**
 * 硬件自检程序（与主系统无关，只验证传感器和接线）
 *
 * 接线：
 *   GPIO23 → 传感器 A OUT（正式固件中对应 ir_front）
 *   GPIO27 → 传感器 B OUT（正式固件中对应 ir_back）
 *   3.3V   → 两个传感器 VCC
 *   GND    → 两个传感器 GND
 *
 * 判断方法（红外避障模块）：
 *   检测到障碍物 → 输出 LOW（读数 0）
 *   无障碍       → 输出 HIGH（读数 1）
 *   与正式固件 IR_ACTIVE_HIGH=false 一致。
 */
#include <Arduino.h>

const uint8_t PIN_A = 23;  // ir_front
const uint8_t PIN_B = 27;  // ir_back

void setup() {
    Serial.begin(115200);
    delay(200);
    pinMode(PIN_A, INPUT_PULLUP);
    pinMode(PIN_B, INPUT_PULLUP);
    Serial.println();
    Serial.println("=== 硬件自检启动 ===");
    Serial.println("用手/障碍物分别遮挡两个传感器，观察读数变化");
    Serial.println("红外避障模块: 检测到物体=0(有), 无障碍=1(无)");
}

void loop() {
    int rawA = digitalRead(PIN_A);
    int rawB = digitalRead(PIN_B);
    bool front = (rawA == LOW);  // 与正式固件 IR_ACTIVE_HIGH=false 一致
    bool back  = (rawB == LOW);
    Serial.printf("raw A=%d B=%d | 检测到物体: front=%d back=%d\n",
                  rawA, rawB, front, back);
    delay(500);
}
