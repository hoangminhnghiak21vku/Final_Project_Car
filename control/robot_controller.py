"""
Robot Controller - AUTO MODE ONLY VERSION
"""

import threading
import time
import logging
import numpy as np
from typing import Optional
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
    Main robot controller - Auto Mode Only
    """
    
    def __init__(self, motor_driver, config: dict):
        self.driver = motor_driver
        self.config = config
        
        # State
        self.is_auto_running = False
        self.current_state = 'IDLE'
        self.current_speed = config.get('lane_following', {}).get('base_speed', 150)
        self.emergency_stopped = False
        
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


        logger.info("Robot Controller initialized (Auto Mode Only)")
    
    def set_auto_mode(self, enabled: bool):
        """Enable or disable autonomous driving"""
        if self.emergency_stopped and enabled:
            logger.warning("Cannot start Auto Mode: Emergency Stop Active")
            return False

        self.is_auto_running = enabled
        if enabled:
            self.current_state = 'AUTO DRIVING'
            logger.info("🚗 Auto Mode STARTED")
        else:
            self.current_state = 'IDLE'
            self.stop()
            logger.info("🛑 Auto Mode STOPPED")
        return True

    def set_speed(self, speed: int):
        self.current_speed = max(0, min(255, speed))
        logger.info(f"Base speed set to: {self.current_speed}")
    
    def stop(self):
        self.driver.stop()
        self.current_state = 'STOPPED'
    
    def emergency_stop(self):
        self.driver.stop()
        self.is_auto_running = False
        self.emergency_stopped = True
        self.current_state = 'EMERGENCY STOP'
        logger.warning("🚨 EMERGENCY STOP ACTIVATED")
        return True
    
    def reset_emergency(self):
        self.emergency_stopped = False
        self.current_state = 'IDLE'
        logger.info("Emergency stop reset")
    
    def smart_turn(self, target_angle: float, speed: int = 220, timeout: float = 5.0):
        """Executes a precision turn using IMU"""
        # Safety checks
        if self.emergency_stopped: return

        if speed < 170: speed = 170
        if speed > 255: speed = 255
        
        logger.info(f"🔄 Smart Turn START: Target {target_angle}°")
        
        # Check IMU availability
        if not hasattr(self, 'imu') or self.imu is None or not self.imu.connected:
            self._fallback_turn(target_angle, speed)
            return
        
        try:
            self.imu.reset_yaw()
            start_time = time.time()
            last_yaw = 0.0
            stuck_counter = 0
            
            # Initial kick to start movement
            if target_angle > 0:
                self.driver.turn_left(speed)
            else:
                self.driver.turn_right(speed)
            
            while True:
                if self.emergency_stopped: break

                current_yaw = self.imu.get_yaw()
                error = abs(target_angle) - abs(current_yaw)
                
                # Target reached
                if error <= 2.0:
                    break
                
                # Timeout
                if time.time() - start_time > timeout:
                    logger.warning("Smart turn timeout")
                    break
                
                # Stuck detection (yaw hasn't changed significantly in 0.5s)
                # 0.1 degree threshold might be too sensitive to noise, increased slightly to 0.5
                if abs(current_yaw - last_yaw) < 0.05:
                    stuck_counter += 1
                    if stuck_counter > 50: # 50 * 0.01s = 0.5s
                        logger.warning("Robot stuck during turn")
                        break
                else:
                    stuck_counter = 0
                last_yaw = current_yaw
                
                # Adaptive Speed control for smoother landing
                if error > 30:
                    turn_speed = speed
                elif error > 10:
                    turn_speed = int(speed * 0.7)
                else:
                    turn_speed = max(130, int(speed * 0.5)) # Slow down at end
                
                if target_angle > 0:
                    self.driver.turn_left(turn_speed)
                else:
                    self.driver.turn_right(turn_speed)
                
                time.sleep(0.01)
            
        except Exception as e:
            logger.error(f"Error during smart turn: {e}")
        finally:
            self.driver.stop()
            time.sleep(0.2)

    def _fallback_turn(self, target_angle: float, speed: int):
        # Rough estimate: 90 degrees takes ~0.6s at full speed (tune this)
        duration = 0.6 * (abs(target_angle) / 90.0)
        if target_angle > 0:
            self.driver.turn_left(speed)
        else:
            self.driver.turn_right(speed)
        time.sleep(duration)
        self.driver.stop()

    def get_state(self) -> dict:
        left_speed, right_speed = self.driver.get_speeds()
        return {
            'mode': 'auto' if self.is_auto_running else 'idle',
            'state': self.current_state,
            'speed': self.current_speed,
            'emergency_stopped': self.emergency_stopped,
            'left_motor_speed': left_speed,
            'right_motor_speed': right_speed,
            'imu_status': "Connected" if (self.imu and self.imu.connected) else "Disconnected"
        }

    def cleanup(self):
        self.is_auto_running = False
        if self.imu: self.imu.stop()
        self.driver.cleanup()
        logger.info("Robot Controller cleaned up")


class AutoModeController:
    """
    Autonomous driving logic (Lane Following + Traffic Signs)
    """
    
    def __init__(self, robot_controller: RobotController):
        self.robot = robot_controller
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.camera: Optional[CameraManager] = None
        
        # Load AI Models
        self.detector = ObjectDetector(
            model_path='data/models/best.onnx', 
            conf_threshold=0.5
        )
        
        # PID Config
        pid_config = robot_controller.config.get('lane_following', {}).get('pid', {})
        self.pid = PIDController(
            kp=pid_config.get('kp', 0.8),
            ki=pid_config.get('ki', 0.0),
            kd=pid_config.get('kd', 0.3),
            output_min=pid_config.get('min_output', -255),
            output_max=pid_config.get('max_output', 255),
            derivative_smoothing=pid_config.get('derivative_smoothing', 0.7)
        )
        
        self.detection_config = robot_controller.config.get('ai', {}).get('lane_detection', {})
        self.lane_lost_count = 0
        self.DIST_EXECUTE = 170
        self.DIST_PREPARE = 140
        self.base_speed = self.robot.current_speed
        self.default_speed = self.base_speed

        logger.info("Auto Mode Controller initialized")
    
    def start(self):
        if not self.running:
            try:
                self.camera = get_web_camera(self.robot.config)
                if not self.camera.is_running():
                    if not self.camera.start(): return False
            except Exception as e:
                logger.error(f"Camera init error: {e}")
                return False
            
            self.pid.reset()
            self.lane_lost_count = 0
            self.base_speed = self.robot.current_speed # Update speed on start
            self.default_speed = self.base_speed

            self.running = True
            self.thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.thread.start()
            logger.info("Auto Mode Thread Started")
            return True
        return False
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.robot.driver.stop()
        logger.info("Auto Mode Thread Stopped")
    
    def _safe_wait(self, duration: float):
        """Wait for duration but check for emergency stop"""
        end_time = time.time() + duration
        while time.time() < end_time:
            if self.robot.emergency_stopped or not self.robot.is_auto_running:
                return False
            time.sleep(0.1)
        return True

    def _auto_loop(self):
        logger.info("Auto loop started")
        
        # Debounce/Consistency check for signs
        sign_consistency_count = 0
        last_sign_name = None

        while self.running:
            try:
                # Check if auto mode is actually enabled
                if not self.robot.is_auto_running or self.robot.emergency_stopped:
                    time.sleep(0.1)
                    continue
                
                frame = self.camera.capture_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue
                
                # 1. Traffic Sign Detection
                detections, _ = self.detector.detect(frame)
                sign_action = None 
                
                # Filter low confidence detections (Redundant check if config handles it, but safe)
                valid_detections = [d for d in detections if d['conf'] > 0.6]

                if valid_detections:
                    sign = max(valid_detections, key=lambda x: x['w'] * x['h'])
                    sign_name = sign['class_name']
                    sign_size = max(sign['w'], sign['h'])
                    
                    # Consistency check: Sign must appear in consecutive frames
                    if sign_name == last_sign_name:
                        sign_consistency_count += 1
                    else:
                        sign_consistency_count = 0
                        last_sign_name = sign_name

                    # Only act if sign is consistent (e.g. seen 2+ times)
                    if sign_consistency_count >= 1:
                        self.robot.current_state = f"SIGN: {sign_name} ({sign_size:.0f}px)"
                        
                        # Logic based on sign size/distance
                        if sign_size < self.DIST_PREPARE:
                            pass # Too far
                        elif sign_size > self.DIST_EXECUTE + 50:
                            pass # Too close/passed
                        else:
                            # Execute Action
                            logger.info(f"🚦 EXECUTING: {sign_name} (Size: {sign_size:.0f})")
                            
                            if sign_name in ['stop', 'red_right']:
                                self.robot.driver.stop()
                                sign_action = "STOP"
                                self.robot.current_state = "STOPPING..."
                                
                                # Use safe wait instead of simple sleep
                                if not self._safe_wait(2.0): break 
                                
                                # Reset consistency to avoid immediate re-trigger
                                sign_consistency_count = 0 
                            
                            elif sign_name == 'green_light':
                                self.base_speed = self.default_speed
                            
                            elif sign_name == 'turn_left':
                                logger.info("⬅️ Left Turn detected -> Smart Turn +90°")
                                self.robot.smart_turn(90, speed=220)
                                sign_action = "TURN"
                                sign_consistency_count = 0
                                continue 
                                
                            
                            elif sign_name == 'turn_right':
                                logger.info("➡️ Right Turn detected -> Smart Turn -90°")
                                self.robot.smart_turn(-90, speed=220)
                                sign_action = "TURN"
                                sign_consistency_count = 0
                                continue
                            
                            
                            
                            elif sign_name == 'parking':
                                self.robot.driver.stop()
                                self.robot.set_auto_mode(False)
                                sign_action = "STOP"
                                break 
                else:
                    # Reset consistency if no sign seen
                    sign_consistency_count = 0
                    last_sign_name = None
                    if self.robot.current_state.startswith("SIGN:") or self.robot.current_state == "STOPPING...":
                        self.robot.current_state = 'AUTO DRIVING'
                
                if sign_action in ["STOP", "TURN"]:
                    continue

                # 2. Lane Following
                error, _, _, _ = detect_line(frame, self.detection_config)
                
                # Handle Lane Loss
                if abs(error) > frame.shape[1] * 0.4:
                    self.lane_lost_count += 1
                    if self.lane_lost_count >= 10:
                        self.robot.driver.stop()
                        self.robot.current_state = 'LANE LOST'
                        continue
                else:
                    self.lane_lost_count = 0
                    # Only update state if not showing sign info
                    if not valid_detections:
                        self.robot.current_state = 'AUTO DRIVING'
                
                # PID Calculation
                correction = self.pid.compute(error, dt=0.05)
                
                current_base_speed = self.base_speed 
                
                left_speed = max(-255, min(255, int(current_base_speed - correction)))
                right_speed = max(-255, min(255, int(current_base_speed + correction)))
                
                self.robot.driver.set_motors(left_speed, right_speed)
                time.sleep(0.03)
                
            except Exception as e:
                logger.error(f"Auto loop error: {e}")
                self.robot.driver.stop()
        
        self.robot.driver.stop()
        logger.info("Auto loop ended")