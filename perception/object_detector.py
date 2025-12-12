from ultralytics import YOLO
import logging
import os
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class ObjectDetector:
    def __init__(self, model_path='data/models/best.onnx', conf_threshold=0.5):
        self.model = None
        self.conf_threshold = conf_threshold
        
        if os.path.exists(model_path):
            try:
                logger.info(f"Loading ONNX model from {model_path}...")
                # task='detect' để tránh cảnh báo
                self.model = YOLO(model_path, task='detect')
                logger.info("Model loaded successfully!")
                logger.info(f"Classes: {self.model.names}")
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
        else:
            logger.error(f"Model not found at {model_path}")

    def detect(self, frame):
        """
        Nhận diện vật thể
        Args:
            frame: Ảnh đầu vào từ Camera (Đang là RGB từ Picamera2)
        """
        if self.model is None or frame is None:
            # Nếu frame lỗi, trả về nguyên vẹn (nhưng cần chuyển BGR để web không lỗi màu)
            if frame is not None:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return [], frame

        # 1. Đưa vào AI (YOLO)
        # Vì Camera đang gửi RGB, và YOLO cũng cần RGB, nên ta ĐƯA THẲNG VÀO.
        # KHÔNG dùng cvtColor ở đây nữa.
        results = self.model(frame, imgsz=320, conf=self.conf_threshold, verbose=False)
        
        # 2. Vẽ khung hình
        # plot() trả về ảnh RGB
        annotated_frame_rgb = results[0].plot()
        
        # 3. Chuyển sang BGR để hiển thị trên Web/OpenCV
        # Đây là bước quan trọng để màu trên web không bị sai
        annotated_frame_bgr = cv2.cvtColor(annotated_frame_rgb, cv2.COLOR_RGB2BGR)
        
        # 4. Trích xuất thông tin
        detections = []
        for box in results[0].boxes:
            x, y, w, h = box.xywh[0].tolist()
            cls_id = int(box.cls[0])
            detections.append({
                'class_name': self.model.names[cls_id],
                'conf': float(box.conf[0]),
                'x': x, 'y': y, 'w': w, 'h': h
            })
            
        return detections, annotated_frame_bgr