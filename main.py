
from flask import Flask, render_template, Response, jsonify
import logging
import sys
import os
import cv2  # <--- MỚI: Cần để xử lý ảnh
import time # <--- MỚI: Cần để delay
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from drivers.motor.arduino_driver import ArduinoDriver
from control.robot_controller import RobotController
from utils.logger import setup_logger
from utils.config_loader import load_config
from perception.camera_manager import get_web_camera, release_web_camera

app = Flask(__name__)
logger = setup_logger("main", "data/logs/robot.log")

# Globals
robot_controller = None
motor_driver = None
config = None

def initialize_hardware():
    global robot_controller, motor_driver, config
    try:
        config = load_config("config/hardware_config.yaml")
        
        # Chỉ hỗ trợ Arduino mode cho bản Lite này
        arduino_config = config.get("arduino", {})
        motor_driver = ArduinoDriver(
            port=arduino_config.get("port", "/dev/ttyUSB0"),
            baudrate=arduino_config.get("baudrate", 115200),
        )

        if not motor_driver.connected:
            logger.error("Failed to connect to Arduino!")
            return False

        # Khởi tạo Controller (Chỉ Auto Mode)
        robot_controller = RobotController(motor_driver, config)
        return True

    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False

# --- HELPER: SMART STREAM GENERATOR ---
def generate_smart_frames():
    """Generator: Ưu tiên gửi ảnh Debug (có vẽ line/box) nếu có"""
    while True:
        frame = None
        
        # 1. Nếu Robot đang chạy Auto -> Lấy ảnh Debug từ Controller (đã vẽ AI)
        # Đây là ảnh đã được vẽ vạch kẻ đường và khung nhận diện biển báo
        if robot_controller and robot_controller.is_running and robot_controller.latest_debug_frame is not None:
            frame = robot_controller.latest_debug_frame
        
        # 2. Nếu không (hoặc chưa có ảnh debug) -> Lấy ảnh thô từ Camera
        else:
            if config:
                try:
                    camera = get_web_camera(config)
                    if not camera.is_running(): 
                        camera.start()
                    frame = camera.capture_frame()
                except Exception:
                    pass

        if frame is not None:
            # Nén sang JPEG để gửi về trình duyệt
            try:
                # Lưu ý: Frame ở đây phải là BGR (do chúng ta đã fix màu ở các bước trước)
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception:
                pass
        
        time.sleep(0.05) # Giới hạn FPS stream (~20fps) để đỡ lag và tiết kiệm CPU

# --- ROUTES ---

@app.route("/")
def index():
    """Giao diện đơn giản chỉ có Video"""
    return render_template("index.html")

@app.route("/video_feed")
def video_feed():
    """Stream Video từ Camera (Smart Mode)"""
    return Response(generate_smart_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/toggle_auto")
def toggle_auto():
    """Bật/Tắt chế độ tự lái"""
    if robot_controller.is_running:
        robot_controller.stop()
        state = "STOPPED"
    else:
        robot_controller.start()
        state = "RUNNING"
    return jsonify({"status": "success", "state": state})

if __name__ == "__main__":
    if initialize_hardware():
        try:
            app.run(host="0.0.0.0", port=5000, debug=False)
        finally:
            release_web_camera()
            if robot_controller: robot_controller.cleanup()
    else:
        print("Hardware init failed.")