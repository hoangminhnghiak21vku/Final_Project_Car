"""
Main Entry Point - LogisticsBot Control System
Integrates Flask Web Dashboard with Robot Hardware Control
"""

from flask import Flask, render_template, Response, jsonify, request
from flask_socketio import SocketIO, emit
from datetime import datetime
import cv2
import yaml
import logging
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

# Import custom modules
from drivers.motor.l298n_driver import L298NDriver, DifferentialDrive
from control.robot_controller import RobotController, AutoModeController
from utils.logger import setup_logger
from utils.config_loader import load_config

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Setup logging
logger = setup_logger('main', 'data/logs/robot.log')

# Global variables
robot_controller = None
auto_controller = None
follow_controller = None  # NEW: Follow mode controller
config = None
LOG_FILE = 'data/logs/robot.log'

# Follow mode settings
follow_settings = {
    'target_color': 'red',
    'follow_distance': 50,  # cm
    'tracking': False,
    'target_x': 0,
    'target_y': 0,
    'target_w': 0,
    'target_h': 0,
    'confidence': 0,
    'target_distance': 0
}


def initialize_hardware():
    """Initialize robot hardware"""
    global robot_controller, auto_controller, follow_controller, config
    
    try:
        # Load configuration
        config = load_config('config/hardware_config.yaml')
        logger.info("Configuration loaded successfully")
        
        # Initialize motor driver
        motor_driver = L298NDriver(config)
        logger.info("L298N Motor Driver initialized")
        
        # Initialize robot controller
        robot_controller = RobotController(motor_driver, config)
        logger.info("Robot Controller initialized")
        
        # Initialize auto mode controller
        auto_controller = AutoModeController(robot_controller)
        logger.info("Auto Mode Controller initialized")
        
        # TODO: Initialize follow controller when ready
        # follow_controller = FollowModeController(robot_controller)
        # logger.info("Follow Mode Controller initialized")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize hardware: {e}")
        return False


# ===== FLASK ROUTES =====

@app.route('/')
def index():
    """Render main dashboard"""
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Video streaming route (placeholder)"""
    def generate():
        # Placeholder for camera feed
        # Replace with actual camera if available
        try:
            camera = cv2.VideoCapture(0)
            
            while True:
                success, frame = camera.read()
                if not success:
                    break
                
                frame = cv2.resize(frame, (320, 240))
                
                # TODO: Add object tracking overlay when in follow mode
                # if robot_controller.current_mode == 'follow' and follow_settings['tracking']:
                #     frame = draw_target_box(frame, follow_settings)
                
                ret, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        except:
            # If no camera, send blank frame
            pass
    
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# ===== MODE CONTROL =====

@app.route('/set_mode')
def set_mode():
    """Set control mode (manual/auto/follow)"""
    mode = request.args.get('mode', 'manual')
    
    if mode not in ['manual', 'auto', 'follow']:
        return jsonify({'status': 'error', 'message': 'Invalid mode'}), 400
    
    if robot_controller.set_mode(mode):
        log_message(f"Mode changed to: {mode.upper()}")
        
        # Start/stop controllers based on mode
        if mode == 'auto':
            auto_controller.start()
            # Stop follow controller if running
            # if follow_controller:
            #     follow_controller.stop()
        elif mode == 'follow':
            # Start follow controller
            # if follow_controller:
            #     follow_controller.start()
            # Stop auto controller if running
            if auto_controller:
                auto_controller.stop()
        else:  # manual
            # Stop both controllers
            if auto_controller:
                auto_controller.stop()
            # if follow_controller:
            #     follow_controller.stop()
        
        # Emit state update
        socketio.emit('mode_update', {'mode': mode})
        socketio.emit('sensor_update', get_sensor_data())
        
        return jsonify({'status': 'success', 'mode': mode})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to set mode'}), 400


# ===== FOLLOW MODE SETTINGS (NEW) =====

@app.route('/set_follow_color')
def set_follow_color():
    """Set target color for follow mode"""
    color = request.args.get('color', 'red')
    
    valid_colors = ['red', 'green', 'blue', 'yellow', 'orange']
    if color not in valid_colors:
        return jsonify({'status': 'error', 'message': 'Invalid color'}), 400
    
    follow_settings['target_color'] = color
    log_message(f"Target color set to: {color.upper()}")
    
    # TODO: Update follow controller with new color
    # if follow_controller:
    #     follow_controller.set_target_color(color)
    
    return jsonify({'status': 'success', 'color': color})


@app.route('/set_follow_distance')
def set_follow_distance():
    """Set follow distance (safe distance from target)"""
    try:
        distance = int(request.args.get('distance', 50))
        distance = max(20, min(100, distance))  # Clamp between 20-100cm
        
        follow_settings['follow_distance'] = distance
        log_message(f"Follow distance set to: {distance} cm")
        
        # TODO: Update follow controller with new distance
        # if follow_controller:
        #     follow_controller.set_follow_distance(distance)
        
        return jsonify({'status': 'success', 'distance': distance})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid distance value'}), 400


# ===== ROBOT CONTROL COMMANDS =====

@app.route('/forward')
def forward():
    """Move forward"""
    if robot_controller.forward():
        log_message("Command: FORWARD")
        socketio.emit('sensor_update', get_sensor_data())
        return jsonify({'status': 'success', 'command': 'forward'})
    else:
        return jsonify({'status': 'error', 'message': 'Cannot execute in current mode'}), 403


@app.route('/backward')
def backward():
    """Move backward"""
    if robot_controller.backward():
        log_message("Command: BACKWARD")
        socketio.emit('sensor_update', get_sensor_data())
        return jsonify({'status': 'success', 'command': 'backward'})
    else:
        return jsonify({'status': 'error', 'message': 'Cannot execute in current mode'}), 403


@app.route('/left')
def left():
    """Turn left"""
    if robot_controller.left():
        log_message("Command: LEFT")
        socketio.emit('sensor_update', get_sensor_data())
        return jsonify({'status': 'success', 'command': 'left'})
    else:
        return jsonify({'status': 'error', 'message': 'Cannot execute in current mode'}), 403


@app.route('/right')
def right():
    """Turn right"""
    if robot_controller.right():
        log_message("Command: RIGHT")
        socketio.emit('sensor_update', get_sensor_data())
        return jsonify({'status': 'success', 'command': 'right'})
    else:
        return jsonify({'status': 'error', 'message': 'Cannot execute in current mode'}), 403


@app.route('/stop')
def stop():
    """Stop motors"""
    robot_controller.stop()
    log_message("Command: STOP")
    socketio.emit('sensor_update', get_sensor_data())
    return jsonify({'status': 'success', 'command': 'stop'})


@app.route('/emergency_stop')
def emergency_stop():
    """Emergency stop"""
    robot_controller.emergency_stop()
    log_message("EMERGENCY STOP executed", level="WARNING")
    socketio.emit('sensor_update', get_sensor_data())
    return jsonify({'status': 'success', 'command': 'emergency_stop'})


# ===== SPEED CONTROL =====

@app.route('/set_speed')
def set_speed():
    """Set motor speed"""
    try:
        speed = int(request.args.get('value', 180))
        robot_controller.set_speed(speed)
        log_message(f"Speed set to: {speed}")
        socketio.emit('sensor_update', get_sensor_data())
        return jsonify({'status': 'success', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400


# ===== LOG MANAGEMENT =====

def log_message(message: str, level: str = "INFO"):
    """Log message and emit to clients"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    time_str = datetime.now().strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] {level}: {message}\n"
    
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"Error writing to log file: {e}")
    
    # Emit to clients
    socketio.emit('log_entry', {
        'time': time_str,
        'level': level,
        'message': message
    })


@app.route('/read_log')
def read_log():
    """Read log file"""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            return content, 200
        else:
            return "Log file not found", 404
    except Exception as e:
        return f"Error reading log: {str(e)}", 500


@app.route('/clear_log')
def clear_log():
    """Clear log file"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"[{timestamp}] INFO: Log file cleared by user\n")
        return jsonify({'status': 'success', 'message': 'Log cleared'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ===== SENSOR DATA =====

def get_sensor_data() -> dict:
    """Get current sensor/robot state"""
    state = robot_controller.get_state()
    
    # Simulate battery (replace with actual reading)
    import random
    battery = random.randint(75, 85)
    
    return {
        'state': state['state'],
        'speed': state['speed'],
        'battery': battery,
        'left_motor_speed': state['left_motor_speed'],
        'right_motor_speed': state['right_motor_speed'],
        'line_sensors': [False, False, True, True, True, True, False, False],
        'line_position': 0,
        'distance': random.uniform(20, 80)
    }


def get_target_data() -> dict:
    """Get current target tracking data for follow mode"""
    # TODO: Get actual data from follow controller
    # if follow_controller:
    #     return follow_controller.get_target_data()
    
    # Return current follow_settings as placeholder
    return {
        'tracking': follow_settings['tracking'],
        'target_color': follow_settings['target_color'],
        'target_x': follow_settings['target_x'],
        'target_y': follow_settings['target_y'],
        'target_w': follow_settings['target_w'],
        'target_h': follow_settings['target_h'],
        'confidence': follow_settings['confidence'],
        'target_distance': follow_settings['target_distance']
    }


# ===== SOCKETIO EVENTS =====

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('connection_response', {'data': 'Connected'})
    
    # Send current mode and state
    emit('mode_update', {'mode': robot_controller.current_mode})
    emit('sensor_update', get_sensor_data())
    
    # Send target data if in follow mode
    if robot_controller.current_mode == 'follow':
        emit('target_update', get_target_data())


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


# ===== BACKGROUND TASKS =====

def send_sensor_data():
    """Send sensor data periodically to all clients"""
    import time
    while True:
        socketio.sleep(2)
        
        try:
            sensor_data = get_sensor_data()
            socketio.emit('sensor_update', sensor_data)
            
            # Send target data if in follow mode
            if robot_controller and robot_controller.current_mode == 'follow':
                target_data = get_target_data()
                socketio.emit('target_update', target_data)
                
        except Exception as e:
            logger.error(f"Error sending sensor data: {e}")


# ===== MAIN =====

def main():
    """Main entry point"""
    global LOG_FILE
    
    # Create directories if not exist
    os.makedirs('data/logs', exist_ok=True)
    os.makedirs('config', exist_ok=True)
    
    # Initialize log file
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] INFO: LogisticsBot Control System Started\n")
    
    logger.info("=" * 60)
    logger.info("LogisticsBot Control System Starting...")
    logger.info("=" * 60)
    
    # Initialize hardware
    if not initialize_hardware():
        logger.error("Failed to initialize hardware. Exiting.")
        sys.exit(1)
    
    logger.info("Hardware initialized successfully")
    
    # Start background task
    socketio.start_background_task(send_sensor_data)
    
    # Run Flask-SocketIO server
    logger.info("Starting web server on http://0.0.0.0:5000")
    logger.info("Access dashboard at: http://<raspberry-pi-ip>:5000")
    
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    finally:
        # Cleanup
        if robot_controller:
            robot_controller.cleanup()
        logger.info("Cleanup completed. Goodbye!")


if __name__ == '__main__':
    main()