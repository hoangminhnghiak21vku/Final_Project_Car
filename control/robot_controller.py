import threading
import time
import logging
import numpy as np
from typing import Optional
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from control.pid_controller import PIDController
from perception.lane_detector import detect_line
from perception.camera_manager import CameraManager, get_web_camera
from perception.object_detector import ObjectDetector
from perception.imu_sensor_fusion import IMUSensorFusion

logger = logging.getLogger(__name__)

class RobotController:
    """
    Main robot controller
    Manages motor control, safety, state, and IMU
    """
    
    def __init__(self, motor_driver, config: dict):
        self.driver = motor_driver
        self.config = config
        
        # Current state
        self.current_mode = 'manual'
        self.current_state = 'IDLE'
        self.current_speed = config.get('lane_following', {}).get('base_speed', 150)
        
        # Safety
        self.emergency_stopped = False
        self.last_command_time = time.time()
        self.timeout = config.get('safety', {}).get('timeout', 5.0)
        
        # Watchdog thread
        self.running = True
        self.watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self.watchdog_thread.start()
        
        # IMU Initialization
        try:
            self.imu = IMUSensorFusion()
            if self.imu.connected:
                self.imu.start()
                logger.info("✅ IMU initialized successfully")
            else:
                logger.warning("⚠️ IMU not connected! Smart turn will use fallback mode.")
                self.imu = None
        except Exception as e:
            logger.error(f"❌ IMU initialization failed: {e}")
            self.imu = None

        logger.info("Robot Controller initialized")
    
    def set_mode(self, mode: str):
        """Set control mode (manual/auto)"""
        if mode in ['manual', 'auto']:
            self.current_mode = mode
            if mode == 'auto':
                self.current_state = 'AUTO MODE'
            else:
                self.current_state = 'IDLE'
            logger.info(f"Mode changed to: {mode}")
            return True
        return False

    def set_speed(self, speed: int):
        self.current_speed = max(0, min(255, speed))
        logger.info(f"Speed set to: {self.current_speed}")
    
    def forward(self):
        if not self._check_manual_mode(): return False
        self.driver.forward(self.current_speed)
        self.current_state = 'MOVING FORWARD'
        self._update_command_time()
        return True
    
    def backward(self):
        if not self._check_manual_mode(): return False
        self.driver.backward(self.current_speed)
        self.current_state = 'MOVING BACKWARD'
        self._update_command_time()
        return True
    
    def left(self):
        if not self._check_manual_mode(): return False
        turn_speed = int(self.current_speed * 0.8)
        self.driver.turn_left(turn_speed)
        self.current_state = 'TURNING LEFT'
        self._update_command_time()
        return True
    
    def right(self):
        if not self._check_manual_mode(): return False
        turn_speed = int(self.current_speed * 0.8)
        self.driver.turn_right(turn_speed)
        self.current_state = 'TURNING RIGHT'
        self._update_command_time()
        return True
    
    def stop(self):
        self.driver.stop()
        if self.current_mode == 'manual':
            self.current_state = 'STOPPED'
        elif self.current_mode == 'auto':
            self.current_state = 'AUTO MODE'
        self._update_command_time()
        return True
    
    def emergency_stop(self):
        self.driver.stop()
        self.emergency_stopped = True
        self.current_state = 'EMERGENCY STOP'
        logger.warning("🚨 EMERGENCY STOP ACTIVATED")
        return True
    
    def reset_emergency(self):
        self.emergency_stopped = False
        self.current_state = 'IDLE'
        logger.info("Emergency stop reset")
    
    def smart_turn(self, target_angle: float, speed: int = 250, timeout: float = 5.0):
        """Smart turn using IMU - Robust Version"""
        if self.emergency_stopped: return

        # Clamp speed
        if speed < 130:
            logger.warning(f"Speed {speed} too low, setting to 130")
            speed = 130
        elif speed > 255:
            speed = 255
        
        if abs(target_angle) > 180:
            logger.error(f"❌ Invalid angle: {target_angle}° (must be -180 to 180)")
            return
        
        # Fallback if IMU not ready
        if not hasattr(self, 'imu') or self.imu is None or not self.imu.connected:
            logger.warning("⚠️ IMU unavailable! Using time-based fallback.")
            self._fallback_turn(target_angle, speed)
            return
        
        logger.info(f"🔄 Smart Turn START: Target {target_angle}° at speed {speed}")
        
        try:
            self.imu.reset_yaw()
            start_time = time.time()
            last_yaw = 0.0
            stuck_counter = 0
            
            while True:
                if self.emergency_stopped: break

                current_yaw = self.imu.get_yaw()
                error = abs(target_angle) - abs(current_yaw)
                
                # Target reached condition
                if error <= 2.0:
                    logger.info(f"✅ Target Reached! Final: {current_yaw:.1f}°")
                    break
                
                # Timeout
                if time.time() - start_time > timeout:
                    logger.warning(f"⚠️ Turn Timeout! Stopped at {current_yaw:.1f}° (Target: {target_angle}°)")
                    break
                
                # Stuck detection
                if abs(current_yaw - last_yaw) < 0.1:
                    stuck_counter += 1
                    if stuck_counter > 50: # 0.5s stuck
                        logger.error(f"❌ Robot appears stuck! Stopping turn.")
                        break
                else:
                    stuck_counter = 0
                last_yaw = current_yaw
                
                # Overshoot protection
                if target_angle > 0 and current_yaw > target_angle + 5:
                    logger.warning(f"⚠️ Overshoot detected! {current_yaw:.1f}° > {target_angle}°")
                    break
                elif target_angle < 0 and current_yaw < target_angle - 5:
                    logger.warning(f"⚠️ Overshoot detected! {current_yaw:.1f}° < {target_angle}°")
                    break
                
                # Adaptive speed
                if error > 30:
                    current_speed = speed
                elif error > 10:
                    current_speed = int(speed * 0.7)
                else:
                    current_speed = max(130, int(speed * 0.5))
                
                if target_angle > 0:
                    self.driver.turn_left(current_speed)
                else:
                    self.driver.turn_right(current_speed)
                
                time.sleep(0.01)
            
        except Exception as e:
            logger.error(f"❌ Error during smart turn: {e}")
        finally:
            self.driver.stop()
            time.sleep(0.2)

    def _fallback_turn(self, target_angle: float, speed: int):
        """Time-based fallback turn"""
        duration = 0.6 * (abs(target_angle) / 90.0)
        logger.info(f"⏱️ Fallback Turn: {target_angle}° for {duration:.2f}s")
        if target_angle > 0:
            self.driver.turn_left(speed)
        else:
            self.driver.turn_right(speed)
        time.sleep(duration)
        self.driver.stop()
    
    def set_auto_mode(self, enabled: bool):
        """Compatibility wrapper for main.py"""
        if enabled:
            return self.set_mode('auto')
        else:
            return self.set_mode('manual')

    def get_state(self) -> dict:
        left_speed, right_speed = self.driver.get_speeds()
        imu_status = "Connected" if (self.imu and self.imu.connected) else "Disconnected"
        
        return {
            'mode': self.current_mode,
            'state': self.current_state,
            'speed': self.current_speed,
            'emergency_stopped': self.emergency_stopped,
            'left_motor_speed': left_speed,
            'right_motor_speed': right_speed,
            'last_command_age': time.time() - self.last_command_time,
            'imu_status': imu_status
        }
    
    def _check_manual_mode(self) -> bool:
        if self.emergency_stopped:
            logger.warning("Cannot execute: Emergency stop active")
            return False
        if self.current_mode != 'manual':
            # logger.warning(f"Cannot execute: Not in manual mode")
            return False
        return True
    
    def _update_command_time(self):
        self.last_command_time = time.time()
    
    def _watchdog(self):
        """Stops robot if no command received in manual mode"""
        while self.running:
            time.sleep(0.5)
            age = time.time() - self.last_command_time
            
            if age > self.timeout and self.current_mode == 'manual':
                left, right = self.driver.get_speeds()
                if left != 0 or right != 0:
                    logger.warning(f"Command timeout ({age:.1f}s) - Auto stopping")
                    self.stop()
                    self.current_state = 'IDLE'
            
            # Reset state to IDLE if stopped manually
            if self.current_state in ['MOVING FORWARD', 'MOVING BACKWARD', 
                                     'TURNING LEFT', 'TURNING RIGHT']:
                left, right = self.driver.get_speeds()
                if left == 0 and right == 0:
                    self.current_state = 'IDLE'

    def cleanup(self):
        self.running = False
        if self.imu: self.imu.stop()
        self.driver.cleanup()
        logger.info("Robot Controller cleaned up")


class AutoModeController:
    """
    Autonomous mode controller - FIXED VERSION
    ✅ Robot only moves when lane is detected
    ✅ Lane Recovery Logic
    """
    
    def __init__(self, robot_controller: RobotController):
        self.robot = robot_controller
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.camera: Optional[CameraManager] = None
        
        # Load Model - Sử dụng chính xác file best.onnx theo yêu cầu
        self.detector = ObjectDetector(
            model_path='data/models/best.onnx', 
            conf_threshold=0.5
        )
        
        # PID
        pid_config = robot_controller.config.get('lane_following', {}).get('pid', {})
        self.pid = PIDController(
            kp=pid_config.get('kp', 0.2),
            ki=pid_config.get('ki', 0.0),
            kd=pid_config.get('kd', 0.05),
            output_min=pid_config.get('min_output', -255),
            output_max=pid_config.get('max_output', 255),
            derivative_smoothing=pid_config.get('derivative_smoothing', 0.7)
        )
        
        # Configs
        lane_config = robot_controller.config.get('lane_following', {})
        self.base_speed = lane_config.get('base_speed', 100)
        self.default_speed = self.base_speed
        self.detection_config = robot_controller.config.get('ai', {}).get('lane_detection', {})
        
        # ===== SIGN DETECTION THRESHOLDS =====
        self.DIST_PREPARE = 65   
        self.DIST_EXECUTE = 100  
        
        # ===== LANE RECOVERY CONFIG =====
        self.MAX_ERROR_THRESHOLD = 150
        self.lane_lost_count = 0
        self.lane_lost_threshold = 5 
        
        # Recovery System State
        self.recovery_mode = False
        self.recovery_direction = 'left' 
        self.recovery_scan_speed = 130    
        self.recovery_scan_time = 0.0     
        self.recovery_max_scan_time = 3.0 
        self.recovery_attempts = 0
        self.recovery_max_attempts = 2    
        
        self.latest_debug_frame = None
        self.latest_error = 0
        self.latest_correction = 0
        
        logger.info("Auto Mode Controller initialized")
    
    def start(self):
        if not self.running:
            if not self._init_shared_camera():
                return False
            
            self.pid.reset()
            self.lane_lost_count = 0
            self.base_speed = self.default_speed
            self.robot.set_mode('auto')
            
            self.running = True
            self.thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.thread.start()
            logger.info("Auto mode started")
            return True
        return False
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.robot.driver.stop()
        logger.info("Auto mode stopped")
    
    def _init_shared_camera(self) -> bool:
        try:
            self.camera = get_web_camera(self.robot.config)
            if not self.camera.is_running():
                if not self.camera.start():
                    return False
            return True
        except Exception as e:
            logger.error(f"Camera init error: {e}")
            return False
    
    def _auto_loop(self):
        """
        Main Auto Loop with Lane Recovery and Smart Sign Logic
        """
        logger.info("Auto loop started")
        
        while self.running:
            try:
                if self.robot.current_mode != 'auto' or self.robot.emergency_stopped:
                    time.sleep(0.1)
                    continue
                
                frame = self.camera.capture_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue
                
                # ===== 1. DETECT TRAFFIC SIGNS =====
                detections, debug_frame = self.detector.detect(frame)
                sign_action = None
                
                if detections:
                    sign = max(detections, key=lambda x: x['w'] * x['h'])
                    sign_name = sign['class_name']
                    sign_size = max(sign['w'], sign['h'])
                    
                    if sign_size < self.DIST_PREPARE:
                        self.robot.current_state = f"DETECTED: {sign_name} ({sign_size:.0f}px) - Too far"
                    
                    elif sign_size >= self.DIST_PREPARE and sign_size < self.DIST_EXECUTE:
                        self.robot.current_state = f"PREPARE: {sign_name} ({sign_size:.0f}px)"
                    
                    elif sign_size >= self.DIST_EXECUTE:
                        logger.info(f"🚦 EXECUTING: {sign_name} (Size: {sign_size:.0f}px)")
                        
                        # Bao gồm tên cũ (stop, red_right) và tên mới nếu có
                        if sign_name in ['stop_sign', 'red_light', 'stop', 'red_right']:
                            self.robot.driver.stop()
                            sign_action = "STOP"
                            time.sleep(0.1)
                        
                        elif sign_name == 'green_light':
                            self.base_speed = self.default_speed
                        
                        elif sign_name in ['left_turn_sign', 'left']:
                            logger.info("⬅️ Smart Turn +90°")
                            self.robot.smart_turn(90, speed=250)
                            continue
                        
                        elif sign_name in ['right_turn_sign', 'turn_right']:
                            logger.info("➡️ Smart Turn -90°")
                            self.robot.smart_turn(-90, speed=250)
                            continue
                        
                        elif sign_name == 'speed_limit_signs':
                            self.base_speed = 100
                        
                        elif sign_name in ['parking_signs', 'parking']:
                            self.robot.driver.stop()
                            self.stop()
                            break
                
                if sign_action in ["STOP", "TURN"]:
                    continue
                
                # ===== 2. LANE DETECTION =====
                error, x_line, center_x, lane_debug_frame = detect_line(
                    frame, self.detection_config
                )
                self.latest_debug_frame = lane_debug_frame
                self.latest_error = error
                
                # ===== 3. LANE VALIDITY CHECK & RECOVERY =====
                is_lane_valid = abs(error) <= self.MAX_ERROR_THRESHOLD
                
                if not is_lane_valid:
                    self.lane_lost_count += 1
                    
                    if self.lane_lost_count >= self.lane_lost_threshold:
                        # Activate Recovery Mode
                        if not self.recovery_mode:
                            logger.info("🔍 RECOVERY MODE ACTIVATED")
                            self.recovery_mode = True
                            self.recovery_scan_time = 0.0
                            self.recovery_attempts = 0
                            self.recovery_direction = 'left'
                        
                        lane_found = self._perform_lane_recovery(frame)
                        
                        if lane_found:
                            logger.info("✅ Lane found! Resuming.")
                            self.recovery_mode = False
                            self.lane_lost_count = 0
                        elif self.recovery_attempts >= self.recovery_max_attempts:
                            logger.error("❌ Lane recovery failed! STOPPED.")
                            self.robot.driver.stop()
                            self.robot.current_state = 'RECOVERY FAILED'
                            self.recovery_mode = False
                            time.sleep(1.0)
                        
                        continue
                    else:
                        # Stop briefly while counting
                        self.robot.driver.stop()
                        self.robot.current_state = f'SEARCHING ({self.lane_lost_count}/{self.lane_lost_threshold})'
                        time.sleep(0.05)
                        continue
                
                # ===== LANE FOUND =====
                self.lane_lost_count = 0
                
                if self.recovery_mode:
                    logger.info("✅ Lane recovered during scan!")
                    self.recovery_mode = False
                    self.robot.driver.stop()
                    time.sleep(0.2)
                
                if not detections:
                    self.robot.current_state = f'FOLLOWING LANE (Err: {error:.0f})'
                
                # ===== 4. PID CONTROL =====
                correction = self.pid.compute(error, dt=0.05)
                self.latest_correction = correction
                
                left_speed = max(-255, min(255, int(self.base_speed - correction)))
                right_speed = max(-255, min(255, int(self.base_speed + correction)))
                
                self.robot.driver.set_motors(left_speed, right_speed)
                time.sleep(0.03)
                
            except Exception as e:
                logger.error(f"❌ Error in auto loop: {e}")
                self.robot.driver.stop()
                break
        
        self.robot.driver.stop()
        logger.info("Auto loop ended")
    
    def _perform_lane_recovery(self, frame) -> bool:
        """Scanning logic to find lost lane"""
        error, _, _, _ = detect_line(frame, self.detection_config)
        
        if abs(error) <= self.MAX_ERROR_THRESHOLD:
            return True
        
        self.recovery_scan_time += 0.05
        
        if self.recovery_scan_time >= self.recovery_max_scan_time:
            # Switch direction
            if self.recovery_direction == 'left':
                self.recovery_direction = 'right'
            else:
                self.recovery_direction = 'left'
                self.recovery_attempts += 1
            
            self.recovery_scan_time = 0.0
            
            if self.recovery_attempts >= self.recovery_max_attempts:
                return False
        
        # Turn to scan
        if self.recovery_direction == 'left':
            self.robot.driver.turn_left(self.recovery_scan_speed)
            self.robot.current_state = f'SCAN LEFT ({self.recovery_scan_time:.1f}s)'
        else:
            self.robot.driver.turn_right(self.recovery_scan_speed)
            self.robot.current_state = f'SCAN RIGHT ({self.recovery_scan_time:.1f}s)'
        
        return False
    
    def get_debug_frame(self):
        return self.latest_debug_frame