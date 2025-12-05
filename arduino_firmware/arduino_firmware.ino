/*
 * Arduino Uno Firmware - LogisticsBot Controller (Camera Only)
 * * Handles:
 * - L298N Motor Control (PWM + Direction)
 * - HC-SR04 Ultrasonic Sensor (Obstacle Detection)
 * - UART Communication with Raspberry Pi
 * * NO IR LINE SENSORS - Camera does all lane detection
 * * Communication: JSON protocol over Serial (115200 baud)
 */

#include <ArduinoJson.h>

// ===== MOTOR PIN DEFINITIONS (UPDATED) =====
// Left Motor
#define ENA 5   // PWM Left Motor Speed
#define IN1 10  // Left Motor Direction 1
#define IN2 11  // Left Motor Direction 2

// Right Motor
#define ENB 6   // PWM Right Motor Speed
#define IN3 12  // Right Motor Direction 1
#define IN4 13  // Right Motor Direction 2

// ===== SENSOR PIN DEFINITIONS (UPDATED) =====
// HC-SR04 Ultrasonic Sensor (Obstacle Detection Only)
#define ULTRASONIC_TRIG  8
#define ULTRASONIC_ECHO  7

// ===== GLOBAL VARIABLES =====
int leftSpeed = 0;
int rightSpeed = 0;
float distance = 0.0;

unsigned long lastSensorRead = 0;
unsigned long sensorReadInterval = 100; // Read sensors every 100ms (slower, only ultrasonic)

// ===== SETUP =====
void setup() {
  // Initialize Serial Communication
  Serial.begin(115200);
  
  // Motor pins - LEFT MOTOR
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  
  // Motor pins - RIGHT MOTOR
  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  
  // Ultrasonic sensor pins
  pinMode(ULTRASONIC_TRIG, OUTPUT);
  pinMode(ULTRASONIC_ECHO, INPUT);
  
  // Stop motors on startup
  stopMotors();
  
  // Send ready signal
  Serial.println("{\"status\":\"ready\",\"device\":\"arduino_uno\",\"mode\":\"camera_only\"}");
}

// ===== MAIN LOOP =====
void loop() {
  // Read sensors periodically
  if (millis() - lastSensorRead >= sensorReadInterval) {
    readSensors();
    sendSensorData();
    lastSensorRead = millis();
  }
  
  // Process incoming commands
  if (Serial.available() > 0) {
    processCommand();
  }
}

// ===== COMMAND PROCESSING =====
void processCommand() {
  String json = Serial.readStringUntil('\n');
  json.trim();
  
  if (json.length() == 0) return;
  
  StaticJsonDocument<200> doc;
  DeserializationError error = deserializeJson(doc, json);
  
  if (error) {
    sendError("JSON parse error");
    return;
  }
  
  const char* cmd = doc["cmd"];
  
  if (strcmp(cmd, "MOVE") == 0) {
    int left = doc["left"] | 0;
    int right = doc["right"] | 0;
    setMotors(left, right);
    sendAck("MOVE");
  }
  else if (strcmp(cmd, "STOP") == 0) {
    stopMotors();
    sendAck("STOP");
  }
  else if (strcmp(cmd, "SET_SPEED") == 0) {
    // int speed = doc["value"] | 0; // Not used directly here, speed is set via MOVE
    sendAck("SET_SPEED");
  }
  else if (strcmp(cmd, "GET_SENSORS") == 0) {
    sendSensorData();
  }
  else if (strcmp(cmd, "PING") == 0) {
    sendAck("PONG");
  }
  else {
    sendError("Unknown command");
  }
}

// ===== MOTOR CONTROL =====
void setMotors(int left, int right) {
  leftSpeed = constrain(left, -255, 255);
  rightSpeed = constrain(right, -255, 255);
  
  // ===== LEFT MOTOR CONTROL =====
  if (leftSpeed > 0) {
    // Forward
    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, leftSpeed);
  }
  else if (leftSpeed < 0) {
    // Backward - Handle negative speed properly
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, HIGH);
    // Use abs() or multiply by -1 to get positive PWM value
    analogWrite(ENA, -leftSpeed);
  }
  else {
    // Stop
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, 0);
  }
  
  // ===== RIGHT MOTOR CONTROL =====
  if (rightSpeed > 0) {
    // Forward
    digitalWrite(IN3, HIGH);
    digitalWrite(IN4, LOW);
    analogWrite(ENB, rightSpeed);
  }
  else if (rightSpeed < 0) {
    // Backward
    digitalWrite(IN3, LOW);
    digitalWrite(IN4, HIGH);
    analogWrite(ENB, -rightSpeed);
  }
  else {
    // Stop
    digitalWrite(IN3, LOW);
    digitalWrite(IN4, LOW);
    analogWrite(ENB, 0);
  }
}

void stopMotors() {
  leftSpeed = 0;
  rightSpeed = 0;
  
  // Stop left motor
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 0);
  
  // Stop right motor
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
  analogWrite(ENB, 0);
}

// ===== SENSOR READING =====
void readSensors() {
  // Only read ultrasonic distance (obstacle detection)
  distance = readUltrasonic();
}

float readUltrasonic() {
  digitalWrite(ULTRASONIC_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIG, LOW);
  
  long duration = pulseIn(ULTRASONIC_ECHO, HIGH, 30000); // Timeout 30ms
  if (duration == 0) {
    return 999.0; // Max distance or no echo
  }
  
  float dist = duration * 0.034 / 2.0; // Convert to cm
  return constrain(dist, 2.0, 400.0);
}

// ===== COMMUNICATION =====
void sendSensorData() {
  StaticJsonDocument<200> doc;
  
  // Only distance sensor (no line sensors)
  doc["distance"] = round(distance * 10) / 10.0; // Round to 1 decimal
  doc["left_speed"] = leftSpeed;
  doc["right_speed"] = rightSpeed;
  doc["uptime"] = millis();
  doc["mode"] = "camera_only";
  
  serializeJson(doc, Serial);
  Serial.println();
}

void sendAck(const char* command) {
  StaticJsonDocument<100> doc;
  doc["status"] = "ok";
  doc["cmd"] = command;
  serializeJson(doc, Serial);
  Serial.println();
}

void sendError(const char* message) {
  StaticJsonDocument<100> doc;
  doc["status"] = "error";
  doc["message"] = message;
  serializeJson(doc, Serial);
  Serial.println();
}