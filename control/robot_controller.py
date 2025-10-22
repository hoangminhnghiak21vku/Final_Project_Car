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
        self.current_mode = 'manual'  # 'manual' or 'auto'
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
        """Set control mode (manual/auto)"""
        if mode in ['manual', 'auto']:
            self.current_mode = mode
            self.current_state = 'AUTO MODE' if mode == 'auto' else 'IDLE'
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
        self.current_state = 'STOPPED' if self.current_mode == 'manual' else 'AUTO MODE'
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
            logger.warning("Cannot execute command: Not in manual mode")
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
            
            # Check command timeout
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