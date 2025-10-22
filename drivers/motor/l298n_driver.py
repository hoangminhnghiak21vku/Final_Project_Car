"""
L298N Motor Driver for Raspberry Pi 5 using gpiozero
Controls 2 DC motors for differential drive robot
Compatible with Python 3.12
"""

from gpiozero import Motor, OutputDevice
from gpiozero.pins.pigpio import PiGPIOFactory
import time
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class L298NDriver:
    """
    L298N H-Bridge Motor Driver Controller using gpiozero
    
    Wiring:
    - Left Motor: ENA (PWM), IN1, IN2
    - Right Motor: ENB (PWM), IN3, IN4
    """
    
    def __init__(self, config: dict, use_pigpio: bool = False):
        """
        Initialize L298N driver with gpiozero
        
        Args:
            config: Hardware configuration dictionary
            use_pigpio: Use pigpio pin factory for better PWM (optional)
        """
        self.config = config
        
        # Use pigpio for hardware PWM (better performance) - OPTIONAL
        self.factory = None
        if use_pigpio:
            try:
                from gpiozero.pins.pigpio import PiGPIOFactory
                self.factory = PiGPIOFactory()
                logger.info("Using pigpio pin factory")
            except Exception as e:
                logger.warning(f"pigpio not available: {e}, using default pin factory")
        else:
            logger.info("Using default pin factory (software PWM)")
        
        # Motor configurations
        self.left_config = config['motor_driver']['left_motor']
        self.right_config = config['motor_driver']['right_motor']
        
        # PWM frequency
        self.pwm_freq = config.get('pwm', {}).get('frequency', 1000)
        
        # Setup left motor
        # Motor(forward, backward, enable=None, pwm=True, pin_factory=None)
        self.left_motor = Motor(
            forward=self.left_config['input1_pin'],
            backward=self.left_config['input2_pin'],
            enable=self.left_config['enable_pin'],
            pwm=True,
            pin_factory=self.factory
        )
        
        # Setup right motor
        self.right_motor = Motor(
            forward=self.right_config['input1_pin'],
            backward=self.right_config['input2_pin'],
            enable=self.right_config['enable_pin'],
            pwm=True,
            pin_factory=self.factory
        )
        
        # Current speeds
        self.current_left_speed = 0
        self.current_right_speed = 0
        
        # Reverse flags
        self.left_reverse = self.left_config.get('reverse', False)
        self.right_reverse = self.right_config.get('reverse', False)
        
        logger.info("L298N Driver initialized with gpiozero")
        logger.info(f"Left Motor: EN={self.left_config['enable_pin']}, "
                   f"IN1={self.left_config['input1_pin']}, "
                   f"IN2={self.left_config['input2_pin']}")
        logger.info(f"Right Motor: EN={self.right_config['enable_pin']}, "
                   f"IN1={self.right_config['input1_pin']}, "
                   f"IN2={self.right_config['input2_pin']}")
    
    def _speed_to_value(self, speed: int) -> float:
        """
        Convert speed (-255 to 255) to gpiozero value (-1.0 to 1.0)
        
        Args:
            speed: Motor speed -255 to 255
            
        Returns:
            Float value -1.0 to 1.0
        """
        # Clamp speed
        speed = max(-255, min(255, speed))
        # Convert to -1.0 to 1.0
        return speed / 255.0
    
    def set_left_motor(self, speed: int):
        """
        Set left motor speed and direction
        
        Args:
            speed: -255 to 255 (negative = backward, positive = forward)
        """
        value = self._speed_to_value(speed)
        
        # Apply reverse if configured
        if self.left_reverse:
            value = -value
        
        # Set motor value
        # Positive = forward, Negative = backward, 0 = stop
        self.left_motor.value = value
        
        self.current_left_speed = speed
        logger.debug(f"Left motor: speed={speed}, value={value:.2f}")
    
    def set_right_motor(self, speed: int):
        """
        Set right motor speed and direction
        
        Args:
            speed: -255 to 255 (negative = backward, positive = forward)
        """
        value = self._speed_to_value(speed)
        
        # Apply reverse if configured
        if self.right_reverse:
            value = -value
        
        # Set motor value
        self.right_motor.value = value
        
        self.current_right_speed = speed
        logger.debug(f"Right motor: speed={speed}, value={value:.2f}")
    
    def set_motors(self, left_speed: int, right_speed: int):
        """
        Set both motors simultaneously
        
        Args:
            left_speed: -255 to 255
            right_speed: -255 to 255
        """
        self.set_left_motor(left_speed)
        self.set_right_motor(right_speed)
    
    def forward(self, speed: int = 180):
        """Move forward"""
        self.set_motors(speed, speed)
        logger.info(f"Moving forward at speed {speed}")
    
    def backward(self, speed: int = 180):
        """Move backward"""
        self.set_motors(-speed, -speed)
        logger.info(f"Moving backward at speed {speed}")
    
    def turn_left(self, speed: int = 150):
        """
        Turn left (differential steering)
        Left motor backward, right motor forward
        """
        self.set_motors(-speed, speed)
        logger.info(f"Turning left at speed {speed}")
    
    def turn_right(self, speed: int = 150):
        """
        Turn right (differential steering)
        Left motor forward, right motor backward
        """
        self.set_motors(speed, -speed)
        logger.info(f"Turning right at speed {speed}")
    
    def stop(self):
        """Stop both motors"""
        self.left_motor.stop()
        self.right_motor.stop()
        self.current_left_speed = 0
        self.current_right_speed = 0
        logger.info("Motors stopped")
    
    def get_speeds(self) -> Tuple[int, int]:
        """Get current motor speeds"""
        return (self.current_left_speed, self.current_right_speed)
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        self.stop()
        self.left_motor.close()
        self.right_motor.close()
        logger.info("L298N Driver cleaned up")
    
    def __del__(self):
        """Destructor"""
        try:
            self.cleanup()
        except:
            pass


class DifferentialDrive:
    """
    High-level differential drive controller
    Converts linear and angular velocity to wheel speeds
    """
    
    def __init__(self, driver: L298NDriver, config: dict):
        """
        Initialize differential drive
        
        Args:
            driver: L298N driver instance
            config: Robot configuration
        """
        self.driver = driver
        self.wheel_base = config['robot']['wheel_base']
        self.wheel_diameter = config['robot']['wheel_diameter']
        self.max_speed = config['motor_driver']['left_motor']['max_speed']
    
    def set_velocity(self, linear: float, angular: float):
        """
        Set robot velocity in m/s and rad/s
        
        Args:
            linear: Linear velocity (m/s) - positive = forward
            angular: Angular velocity (rad/s) - positive = counter-clockwise
        """
        # Differential drive kinematics
        v_left = linear - (angular * self.wheel_base / 2.0)
        v_right = linear + (angular * self.wheel_base / 2.0)
        
        # Convert m/s to motor speed (0-255)
        max_velocity = 1.0  # m/s (adjust based on your robot)
        
        left_speed = int((v_left / max_velocity) * self.max_speed)
        right_speed = int((v_right / max_velocity) * self.max_speed)
        
        # Clamp to valid range
        left_speed = max(-self.max_speed, min(self.max_speed, left_speed))
        right_speed = max(-self.max_speed, min(self.max_speed, right_speed))
        
        self.driver.set_motors(left_speed, right_speed)
        
        logger.debug(f"Velocity: linear={linear:.2f}m/s, angular={angular:.2f}rad/s")
        logger.debug(f"Wheel speeds: left={left_speed}, right={right_speed}")
    
    def stop(self):
        """Stop robot"""
        self.driver.stop()