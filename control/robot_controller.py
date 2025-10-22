"""
Robot Controller - Interface between Web Dashboard and Motor Driver
Handles commands from Flask app and controls motors
"""

import threading
import time
import logging
from typing import Optional
from datetime import datetime

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
            motor_driver: L298N driver instance
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
        
        # Use 80% of current speed for turning
        turn_speed = int(self.current_speed * 0.8)
        self.driver.turn_left(turn_speed)
        self.current_state = 'TURNING LEFT'
        self._update_command_time()
        return True
    
    def right(self):
        """Turn right"""
        if not self._check_manual_mode():
            return False
        
        # Use 80% of current speed for turning
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
    Autonomous mode controller
    Handles automatic behaviors (line following, obstacle avoidance, etc.)
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
        
        logger.info("Auto Mode Controller initialized")
    
    def start(self):
        """Start autonomous mode"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.thread.start()
            logger.info("Autonomous mode started")
    
    def stop(self):
        """Stop autonomous mode"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.robot.driver.stop()
        logger.info("Autonomous mode stopped")
    
    def _auto_loop(self):
        """
        Main autonomous control loop
        Implement your autonomous behaviors here
        """
        while self.running:
            try:
                # Example: Simple line following behavior
                # Replace with actual sensor readings and logic
                
                if self.robot.current_mode != 'auto':
                    break
                
                # Placeholder: Move forward slowly in auto mode
                self.robot.driver.forward(100)
                self.robot.current_state = 'FOLLOWING LINE'
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in auto loop: {e}")
                self.robot.driver.stop()
                break
        
        self.robot.driver.stop()
        logger.info("Auto loop ended")


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
        TODO: Integrate with object_tracker.py
        """
        while self.running:
            try:
                if self.robot.current_mode != 'follow':
                    break
                
                # TODO: Get target data from object_tracker
                # target_data = object_tracker.detect_color(self.target_color)
                
                # Placeholder: Simulate target detection
                # Replace with actual color detection logic
                import random
                self.tracking = random.choice([True, False])
                
                if self.tracking:
                    # Simulate target position (normalized 0-1)
                    self.target_x = random.uniform(0.3, 0.7)
                    self.target_y = random.uniform(0.3, 0.7)
                    self.target_w = random.uniform(0.1, 0.3)
                    self.target_h = random.uniform(0.1, 0.3)
                    self.confidence = random.randint(70, 95)
                    self.target_distance = random.uniform(30, 80)
                    
                    # Simple follow logic
                    # Center of frame is at 0.5
                    error_x = self.target_x - 0.5
                    
                    # Turn towards target
                    if abs(error_x) > 0.1:
                        if error_x > 0:
                            # Target is on right, turn right
                            self.robot.driver.turn_right(120)
                            self.robot.current_state = 'FOLLOWING TARGET - TURNING RIGHT'
                        else:
                            # Target is on left, turn left
                            self.robot.driver.turn_left(120)
                            self.robot.current_state = 'FOLLOWING TARGET - TURNING LEFT'
                    else:
                        # Target centered, move forward or backward based on distance
                        if self.target_distance > self.follow_distance + 10:
                            # Too far, move forward
                            self.robot.driver.forward(150)
                            self.robot.current_state = 'FOLLOWING TARGET - APPROACHING'
                        elif self.target_distance < self.follow_distance - 10:
                            # Too close, move backward
                            self.robot.driver.backward(100)
                            self.robot.current_state = 'FOLLOWING TARGET - BACKING UP'
                        else:
                            # At good distance, stop
                            self.robot.driver.stop()
                            self.robot.current_state = 'FOLLOWING TARGET - LOCKED'
                else:
                    # Target lost, stop and search
                    self.robot.driver.stop()
                    self.robot.current_state = 'FOLLOW MODE - TARGET LOST'
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in follow loop: {e}")
                self.robot.driver.stop()
                self.tracking = False
                break
        
        self.robot.driver.stop()
        self.tracking = False
        logger.info("Follow loop ended")