"""
Lane Detection Module (UPDATED for Picamera2)
Detects lane-like lines and calculates midline for following
Now supports BGR input from Picamera2
"""

import cv2
import numpy as np


def detect_line(frame, config=None):
    """
    Detect lane lines and calculate midline position
    
    Args:
        frame: Input image (BGR format from Picamera2)
        config: Optional configuration dictionary
    
    Returns:
        tuple: (error, x_line, center_x, frame_debug)
    """
    # Default configuration
    if config is None:
        config = {
            'roi_top_ratio': 0.5,      # Start ROI at 50% from top
            'roi_bottom_ratio': 1.0,    # End ROI at bottom
            'canny_low': 50,
            'canny_high': 150,
            'hough_threshold': 30,
            'min_line_length': 40,
            'max_line_gap': 100,
            'blur_kernel': 5,
        }
    
    # Get frame dimensions
    height, width = frame.shape[:2]
    center_x = width // 2
    
    # Create debug frame (copy original)
    frame_debug = frame.copy()
    
    # Draw center line
    cv2.line(frame_debug, (center_x, 0), (center_x, height), (0, 255, 255), 2)
    
    # ===== PREPROCESSING =====
    
    # Convert to grayscale (Input is BGR)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # <--- ĐÃ SỬA
    
    # Apply Gaussian blur to reduce noise
    blur = cv2.GaussianBlur(gray, (config['blur_kernel'], config['blur_kernel']), 0)
    
    # Canny edge detection
    edges = cv2.Canny(blur, config['canny_low'], config['canny_high'])
    
    # ===== REGION OF INTEREST (ROI) =====
    
    # Define ROI vertices (trapezoid shape for road/lane)
    roi_top = int(height * config['roi_top_ratio'])
    roi_bottom = int(height * config['roi_bottom_ratio'])
    
    roi_vertices = np.array([[
        (0, roi_bottom),
        (int(width * 0.3), roi_top),
        (int(width * 0.7), roi_top),
        (width, roi_bottom)
    ]], dtype=np.int32)
    
    # Create mask
    mask = np.zeros_like(edges)
    cv2.fillPoly(mask, roi_vertices, 255)
    
    # Apply mask
    masked_edges = cv2.bitwise_and(edges, mask)
    
    # Draw ROI on debug frame
    cv2.polylines(frame_debug, roi_vertices, True, (255, 0, 0), 2)
    
    # ===== HOUGH LINE DETECTION =====
    
    lines = cv2.HoughLinesP(
        masked_edges,
        rho=1,
        theta=np.pi / 180,
        threshold=config['hough_threshold'],
        minLineLength=config['min_line_length'],
        maxLineGap=config['max_line_gap']
    )
    
    # Check if any lines detected
    if lines is None or len(lines) == 0:
        return 0, center_x, center_x, frame_debug
    
    # ===== SEPARATE LEFT AND RIGHT LANES =====
    
    left_lines = []
    right_lines = []
    
    for line in lines:
        x1, y1, x2, y2 = line[0]
        
        # Calculate slope
        if x2 - x1 == 0:  # Vertical line
            continue
        
        slope = (y2 - y1) / (x2 - x1)
        
        # Filter by slope (avoid horizontal lines)
        if abs(slope) < 0.3:
            continue
        
        # Classify as left or right based on position and slope
        line_center_x = (x1 + x2) / 2
        
        if line_center_x < center_x and slope < 0:
            left_lines.append((x1, y1, x2, y2, slope))
        elif line_center_x > center_x and slope > 0:
            right_lines.append((x1, y1, x2, y2, slope))
    
    # ===== CALCULATE LANE BOUNDARIES =====
    
    left_lane_x = None
    right_lane_x = None
    
    # Calculate left lane position
    if left_lines:
        slopes = [line[4] for line in left_lines]
        points = [(line[0], line[1]) for line in left_lines]
        
        avg_slope = np.mean(slopes)
        avg_x = np.mean([p[0] for p in points])
        avg_y = np.mean([p[1] for p in points])
        
        b = avg_y - avg_slope * avg_x
        left_lane_x = int((roi_bottom - b) / avg_slope) if avg_slope != 0 else int(avg_x)
        
        y1 = roi_top
        x1 = int((y1 - b) / avg_slope) if avg_slope != 0 else int(avg_x)
        cv2.line(frame_debug, (x1, y1), (left_lane_x, roi_bottom), (0, 255, 0), 3)
    
    # Calculate right lane position
    if right_lines:
        slopes = [line[4] for line in right_lines]
        points = [(line[0], line[1]) for line in right_lines]
        
        avg_slope = np.mean(slopes)
        avg_x = np.mean([p[0] for p in points])
        avg_y = np.mean([p[1] for p in points])
        
        b = avg_y - avg_slope * avg_x
        right_lane_x = int((roi_bottom - b) / avg_slope) if avg_slope != 0 else int(avg_x)
        
        y1 = roi_top
        x1 = int((y1 - b) / avg_slope) if avg_slope != 0 else int(avg_x)
        cv2.line(frame_debug, (x1, y1), (right_lane_x, roi_bottom), (0, 255, 0), 3)
    
    # ===== CALCULATE MIDLINE =====
    
    if left_lane_x is not None and right_lane_x is not None:
        x_line = (left_lane_x + right_lane_x) // 2
        cv2.line(frame_debug, (x_line, roi_top), (x_line, roi_bottom), (255, 0, 255), 3)
        cv2.circle(frame_debug, (left_lane_x, roi_bottom), 8, (0, 255, 0), -1)
        cv2.circle(frame_debug, (right_lane_x, roi_bottom), 8, (0, 255, 0), -1)
        
    elif left_lane_x is not None:
        estimated_lane_width = 200
        x_line = left_lane_x + estimated_lane_width // 2
        cv2.line(frame_debug, (x_line, roi_top), (x_line, roi_bottom), (255, 165, 0), 3)
        cv2.putText(frame_debug, "LEFT ONLY", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)
        
    elif right_lane_x is not None:
        estimated_lane_width = 200
        x_line = right_lane_x - estimated_lane_width // 2
        cv2.line(frame_debug, (x_line, roi_top), (x_line, roi_bottom), (255, 165, 0), 3)
        cv2.putText(frame_debug, "RIGHT ONLY", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)
    else:
        x_line = center_x
        cv2.putText(frame_debug, "NO LANE DETECTED", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    # ===== CALCULATE ERROR =====
    
    error = center_x - x_line
    
    cv2.arrowedLine(frame_debug, (center_x, height - 50), 
                   (x_line, height - 50), (0, 0, 255), 3, tipLength=0.3)
    
    error_text = f"Error: {error:+d} px"
    cv2.putText(frame_debug, error_text, (10, height - 20), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    return error, x_line, center_x, frame_debug


def detect_line_simple(frame):
    """
    Simplified lane detection using color thresholding
    Args:
        frame: BGR format from Picamera2
    """
    height, width = frame.shape[:2]
    center_x = width // 2
    
    frame_debug = frame.copy()
    
    # Convert to HSV (Input is BGR)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV) # <--- ĐÃ SỬA
    
    # Detect white/yellow lines
    lower_white = np.array([0, 0, 200])
    upper_white = np.array([180, 30, 255])
    
    mask_white = cv2.inRange(hsv, lower_white, upper_white)
    
    # ROI
    roi_top = height // 2
    mask_white[:roi_top, :] = 0
    
    contours, _ = cv2.findContours(mask_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest_contour)
        if M['m00'] > 0:
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
            x_line = cx
            cv2.drawContours(frame_debug, [largest_contour], -1, (0, 255, 0), 2)
            cv2.circle(frame_debug, (cx, cy), 10, (255, 0, 255), -1)
        else:
            x_line = center_x
    else:
        x_line = center_x
    
    error = center_x - x_line
    cv2.line(frame_debug, (center_x, 0), (center_x, height), (0, 255, 255), 2)
    cv2.arrowedLine(frame_debug, (center_x, height - 50), (x_line, height - 50), (0, 0, 255), 3)
    cv2.putText(frame_debug, f"Error: {error:+d}", (10, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    return error, x_line, center_x, frame_debug