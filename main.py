"""

Main Entry Point - Autonomous Car (Auto Mode Only)

Optimized for Raspberry Pi 4

"""



from flask import Flask, render_template, Response, jsonify, request

from flask_socketio import SocketIO, emit

from datetime import datetime

import logging

import sys

import os

import time

from pathlib import Path



# Add project root to path

sys.path.append(str(Path(__file__).parent))



# Import custom modules

# Lưu ý: Đảm bảo các file driver và controller đã tồn tại

from drivers.motor.arduino_driver import ArduinoDriver

from control.robot_controller import RobotController, AutoModeController

from utils.logger import setup_logger

from utils.config_loader import load_config

from perception.camera_manager import get_web_camera, release_web_camera



# Initialize Flask app

app = Flask(__name__)

app.config["SECRET_KEY"] = "autonomous-car-secret"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')



# Setup logging

LOG_FILE = "data/logs/robot.log"

logger = setup_logger("main", LOG_FILE)



# Global variables

robot_controller = None

auto_controller = None

motor_driver = None

config = None





def initialize_hardware():

    """Initialize robot hardware and controllers"""

    global robot_controller, auto_controller, motor_driver, config



    try:

        # Load configuration

        config = load_config("config/hardware_config.yaml")

        logger.info("Configuration loaded successfully")



        # Determine control mode

        control_mode = config.get("control_mode", "direct")



        if control_mode == "arduino":

            # Use Arduino for motor control

            logger.info("Initializing Arduino driver...")

            arduino_config = config.get("arduino", {})

            motor_driver = ArduinoDriver(

                port=arduino_config.get("port", "/dev/ttyACM0"),

                baudrate=arduino_config.get("baudrate", 115200),

            )

            if not motor_driver.connected:

                logger.error("Failed to connect to Arduino!")

                return False

            # Set sensor callback

            motor_driver.set_sensor_callback(on_arduino_sensor_data)

            logger.info("Arduino Motor Driver initialized")



        else:

            # Use Raspberry Pi GPIO directly (L298N)

            # Import local để tránh lỗi nếu không cài thư viện trên máy tính test

            try:

                from drivers.motor.l298n_driver import L298NDriver

                logger.info("Initializing L298N driver (direct GPIO mode)...")

                motor_driver = L298NDriver(config)

                logger.info("L298N Motor Driver initialized")

            except ImportError:

                logger.error("Could not import L298NDriver. Check dependencies.")

                return False



        # Initialize robot controller

        robot_controller = RobotController(motor_driver, config)

       

        # Initialize auto mode controller

        auto_controller = AutoModeController(robot_controller)

       

        return True



    except Exception as e:

        logger.error(f"Failed to initialize hardware: {e}")

        import traceback

        traceback.print_exc()

        return False





def on_arduino_sensor_data(sensor_data: dict):

    """Callback when Arduino sends sensor data"""

    # Emit to all connected clients immediately for responsiveness

    socketio.emit("arduino_sensors", sensor_data)





# ===== FLASK ROUTES =====



@app.route("/")

def index():

    """Render main dashboard"""

    return render_template("index.html")





@app.route("/video_feed")

def video_feed():

    """Video streaming route"""

    try:

        camera = get_web_camera(config)

        if not camera.is_running():

            if not camera.start():

                return "Camera initialization failed", 500



        return Response(

            camera.generate_frames(),

            mimetype="multipart/x-mixed-replace; boundary=frame",

        )

    except Exception as e:

        logger.error(f"Video feed error: {e}")

        return "Camera error", 500





# ===== AUTO MODE CONTROL =====



@app.route("/set_mode")

def set_mode():

    """Enable/Disable Auto Mode"""

    mode = request.args.get("mode", "manual") # 'auto' or 'manual' (idle)

   

    if not robot_controller:

        return jsonify({"status": "error", "message": "Robot controller not initialized"}), 500



    if mode == 'auto':

        success = robot_controller.set_auto_mode(True)

        if success:

            if auto_controller:

                auto_controller.start()

            log_message("Auto Mode ENABLED")

            return jsonify({"status": "success", "mode": "auto"})

        else:

            return jsonify({"status": "error", "message": "Failed to start Auto Mode"}), 400

           

    else: # manual/idle

        robot_controller.set_auto_mode(False)

        if auto_controller:

            auto_controller.stop()

        log_message("Auto Mode DISABLED")

        return jsonify({"status": "success", "mode": "idle"})





@app.route("/set_speed")

def set_speed():

    """Set base speed for auto mode"""

    if not robot_controller:

        return jsonify({"status": "error", "message": "Robot controller not initialized"}), 500



    try:

        speed = int(request.args.get("value", 150))

        robot_controller.set_speed(speed)

        # Update config in memory for auto controller

        if auto_controller:

            auto_controller.base_speed = speed

        return jsonify({"status": "success", "speed": speed})

    except ValueError:

        return jsonify({"status": "error", "message": "Invalid speed value"}), 400





@app.route("/emergency_stop")

def emergency_stop():

    """Emergency stop"""

    if robot_controller:

        robot_controller.emergency_stop()

    if auto_controller:

        auto_controller.stop()

    log_message("EMERGENCY STOP executed", level="WARNING")

    socketio.emit("sensor_update", get_sensor_data())

    return jsonify({"status": "success", "command": "emergency_stop"})





# ===== VISUAL ODOMETRY API =====



@app.route('/api/odometry/status', methods=['GET'])

def get_odometry_status():

    """Get Visual Odometry Status"""

    try:

        # Check if VO is initialized

        if not robot_controller or not hasattr(robot_controller, 'vo') or robot_controller.vo is None:

            # Return valid JSON even if VO is not ready, just mark enabled=False

            # This prevents 404/500 errors on client side polling

            return jsonify({

                'enabled': False,

                'distance_cm': 0.0,

                'position': {'x_cm': 0, 'y_cm': 0}

            })

       

        status = robot_controller.vo.get_status()

        # Sử dụng .get() để tránh lỗi KeyError nếu status dict thiếu key

        return jsonify({

            'enabled': True,

            'distance_cm': status.get('position_y_cm', 0.0),

            'position': {

                'x_cm': status.get('position_x_cm', 0.0),

                'y_cm': status.get('position_y_cm', 0.0)

            }

        })

    except Exception as e:

        logger.error(f"Odometry API error: {e}")

        return jsonify({'error': str(e), 'enabled': False}), 500



@app.route('/api/odometry/reset', methods=['POST'])

def reset_odometry():

    """Reset Visual Odometry"""

    if robot_controller and hasattr(robot_controller, 'vo') and robot_controller.vo:

        robot_controller.vo.reset()

        return jsonify({'status': 'success'})

    return jsonify({'error': 'VO not available'}), 404





# ===== DATA MANAGEMENT =====



def get_sensor_data() -> dict:

    """Get current sensor/robot state for UI"""

    if not robot_controller:

        return {}



    state = robot_controller.get_state()

   

    # Get physical sensor data

    distance_value = 0.0

   

    # If using Arduino, get real data

    if motor_driver and isinstance(motor_driver, ArduinoDriver):

        arduino_data = motor_driver.get_sensor_data()

        distance_value = arduino_data.get("distance", 0.0)

        state["left_motor_speed"] = arduino_data.get("left_speed", 0)

        state["right_motor_speed"] = arduino_data.get("right_speed", 0)

   

    return {

        "state": state.get("state", "UNKNOWN"),

        "speed": state.get("speed", 0),

        "battery": 100, # Placeholder

        "left_motor_speed": state.get("left_motor_speed", 0),

        "right_motor_speed": state.get("right_motor_speed", 0),

        "distance": distance_value,

        "timestamp": time.time()

    }



def log_message(message: str, level: str = "INFO"):

    """Log message and emit to clients"""

    # Emit to clients (can be added to UI log if needed)

    logger.info(message)





# ===== BACKGROUND TASKS =====



def send_telemetry():

    """Send data to UI periodically"""

    while True:

        socketio.sleep(0.5) # Update UI every 0.5s

        try:

            if robot_controller:

                data = get_sensor_data()

                socketio.emit("sensor_update", data)

        except Exception as e:

            logger.error(f"Telemetry error: {e}")





# ===== MAIN EXECUTION =====



def main():

    # Ensure directories exist

    os.makedirs("data/logs", exist_ok=True)

   

    logger.info("========================================")

    logger.info("   Autonomous Car System (Auto Mode)    ")

    logger.info("========================================")



    if not initialize_hardware():

        logger.error("Hardware initialization failed. Exiting.")

        sys.exit(1)



    logger.info("System Ready. Starting Web Server...")



    # Cleanup on exit

    import atexit

    atexit.register(release_web_camera)

    atexit.register(lambda: robot_controller.cleanup() if robot_controller else None)



    # Start telemetry thread

    socketio.start_background_task(send_telemetry)



    # Run Server

    try:

        socketio.run(

            app,

            host="0.0.0.0",

            port=5000,

            debug=False,

            allow_unsafe_werkzeug=True

        )

    except KeyboardInterrupt:

        logger.info("Shutting down...")

    finally:

        release_web_camera()

        if robot_controller:

            robot_controller.cleanup()



if __name__ == "__main__":

    main()