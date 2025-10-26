# 🤖 LogisticsBot - Arduino Integration Guide

## 📋 Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Hardware Requirements](#hardware-requirements)
3. [Software Setup](#software-setup)
4. [Arduino Firmware Upload](#arduino-firmware-upload)
5. [Raspberry Pi Setup](#raspberry-pi-setup)
6. [Testing](#testing)
7. [Running the System](#running-the-system)
8. [Troubleshooting](#troubleshooting)

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 5                           │
│  • Flask Web Server (Port 5000)                            │
│  • AI Processing (OpenCV, Object Detection, Color Tracking)│
│  • Video Streaming                                          │
│  • High-level Control Logic                                │
└────────────────────────┬────────────────────────────────────┘
                         │ UART (115200 baud)
                         │ TX/RX + GND
┌────────────────────────┴────────────────────────────────────┐
│                    ARDUINO NANO                             │
│  • Motor Control (L298N PWM)                               │
│  • 8x IR Line Sensors Reading                              │
│  • HC-SR04 Ultrasonic Sensor                               │
│  • Real-time Sensor Processing                             │
└─────────────────────────────────────────────────────────────┘
```

**Benefits:**
- ✅ Offload real-time motor/sensor control to Arduino
- ✅ Raspberry Pi focuses on AI and web interface
- ✅ More stable and responsive control
- ✅ Better separation of concerns

---

## 🛠️ Hardware Requirements

### Components
- **Raspberry Pi 5** (4GB+ RAM recommended)
- **Arduino Nano** (ATmega328P)
- **L298N Motor Driver Module**
- **2x DC Geared Motors** (6V-12V)
- **HC-SR04 Ultrasonic Sensor**
- **8x IR Line Sensors** (TCRT5000)
- **Raspberry Pi Camera V2**
- **7.4V-12V LiPo Battery** (for motors)
- **5V Power Bank** (for Raspberry Pi)
- **Jumper Wires & Breadboard**

### Pin Connections
See [ARDUINO_WIRING.md](ARDUINO_WIRING.md) for detailed wiring diagrams.

---

## 💾 Software Setup

### 1. Arduino IDE Setup

**Install Arduino IDE on your computer:**
```bash
# Ubuntu/Debian
sudo apt install arduino arduino-cli

# Or download from: https://www.arduino.cc/en/software
```

**Install Required Libraries:**
- Open Arduino IDE
- Go to `Tools` → `Manage Libraries`
- Search and install: **ArduinoJson** (v6.21.0 or higher)

### 2. Raspberry Pi Setup

**Install Python Dependencies:**
```bash
# Update system
sudo apt update
sudo apt upgrade -y

# Install Python packages
pip3 install flask flask-socketio pyserial opencv-python pyyaml

# Add user to dialout group (for serial port access)
sudo usermod -a -G dialout $USER

# IMPORTANT: Logout and login again for group changes to take effect
```

**Enable UART on Raspberry Pi:**
```bash
# Edit config
sudo nano /boot/config.txt

# Add these lines:
enable_uart=1
dtoverlay=disable-bt

# Reboot
sudo reboot
```

---

## 📤 Arduino Firmware Upload

### Method 1: Using Arduino IDE

1. Open `arduino_firmware/arduino_firmware.ino` in Arduino IDE
2. Select board: `Tools` → `Board` → `Arduino Nano`
3. Select processor: `Tools` → `Processor` → `ATmega328P (Old Bootloader)`
4. Select port: `Tools` → `Port` → `/dev/ttyUSB0` (or `/dev/ttyACM0`)
5. Click **Upload** button (→)

### Method 2: Using arduino-cli

```bash
# Compile
arduino-cli compile --fqbn arduino:avr:nano arduino_firmware/

# Upload
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano arduino_firmware/

# Verify
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

**Expected Output:**
```json
{"status":"ready","device":"arduino_nano"}
```

---

## 🔧 Raspberry Pi Configuration

### 1. Update `config/hardware_config.yaml`

```yaml
# Set control mode to Arduino
control_mode: 'arduino'

# Configure Arduino serial port
arduino:
  port: '/dev/ttyUSB0'  # Change if needed
  baudrate: 115200
  timeout: 1.0
  reconnect_interval: 5.0
```

### 2. Find Correct Serial Port

```bash
# List all serial devices
ls -l /dev/ttyUSB* /dev/ttyACM*

# Check which one is Arduino
dmesg | grep tty

# Common ports:
# /dev/ttyUSB0 - USB to Serial adapter
# /dev/ttyACM0 - Arduino native USB
```

---

## 🧪 Testing

### Step 1: Test Arduino Connection

```bash
cd /path/to/project
python3 test_arduino.py
```

**This will test:**
- ✅ Serial connection
- ✅ Motor control commands
- ✅ Sensor data reading
- ✅ Speed control
- ✅ Interactive mode

### Step 2: Test Individual Components

**Test Motors:**
```bash
# In test_arduino.py interactive mode:
# Press 'w' - Motors should move forward
# Press 's' - Motors should move backward
# Press 'a'/'d' - Robot should turn
# Press 'x' - Motors should stop
```

**Test Sensors:**
- Place hand in front of ultrasonic sensor → Distance should change
- Move object along line sensors → Line position should change
- Check all 8 line sensors respond

### Step 3: Test Web Interface

```bash
# Start the system
python3 main.py

# Open browser
http://<raspberry-pi-ip>:5000

# Test:
# - Manual control buttons
# - Speed slider
# - Mode switching (Manual/Auto/Follow)
# - Emergency stop
```

---

## 🚀 Running the System

### Start Command

```bash
cd /path/to/project
python3 main.py
```

**Access Web Interface:**
```
http://192.168.1.100:5000
# Replace with your Raspberry Pi's IP
```

### Auto-start on Boot (Optional)

```bash
# Create systemd service
sudo nano /etc/systemd/system/logisticsbot.service
```

**Add content:**
```ini
[Unit]
Description=LogisticsBot Control System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/logisticsbot
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable service:**
```bash
sudo systemctl enable logisticsbot.service
sudo systemctl start logisticsbot.service
sudo systemctl status logisticsbot.service
```

---

## 🔍 Troubleshooting

### ❌ "Arduino not detected"

**Solution:**
```bash
# 1. Check if Arduino is connected
lsusb

# 2. Check serial ports
ls -l /dev/ttyUSB* /dev/ttyACM*

# 3. Check permissions
groups $USER
# Should include 'dialout'

# If not:
sudo usermod -a -G dialout $USER
# Then logout and login

# 4. Test with screen
screen /dev/ttyUSB0 115200
# Should see JSON messages from Arduino
```

### ❌ "Permission denied: '/dev/ttyUSB0'"

**Solution:**
```bash
# Temporary fix
sudo chmod 666 /dev/ttyUSB0

# Permanent fix
sudo usermod -a -G dialout $USER
# Logout and login again
```

### ❌ Motors not moving

**Checklist:**
1. ✅ L298N has power (12V light ON)
2. ✅ ENA/ENB jumpers are ON
3. ✅ Battery voltage > 6V
4. ✅ Motor wires connected to OUT1-4
5. ✅ Arduino pins match firmware code
6. ✅ Test motors directly with battery

### ❌ Sensors not reading

**Checklist:**
1. ✅ All sensors have 5V power
2. ✅ Common GND connected
3. ✅ Check sensor threshold (adjust potentiometer)
4. ✅ Test sensor with multimeter (should toggle 0V/5V)
5. ✅ Verify pin connections match firmware

### ❌ "JSON parse error" in logs

**Cause:** Communication error between Pi and Arduino

**Solution:**
```bash
# 1. Check baud rate matches (115200)
# 2. Check TX/RX are crossed correctly
# 3. Check common GND connected
# 4. Try different USB cable
# 5. Re-upload Arduino firmware
```

### ❌ Web interface not loading

**Solution:**
```bash
# 1. Check Flask is running
ps aux | grep python

# 2. Check port 5000
sudo netstat -tlnp | grep 5000

# 3. Check firewall
sudo ufw status
sudo ufw allow 5000

# 4. Check Pi's IP address
hostname -I

# 5. Try localhost first
http://localhost:5000
```

---

## 📊 System Status Check

```bash
# Check Arduino connection
python3 -c "from drivers.motor.arduino_driver import ArduinoDriver; d=ArduinoDriver(); print('OK' if d.connected else 'FAIL')"

# Check all serial ports
ls -l /dev/tty{USB,ACM}*

# Monitor Arduino output
screen /dev/ttyUSB0 115200

# Check Python packages
pip3 list | grep -E 'flask|serial|opencv|yaml'

# Check system logs
tail -f data/logs/robot.log
```

---

## 📚 Next Steps

1. ✅ **Complete hardware wiring** - Follow [ARDUINO_WIRING.md](ARDUINO_WIRING.md)
2. ✅ **Upload Arduino firmware** - Use Arduino IDE or arduino-cli
3. ✅ **Run tests** - Execute `python3 test_arduino.py`
4. ✅ **Calibrate sensors** - Adjust IR sensor thresholds
5. ✅ **Test web interface** - Open browser and test controls
6. ✅ **Implement AI features** - Add color tracking, object detection
7. ✅ **Tune PID** - Optimize line following and speed control

---

## 🤝 Support

**Issues or questions?**
- Check the logs: `data/logs/robot.log`
- Review wiring diagram: `ARDUINO_WIRING.md`
- Test Arduino independently: `test_arduino.py`

**Common Files:**
- `main.py` - Main application entry point
- `drivers/motor/arduino_driver.py` - Arduino UART driver
- `arduino_firmware/arduino_firmware.ino` - Arduino firmware
- `config/hardware_config.yaml` - Hardware configuration
- `test_arduino.py` - Testing script

---

## 📝 License

This project is part of LogisticsBot autonomous robot platform.

Happy Building! 🤖🚀
