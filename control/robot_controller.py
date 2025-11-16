"""
Robot Controller - Interface between Web Dashboard and Motor Driver
Handles commands from Flask app and controls motors
Updated with PID-based Auto Mode and Picamera2 support
"""

import threading
import time
import logging
import numpy as np
from typing import Optional
from datetime import datetime

# Import PID and lane detection
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from control.pid_controller import PIDController
from perception.lane_detector import detect_line
from perception.camera_manager import CameraManager  # NEW: Picamera2 support

logger = logging.getLogger(__name__)


class RobotController:
    """
    Main robot controller
    Manages motor control, safety, and state
    """
    
    def __init__(self, motor_driver, config: dict):
        """
        Initialize robot controller
        
        Args:
            motor_driver: Arduino driver instance
            config: Robot configuration
        """
        self.driver = motor_driver
        self.config = config
        
        # Current state
        self.current_mode = 'manual'  # 'manual', 'auto', or 'follow'
        self.current_state = 'IDLE'
        self.current_speed = 180  # Default speed (0-255)
        
        # Safety
        self.emergency_stopped = False
        self.last_command_time = time.time()
        self.timeout = config.get('safety', {}).get('timeout', 5.0)
        
        # Watchdog thread
        self.running = True
        self.watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self.watchdog_thread.start()
        
        logger.info("Robot Controller initialized")
    
    def set_mode(self, mode: str):
        """Set control mode (manual/auto/follow)"""
        if mode in ['manual', 'auto', 'follow']:
            self.current_mode = mode
            
            if mode == 'auto':
                self.current_state = 'AUTO MODE'
            elif mode == 'follow':
                self.current_state = 'FOLLOW MODE'
            else:
                self.current_state = 'IDLE'
            
            logger.info(f"Mode changed to: {mode}")
            return True
        return False
    
    def set_speed(self, speed: int):
        """Set default speed (0-255)"""
        self.current_speed = max(0, min(255, speed))
        logger.info(f"Speed set to: {self.current_speed}")
    
    def forward(self):
        """Move forward"""
        if not self._check_manual_mode():
            return False
        
        self.driver.forward(self.current_speed)
        self.current_state = 'MOVING FORWARD'
        self._update_command_time()
        return True
    
    def backward(self):
        """Move backward"""
        if not self._check_manual_mode():
            return False
        
        self.driver.backward(self.current_speed)
        self.current_state = 'MOVING BACKWARD'
        self._update_command_time()
        return True
    
    def left(self):
        """Turn left"""
        if not self._check_manual_mode():
            return False
        
        turn_speed = int(self.current_speed * 0.8)
        self.driver.turn_left(turn_speed)
        self.current_state = 'TURNING LEFT'
        self._update_command_time()
        return True
    
    def right(self):
        """Turn right"""
        if not self._check_manual_mode():
            return False
        
        turn_speed = int(self.current_speed * 0.8)
        self.driver.turn_right(turn_speed)
        self.current_state = 'TURNING RIGHT'
        self._update_command_time()
        return True
    
    def stop(self):
        """Stop motors"""
        self.driver.stop()
        
        if self.current_mode == 'manual':
            self.current_state = 'STOPPED'
        elif self.current_mode == 'auto':
            self.current_state = 'AUTO MODE'
        elif self.current_mode == 'follow':
            self.current_state = 'FOLLOW MODE'
        
        self._update_command_time()
        return True
    
    def emergency_stop(self):
        """Emergency stop - works in any mode"""
        self.driver.stop()
        self.emergency_stopped = True
        self.current_state = 'EMERGENCY STOP'
        logger.warning("EMERGENCY STOP ACTIVATED")
        return True
    
    def reset_emergency(self):
        """Reset emergency stop"""
        self.emergency_stopped = False
        self.current_state = 'IDLE'
        logger.info("Emergency stop reset")
    
    def get_state(self) -> dict:
        """Get current robot state"""
        left_speed, right_speed = self.driver.get_speeds()
        
        return {
            'mode': self.current_mode,
            'state': self.current_state,
            'speed': self.current_speed,
            'emergency_stopped': self.emergency_stopped,
            'left_motor_speed': left_speed,
            'right_motor_speed': right_speed,
            'last_command_age': time.time() - self.last_command_time
        }
    
    def _check_manual_mode(self) -> bool:
        """Check if manual mode is active"""
        if self.emergency_stopped:
            logger.warning("Cannot execute command: Emergency stop active")
            return False
        
        if self.current_mode != 'manual':
            logger.warning(f"Cannot execute command: Not in manual mode (current: {self.current_mode})")
            return False
        
        return True
    
    def _update_command_time(self):
        """Update last command timestamp"""
        self.last_command_time = time.time()
    
    def _watchdog(self):
        """
        Watchdog thread
        Auto-stop motors if no command received for timeout period
        """
        while self.running:
            time.sleep(0.5)
            
            # Check command timeout (only in manual mode)
            age = time.time() - self.last_command_time
            if age > self.timeout and self.current_mode == 'manual':
                # Check if motors are running
                left, right = self.driver.get_speeds()
                if left != 0 or right != 0:
                    logger.warning(f"Command timeout ({age:.1f}s) - Auto stopping motors")
                    self.stop()
            
            # Update state if idle
            if self.current_state in ['MOVING FORWARD', 'MOVING BACKWARD', 'TURNING LEFT', 'TURNING RIGHT']:
                left, right = self.driver.get_speeds()
                if left == 0 and right == 0:
                    self.current_state = 'IDLE'
    
    def cleanup(self):
        """Cleanup resources"""
        self.running = False
        self.driver.cleanup()
        logger.info("Robot Controller cleaned up")


class AutoModeController:
    """
    Autonomous mode controller with PID-based lane following
    Uses Picamera2 for lane detection and PID for smooth steering
    """
    
    def __init__(self, robot_controller: RobotController):
        """
        Initialize auto mode controller
        
        Args:
            robot_controller: Main robot controller instance
        """
        self.robot = robot_controller
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        # Camera - UPDATED to use CameraManager with Picamera2
        self.camera: Optional[CameraManager] = None
        
        # PID Controller for steering
        pid_config = robot_controller.config.get('lane_following', {}).get('pid', {})
        self.pid = PIDController(
            kp=pid_config.get('kp', 0.8),
            ki=pid_config.get('ki', 0.0),
            kd=pid_config.get('kd', 0.3),
            output_min=pid_config.get('min_output', -150),
            output_max=pid_config.get('max_output', 150),
            derivative_smoothing=pid_config.get('derivative_smoothing', 0.7)
        )
        
        # Lane following settings
        lane_config = robot_controller.config.get('lane_following', {})
        self.base_speed = lane_config.get('base_speed', 120)
        self.max_speed = lane_config.get('max_speed', 180)
        self.min_speed = lane_config.get('min_speed', 60)
        
        # Lane detection config
        self.detection_config = robot_controller.config.get('ai', {}).get('lane_detection', {})
        
        # State
        self.lane_lost_count = 0
        self.lane_lost_threshold = 10  # Frames before stopping
        
        # Frame for debugging (can be accessed by web interface)
        self.latest_debug_frame = None
        self.latest_error = 0
        self.latest_correction = 0
        
        logger.info("Auto Mode Controller initialized with PID and Picamera2")
    
    def start(self):
        """Start autonomous mode"""
        if not self.running:
            # Initialize camera
            if not self._init_camera():
                logger.error("Failed to initialize camera")
                return False
            
            # Reset PID
            self.pid.reset()
            self.lane_lost_count = 0
            
            self.running = True
            self.thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.thread.start()
            logger.info("Autonomous mode started (PID lane following with Picamera2)")
            return True
        return False
    
    def stop(self):
        """Stop autonomous mode"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.robot.driver.stop()
        
        # Release camera - UPDATED for CameraManager
        if self.camera:
            self.camera.stop()
            self.camera = None
        
        logger.info("Autonomous mode stopped")
    
    def _init_camera(self) -> bool:
        """
        Initialize camera using Picamera2
        UPDATED: Now uses CameraManager instead of cv2.VideoCapture
        """
        try:
            # Create camera manager instance
            self.camera = CameraManager(self.robot.config)
            
            # Start camera
            if not self.camera.start():
                logger.error("Failed to start camera")
                return False
            
            logger.info(f"Camera initialized: {self.camera.get_resolution()}")
            return True
            
        except Exception as e:
            logger.error(f"Camera initialization error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _auto_loop(self):
        """
        Main autonomous control loop with PID
        UPDATED: Now captures RGB frames from Picamera2
        """
        logger.info("Auto loop started (PID mode with Picamera2)")
        
        prev_time = time.time()
        frame_count = 0
        
        while self.running:
            try:
                if self.robot.current_mode != 'auto':
                    break
                
                # ===== GET CAMERA FRAME =====
                # CHANGED: capture_frame() returns RGB directly from Picamera2
                frame = self.camera.capture_frame()
                
                if frame is None:
                    logger.warning("Failed to capture camera frame")
                    time.sleep(0.1)
                    continue
                
                # ===== DETECT LANE =====
                # Frame is already RGB, detect_line now handles RGB input
                error, x_line, center_x, frame_debug = detect_line(frame, self.detection_config)
                
                # Store for web interface
                self.latest_debug_frame = frame_debug
                self.latest_error = error
                
                # ===== CALCULATE TIME STEP =====
                current_time = time.time()
                dt = current_time - prev_time
                prev_time = current_time
                
                # ===== CHECK IF LANE IS DETECTED =====
                if abs(error) > frame.shape[1] * 0.4:  # Error too large = no lane
                    self.lane_lost_count += 1
                    
                    if self.lane_lost_count >= self.lane_lost_threshold:
                        # Lane lost - slow down and stop
                        logger.warning("Lane lost! Stopping...")
                        self.robot.driver.stop()
                        self.robot.current_state = 'LANE LOST - STOPPED'
                        time.sleep(0.5)
                        continue
                    else:
                        # Lane temporarily lost - maintain last command
                        logger.debug(f"Lane detection weak ({self.lane_lost_count}/{self.lane_lost_threshold})")
                else:
                    # Lane detected - reset counter
                    self.lane_lost_count = 0
                
                # ===== PID CONTROL =====
                correction = self.pid.compute(error, dt)
                self.latest_correction = correction
                
                # ===== CALCULATE MOTOR SPEEDS =====
                # Base speed - correction for turning
                left_speed = self.base_speed - correction
                right_speed = self.base_speed + correction
                
                # Clamp to valid range
                left_speed = max(self.min_speed, min(self.max_speed, int(left_speed)))
                right_speed = max(self.min_speed, min(self.max_speed, int(right_speed)))
                
                # ===== SEND TO MOTORS =====
                self.robot.driver.set_motors(left_speed, right_speed)
                
                # Update state
                if abs(correction) > 50:
                    if correction > 0:
                        self.robot.current_state = 'AUTO - TURNING RIGHT'
                    else:
                        self.robot.current_state = 'AUTO - TURNING LEFT'
                else:
                    self.robot.current_state = 'AUTO - FOLLOWING LANE'
                
                # ===== LOGGING (every 30 frames) =====
                frame_count += 1
                if frame_count % 30 == 0:
                    pid_info = self.pid.get_components()
                    fps = self.camera.get_fps()
                    logger.debug(
                        f"PID: error={error:+4d}px, "
                        f"P={pid_info['p']:+6.1f}, I={pid_info['i']:+6.1f}, D={pid_info['d']:+6.1f}, "
                        f"correction={correction:+6.1f}, "
                        f"motors=L{left_speed}/R{right_speed}, "
                        f"FPS={fps:.1f}"
                    )
                
                # Small delay to control loop rate (~30Hz)
                time.sleep(0.03)
                
            except Exception as e:
                logger.error(f"Error in auto loop: {e}")
                import traceback
                traceback.print_exc()
                self.robot.driver.stop()
                break
        
        self.robot.driver.stop()
        logger.info("Auto loop ended")
    
    def get_debug_frame(self):
        """Get latest debug frame for visualization (RGB format)"""
        return self.latest_debug_frame
    
    def get_pid_status(self) -> dict:
        """Get PID controller status for tuning"""
        return {
            'error': self.latest_error,
            'correction': self.latest_correction,
            **self.pid.get_components()
        }


class FollowModeController:
    """
    Follow mode controller
    Tracks and follows colored objects
    """
    
    def __init__(self, robot_controller: RobotController):
        """
        Initialize follow mode controller
        
        Args:
            robot_controller: Main robot controller instance
        """
        self.robot = robot_controller
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        # Follow settings
        self.target_color = 'red'
        self.follow_distance = 50  # cm
        self.tracking = False
        
        # Target info
        self.target_x = 0
        self.target_y = 0
        self.target_w = 0
        self.target_h = 0
        self.confidence = 0
        self.target_distance = 0
        
        logger.info("Follow Mode Controller initialized")
    
    def start(self):
        """Start follow mode"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._follow_loop, daemon=True)
            self.thread.start()
            logger.info(f"Follow mode started - tracking {self.target_color}")
    
    def stop(self):
        """Stop follow mode"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.robot.driver.stop()
        self.tracking = False
        logger.info("Follow mode stopped")
    
    def set_target_color(self, color: str):
        """Set target color to follow"""
        self.target_color = color
        logger.info(f"Target color changed to: {color}")
    
    def set_follow_distance(self, distance: int):
        """Set safe follow distance"""
        self.follow_distance = distance
        logger.info(f"Follow distance set to: {distance} cm")
    
    def get_target_data(self) -> dict:
        """Get current target tracking data"""
        return {
            'tracking': self.tracking,
            'target_color': self.target_color,
            'target_x': self.target_x,
            'target_y': self.target_y,
            'target_w': self.target_w,
            'target_h': self.target_h,
            'confidence': self.confidence,
            'target_distance': self.target_distance
        }
    
    def _follow_loop(self):
        """
        Main follow control loop
        TODO: Integrate with object_tracker.py and Picamera2
        """
        while self.running:
            try:
                if self.robot.current_mode != 'follow':
                    break
                
                # TODO: Implement color tracking with Picamera2
                # For now, just maintain stopped state
                self.robot.driver.stop()
                self.robot.current_state = 'FOLLOW MODE - IDLE'
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in follow loop: {e}")
                self.robot.driver.stop()
                self.tracking = False
                break
        
        self.robot.driver.stop()
        self.tracking = False
        logger.info("Follow loop ended")