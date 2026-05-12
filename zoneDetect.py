import sys
import cv2
import time
import os
import json
import numpy as np
from pythonosc import udp_client

VERSION = "2026.05.12"

DEFAULT_CONFIG = {
    "camera_index": 0,
    "roi": {"x": 200, "y": 150, "width": 200, "height": 200},
    "color_change_threshold": 2000,
    "base_colors_rgb": [[180, 100, 90], [130, 120, 80]],
    "color_similarity_threshold": 50,
    "global_change_percentage_threshold": 0.75,
    "red_duration_seconds": 1,
    "timerDuration": 2.0,
    "osc": {
        "ip": "127.0.0.1",
        "port": 5005,
        "address": "/motion"
    }
}

class ZoneDetector:
    def __init__(self):
        self.cwd = self._get_cwd()
        self.config_path = os.path.join(self.cwd, f"{os.path.splitext(os.path.basename(sys.argv[0]))[0]}.json")
        self.config = self.load_config()
        
        self.cap = None
        self.avg_frame = None
        self.last_detection_time = 0
        self.detect_movement = True
        self.osc_client = udp_client.SimpleUDPClient(self.config['osc']['ip'], self.config['osc']['port'])
        
        self.window_name = "zoneDetect - Premium Motion Control"
        cv2.namedWindow(self.window_name)

    def _get_cwd(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def load_config(self):
        if not os.path.exists(self.config_path):
            print(f"[*] Creating default config: {self.config_path}")
            with open(self.config_path, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            return DEFAULT_CONFIG
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=4)
        print(f"[*] Config saved to {self.config_path}")

    def init_camera(self):
        idx = self.config.get('camera_index', 0)
        print(f"[*] Opening camera {idx}...")
        self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            print(f"[!] Failed to open camera {idx}. Scanning for alternatives...")
            for i in range(5):
                if i == idx: continue
                self.cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if self.cap.isOpened():
                    print(f"[+] Found working camera at index {i}")
                    self.config['camera_index'] = i
                    self.save_config()
                    break
        return self.cap.isOpened()

    def select_roi(self, frame):
        print("[*] ROI Selection Mode. Draw a rectangle and press ENTER or SPACE. Press 'c' to cancel.")
        # We use a separate window name to avoid messing with the main HUD during selection
        selector_window = "ROI Selector - Draw and press ENTER"
        roi = cv2.selectROI(selector_window, frame, fromCenter=False, showCrosshair=True)
        if roi[2] > 0 and roi[3] > 0:
            self.config['roi'] = {"x": int(roi[0]), "y": int(roi[1]), "width": int(roi[2]), "height": int(roi[3])}
            self.save_config()
            self.avg_frame = None # Reset background model
            print("[+] ROI Updated.")
        
        try:
            cv2.destroyWindow(selector_window)
        except:
            pass

    def is_base_color(self, detected_bgr):
        similarity = self.config['color_similarity_threshold']
        for base_rgb in self.config['base_colors_rgb']:
            base_bgr = np.array(base_rgb[::-1], dtype=np.float64)
            if np.linalg.norm(np.array(detected_bgr) - base_bgr) < similarity:
                return True
        return False

    def add_base_color(self, roi_frame, mask):
        mean_color_bgr = cv2.mean(roi_frame, mask=mask)[:3]
        mean_color_rgb = [int(x) for x in mean_color_bgr[::-1]]
        self.config['base_colors_rgb'].append(mean_color_rgb)
        self.save_config()
        print(f"[+] Added base color to ignore: {mean_color_rgb}")

    def run(self):
        if not self.init_camera():
            print("[ERROR] No camera available. Exiting.")
            return

        print("[*] zoneDetect Running. Press 'R' for ROI, 'B' for Base Color, 'ESC' to Exit.")
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("[!] Lost frame. Retrying...")
                time.sleep(1)
                continue

            roi_cfg = self.config['roi']
            # Bounds check
            if frame.shape[0] < roi_cfg['y'] + roi_cfg['height'] or frame.shape[1] < roi_cfg['x'] + roi_cfg['width']:
                cv2.putText(frame, "ROI OUT OF BOUNDS - Press 'R'", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                roi_valid = False
            else:
                roi_valid = True

            motion_detected = False
            intensity = 0
            
            if roi_valid:
                roi = frame[roi_cfg['y']:roi_cfg['y'] + roi_cfg['height'], roi_cfg['x']:roi_cfg['x'] + roi_cfg['width']]
                gray_roi = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (21, 21), 0)

                if self.avg_frame is None or self.avg_frame.shape != gray_roi.shape:
                    self.avg_frame = gray_roi.copy().astype("float")
                    continue

                cv2.accumulateWeighted(gray_roi, self.avg_frame, 0.5)
                frame_delta = cv2.absdiff(gray_roi, cv2.convertScaleAbs(self.avg_frame))
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)
                
                changed_pixels = cv2.countNonZero(thresh)
                total_pixels = roi_cfg['width'] * roi_cfg['height']
                intensity = (changed_pixels / total_pixels)
                
                if changed_pixels > self.config['color_change_threshold']:
                    if intensity < self.config['global_change_percentage_threshold']:
                        mean_color = cv2.mean(roi, mask=thresh)[:3]
                        if not self.is_base_color(mean_color):
                            motion_detected = True

            # Logic for timing and OSC
            now = time.time()
            if motion_detected:
                self.last_detection_time = now
                if self.detect_movement:
                    self.osc_client.send_message(self.config['osc']['address'], 1)
                    print(f"[!] Motion Detected! Intensity: {intensity:.2%}")
                    self.detect_movement = False
            
            if now - self.last_detection_time > self.config['timerDuration']:
                if not self.detect_movement:
                    print("[*] Cooldown finished.")
                    self.detect_movement = True
            
            # --- HUD Rendering ---
            status_color = (0, 0, 255) if (now - self.last_detection_time < self.config['timerDuration']) else (0, 255, 0)
            cv2.rectangle(frame, (roi_cfg['x'], roi_cfg['y']), 
                         (roi_cfg['x'] + roi_cfg['width'], roi_cfg['y'] + roi_cfg['height']), status_color, 2)
            
            # Visual Intensity Bar
            bar_x = roi_cfg['x'] + roi_cfg['width'] + 10
            bar_h = roi_cfg['height']
            cv2.rectangle(frame, (bar_x, roi_cfg['y']), (bar_x + 15, roi_cfg['y'] + bar_h), (50, 50, 50), -1)
            intensity_h = int(min(1.0, intensity / (self.config['color_change_threshold'] / (roi_cfg['width'] * roi_cfg['height'] + 1) * 5)) * bar_h)
            cv2.rectangle(frame, (bar_x, roi_cfg['y'] + bar_h - intensity_h), (bar_x + 15, roi_cfg['y'] + bar_h), (255, 100, 0), -1)
            # Threshold marker on bar
            thresh_y = roi_cfg['y'] + bar_h - int((self.config['color_change_threshold'] / (roi_cfg['width'] * roi_cfg['height'] + 1) / ( (self.config['color_change_threshold'] / (roi_cfg['width'] * roi_cfg['height'] + 1) * 5) + 1e-6)) * bar_h)
            cv2.line(frame, (bar_x - 2, thresh_y), (bar_x + 17, thresh_y), (0, 255, 255), 2)

            # Text HUD
            y_off = 30
            hud_info = [
                (f"MODE: {'DETECTING' if self.detect_movement else 'COOLDOWN'}", status_color),
                (f"INTENSITY: {intensity:.2%}", (255, 255, 255)),
                (f"THRESHOLD: {self.config['color_change_threshold']} (+/- to adjust)", (0, 255, 255)),
                ("R: ROI | B: BASE COLOR | ESC: EXIT", (100, 255, 255))
            ]
            for text, color in hud_info:
                cv2.putText(frame, text, (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 3) # Outline
                cv2.putText(frame, text, (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
                y_off += 25

            cv2.imshow(self.window_name, frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == 27: # ESC
                break
            elif key == ord('r'):
                self.select_roi(frame)
            elif key == ord('b') and roi_valid:
                self.add_base_color(roi, thresh)
            elif key == ord('=') or key == ord('+'):
                self.config['color_change_threshold'] += 100
                self.save_config()
            elif key == ord('-') or key == ord('_'):
                self.config['color_change_threshold'] = max(100, self.config['color_change_threshold'] - 100)
                self.save_config()

        self.cap.release()
        cv2.destroyAllWindows()
        print("[*] Application closed.")

if __name__ == "__main__":
    detector = ZoneDetector()
    detector.run()
