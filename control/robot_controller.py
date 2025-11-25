"""
Robot Controller - Lite Version
Features: Auto Mode with Lane Following, Sign Recognition & Obstacle Avoidance
"""

import threading
import time
import logging
from perception.lane_detector import detect_line
from perception.camera_manager import get_web_camera
from perception.object_detector import ObjectDetector
from control.pid_controller import PIDController

logger = logging.getLogger(__name__)

class RobotController:
    def __init__(self, motor_driver, config: dict):
        self.driver = motor_driver
        self.config = config
        self.is_running = False
        self.thread = None
        
        # 1. Cấu hình An Toàn (Ultrasonic)
        safety_cfg = config.get('safety', {})
        self.SAFE_DISTANCE = safety_cfg.get('min_safe_distance', 25.0) # 25cm để kịp né
        self.is_avoiding = False # Cờ trạng thái né tránh
        
        # 2. AI & PID
        self.detector = ObjectDetector(model_path='data/models/best_ncnn_model', conf_threshold=0.5)
        
        pid_cfg = config.get('lane_following', {}).get('pid', {})
        self.pid = PIDController(
            kp=pid_cfg.get('kp', 0.8), ki=pid_cfg.get('ki', 0.0), kd=pid_cfg.get('kd', 0.3),
            output_min=-255, output_max=255
        )
        
        # 3. Cài đặt Tốc độ
        lane_cfg = config.get('lane_following', {})
        self.base_speed = lane_cfg.get('base_speed', 150)
        self.default_speed = self.base_speed
        self.detection_config = config.get('ai', {}).get('lane_detection', {})
        
        # 4. Khoảng cách Biển báo (Pixel)
        self.DIST_PREPARE = 140
        self.DIST_EXECUTE = 170
        
        # Camera (Singleton)
        self.camera = None

    def start(self):
        if not self.is_running:
            self.camera = get_web_camera(self.config)
            if not self.camera.is_running(): self.camera.start()
            
            self.is_running = True
            self.base_speed = self.default_speed
            self.pid.reset()
            self.is_avoiding = False
            
            self.thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.thread.start()
            logger.info(f"Auto Mode Started (Safe Dist: {self.SAFE_DISTANCE}cm)")

    def stop(self):
        self.is_running = False
        if self.thread: self.thread.join(timeout=1.0)
        self.driver.stop()
        logger.info("Auto Mode Stopped")

    def cleanup(self):
        self.stop()
        self.driver.cleanup()

    def perform_avoidance_maneuver(self):
        """
        Kịch bản né vật cản: Dừng -> Lùi -> Rẽ Trái -> Vượt -> Về Làn
        """
        logger.warning(">>> STARTING AVOIDANCE MANEUVER <<<")
        self.is_avoiding = True
        
        # 1. Dừng khẩn cấp
        self.driver.stop()
        time.sleep(0.5)
        
        # 2. Lùi lại (để có không gian đánh lái)
        logger.info("Avoid: Reversing...")
        self.driver.backward(130)
        time.sleep(0.8)
        
        # 3. Rẽ Trái (Né)
        logger.info("Avoid: Turning Left...")
        self.driver.turn_left(180)
        time.sleep(0.6)
        
        # 4. Đi Thẳng (Vượt qua vật cản)
        logger.info("Avoid: Passing...")
        self.driver.forward(150)
        time.sleep(1.2)
        
        # 5. Rẽ Phải (Quay về làn)
        logger.info("Avoid: Returning to lane...")
        self.driver.turn_right(180)
        time.sleep(0.5)
        
        # 6. Ổn định
        self.driver.stop()
        time.sleep(0.2)
        
        self.is_avoiding = False
        self.pid.reset() # Reset PID để tránh bị giật khi bắt lại làn
        logger.warning(">>> AVOIDANCE COMPLETE <<<")

    def _auto_loop(self):
        prev_time = time.time()
        
        while self.is_running:
            try:
                # --- 0. KIỂM TRA VẬT CẢN (Ưu tiên số 1) ---
                distance = self.driver.get_distance()
                
                if 0 < distance < self.SAFE_DISTANCE and not self.is_avoiding:
                    logger.warning(f"OBSTACLE DETECTED: {distance}cm")
                    # Thực hiện né tránh (Hàm này sẽ chặn luồng trong vài giây)
                    self.perform_avoidance_maneuver()
                    continue
                # ------------------------------------------

                # 1. Lấy ảnh Camera
                frame = self.camera.capture_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue

                # 2. Nhận diện Biển Báo
                detections, _ = self.detector.detect(frame)
                sign_action = None
                
                if detections:
                    sign = max(detections, key=lambda x: x['w'] * x['h'])
                    name = sign['class_name']
                    size = max(sign['w'], sign['h'])
                    
                    # Logic khoảng cách biển báo
                    if self.DIST_PREPARE <= size <= self.DIST_EXECUTE:
                        logger.info(f"Action for: {name}")
                        
                        if name in ['stop_sign', 'red_light']:
                            self.driver.stop()
                            sign_action = "STOP"
                            time.sleep(0.1)
                            
                        elif name == 'left_turn_sign':
                            self.driver.turn_left(150)
                            sign_action = "TURN"
                            time.sleep(1.5)
                            
                        elif name == 'right_turn_sign':
                            self.driver.turn_right(150)
                            sign_action = "TURN"
                            time.sleep(1.5)
                        
                        elif name == 'speed_limit_signs':
                            self.base_speed = 100
                            
                        elif name == 'green_light':
                            self.base_speed = self.default_speed

                if sign_action: continue

                # 3. Chạy theo làn (Lane Following)
                error, _, _, _ = detect_line(frame, self.detection_config)
                
                # Kiểm tra mất làn
                if abs(error) > frame.shape[1] * 0.4:
                     pass 
                
                # PID
                cur_time = time.time()
                dt = cur_time - prev_time
                prev_time = cur_time
                
                correction = self.pid.compute(error, dt)
                
                left = max(-255, min(255, int(self.base_speed - correction)))
                right = max(-255, min(255, int(self.base_speed + correction)))
                
                self.driver.set_motors(left, right)
                time.sleep(0.03)

            except Exception as e:
                logger.error(f"Loop error: {e}")
                self.driver.stop()
                break
        
        self.driver.stop()