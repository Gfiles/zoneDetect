import sys
import cv2
import time
import os
import json
import numpy as np
import threading
from pythonosc import udp_client
from PIL import Image
import pystray
from pystray import MenuItem as item

import _version
VERSION = _version.VERSION

LEARNING_PHASE_FRAMES = 60  # Frames for fast baseline learning on startup/ROI reset (~2s at 30fps)

DEFAULT_CONFIG = {
    "camera_index": 0,
    "roi": {"x": 200, "y": 150, "width": 200, "height": 200},
    "color_change_threshold": 2000,
    "base_colors_rgb": [[180, 100, 90], [130, 120, 80]],
    "color_similarity_threshold": 50,
    "global_change_percentage_threshold": 0.75,
    "red_duration_seconds": 1,
    "timerDuration": 2.0,
    "background_learning_alpha": 0.02,
    "osc": {
        "ip": "127.0.0.1",
        "port": 5005,
        "address": "/motion"
    },
    "show_hud": True
}

class ZoneDetector:
    def __init__(self, headless=False):
        self.headless = headless
        self.cwd = self._get_cwd()
        self.config_path = os.path.join(self.cwd, f"{os.path.splitext(os.path.basename(sys.argv[0]))[0]}.json")
        self.config = self.load_config()
        
        self.cap = None
        self.avg_frame = None
        self.last_detection_time = 0
        self.detect_movement = True
        
        try:
            self.osc_client = udp_client.SimpleUDPClient(self.config['osc']['ip'], self.config['osc']['port'])
        except Exception as e:
            print(f"[!] Failed to initialize OSC client: {e}")
            self.osc_client = None
        
        self.window_name = "zoneDetect - Premium Motion Control"
        # Window will be created dynamically based on HUD visibility

        # Background model learning state
        self.learning_phase = True
        self.learning_frame_count = 0

        # Performance and state tracking
        self.last_save_time = time.time()
        self.config_dirty = False
        self.fps_start_time = time.time()
        self.fps_counter = 0
        self.current_fps = 0
        
        # System Tray & Background State
        self.exit_event = threading.Event()
        self.show_hud = self.config.get('show_hud', True) if not headless else False
        self.tray_icon = None
        
        if not headless:
            self._start_tray()

    def _start_tray(self):
        icon_path = os.path.join(self.cwd, "icon.ico")
        if os.path.exists(icon_path):
            icon_img = Image.open(icon_path)
        else:
            # Fallback to a simple colored square if no icon exists
            icon_img = Image.new('RGB', (64, 64), color=(0, 255, 0))
            
        menu = (
            item('Show HUD', self._menu_show_hud),
            item('Hide HUD', self._menu_hide_hud),
            item('Exit', self._menu_exit)
        )
        self.tray_icon = pystray.Icon("zoneDetect", icon_img, "zoneDetect", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _menu_show_hud(self):
        self.show_hud = True
        self.config['show_hud'] = True
        self.config_dirty = True
        print("[*] HUD Enabled")

    def _menu_hide_hud(self):
        self.show_hud = False
        self.config['show_hud'] = False
        self.config_dirty = True
        print("[*] HUD Disabled")

    def _menu_exit(self):
        print("[*] Exiting from Tray...")
        self.exit_event.set()
        if self.tray_icon:
            self.tray_icon.stop()

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

    def save_config(self, force=False):
        if self.config_dirty or force:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.config_dirty = False
            print(f"[*] Config synchronized to {self.config_path}")

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
                    self.config_dirty = True
                    break
        return self.cap.isOpened()

    def select_roi(self, frame):
        print("[*] ROI Selection Mode. Draw a rectangle and press ENTER or SPACE. Press 'c' to cancel.")
        selector_window = "ROI Selector - Draw and press ENTER"
        roi = cv2.selectROI(selector_window, frame, fromCenter=False, showCrosshair=True)
        if roi[2] > 0 and roi[3] > 0:
            self.config['roi'] = {"x": int(roi[0]), "y": int(roi[1]), "width": int(roi[2]), "height": int(roi[3])}
            self.config_dirty = True
            self.avg_frame = None  # Reset background model
            self.learning_phase = True  # Re-establish baseline for new ROI
            self.learning_frame_count = 0
            print("[+] ROI Updated. Re-learning background...")
        
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
        self.config_dirty = True
        print(f"[+] Added base color to ignore: {mean_color_rgb}")

    def run(self):
        if not self.init_camera():
            print("[ERROR] No camera available. Exiting.")
            return

        print("[*] zoneDetect Running. Tray Icon active. Keys: R:ROI, B:Base, +/-:Thresh, []:Timer, ESC:Exit")
        
        last_hud_state = self.show_hud
        try:
            while not self.exit_event.is_set():
                # Handle HUD visibility changes on the MAIN thread
                if self.show_hud != last_hud_state:
                    if not self.show_hud:
                        cv2.destroyAllWindows()
                    last_hud_state = self.show_hud

                ret, frame = self.cap.read()
                if not ret:
                    print("[!] Lost frame. Retrying...")
                    time.sleep(1)
                    continue

                # FPS Calculation
                self.fps_counter += 1
                if time.time() - self.fps_start_time > 1.0:
                    self.current_fps = self.fps_counter
                    self.fps_counter = 0
                    self.fps_start_time = time.time()

                roi_cfg = self.config['roi']
                if frame.shape[0] < roi_cfg['y'] + roi_cfg['height'] or frame.shape[1] < roi_cfg['x'] + roi_cfg['width']:
                    if self.show_hud:
                        cv2.putText(frame, "ROI OUT OF BOUNDS - Press 'R'", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    roi_valid = False
                else:
                    roi_valid = True

                motion_detected = False
                intensity = 0
                thresh_img = None

                if roi_valid:
                    roi = frame[roi_cfg['y']:roi_cfg['y'] + roi_cfg['height'], roi_cfg['x']:roi_cfg['x'] + roi_cfg['width']]
                    gray_roi = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (21, 21), 0)

                    if self.avg_frame is None or self.avg_frame.shape != gray_roi.shape:
                        self.avg_frame = gray_roi.copy().astype("float")
                        self.learning_phase = True
                        self.learning_frame_count = 0
                        continue

                    in_cooldown = (time.time() - self.last_detection_time) < self.config['timerDuration']

                    if self.learning_phase:
                        # Phase 1: Fast absorption to build baseline from a cold start or ROI change
                        cv2.accumulateWeighted(gray_roi, self.avg_frame, 0.5)
                        self.learning_frame_count += 1
                        if self.learning_frame_count >= LEARNING_PHASE_FRAMES:
                            self.learning_phase = False
                            print("[+] Background model established. Entering detection mode.")
                    else:
                        # Phase 2: Production mode
                        # - Freeze model while cooldown is active (preserve pre-motion baseline)
                        # - Slowly adapt when scene is settled (handles long-term lighting drift)
                        if not in_cooldown:
                            alpha = self.config.get('background_learning_alpha', 0.02)
                            cv2.accumulateWeighted(gray_roi, self.avg_frame, alpha)

                        # Run detection against the stable background
                        frame_delta = cv2.absdiff(gray_roi, cv2.convertScaleAbs(self.avg_frame))
                        thresh_img = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                        thresh_img = cv2.dilate(thresh_img, None, iterations=2)

                        changed_pixels = cv2.countNonZero(thresh_img)
                        total_pixels = roi_cfg['width'] * roi_cfg['height']
                        intensity = (changed_pixels / total_pixels)

                        if changed_pixels > self.config['color_change_threshold']:
                            if intensity < self.config['global_change_percentage_threshold']:
                                mean_color = cv2.mean(roi, mask=thresh_img)[:3]
                                if not self.is_base_color(mean_color):
                                    motion_detected = True

                now = time.time()
                if motion_detected:
                    self.last_detection_time = now
                    if self.detect_movement:
                        if self.osc_client:
                            try:
                                self.osc_client.send_message(self.config['osc']['address'], 1)
                            except Exception as e:
                                print(f"[!] OSC Send Error: {e}")
                        
                        print(f"[!] Motion Detected! Intensity: {intensity:.2%}")
                        self.detect_movement = False
                
                if now - self.last_detection_time > self.config['timerDuration']:
                    if not self.detect_movement:
                        print("[*] Cooldown finished.")
                        self.detect_movement = True

                # Periodic Auto-save (every 30s)
                if now - self.last_save_time > 30.0:
                    if self.config_dirty:
                        self.save_config()
                    self.last_save_time = now
                
                # --- HUD Rendering ---
                if self.show_hud:
                    if self.learning_phase:
                        mode_label, mode_color = "LEARNING", (0, 165, 255)
                    elif not self.detect_movement:
                        mode_label, mode_color = "COOLDOWN", (0, 0, 255)
                    else:
                        mode_label, mode_color = "DETECTING", (0, 255, 0)
                    status_color = mode_color

                    cv2.rectangle(frame, (roi_cfg['x'], roi_cfg['y']),
                                 (roi_cfg['x'] + roi_cfg['width'], roi_cfg['y'] + roi_cfg['height']), status_color, 2)

                    # Visual Intensity Bar
                    bar_x = roi_cfg['x'] + roi_cfg['width'] + 10
                    bar_h = roi_cfg['height']
                    total_px = roi_cfg['width'] * roi_cfg['height']
                    thresh_ratio = self.config['color_change_threshold'] / max(total_px, 1)
                    cv2.rectangle(frame, (bar_x, roi_cfg['y']), (bar_x + 15, roi_cfg['y'] + bar_h), (50, 50, 50), -1)
                    intensity_h = int(min(1.0, intensity) * bar_h)
                    cv2.rectangle(frame, (bar_x, roi_cfg['y'] + bar_h - intensity_h), (bar_x + 15, roi_cfg['y'] + bar_h), (255, 100, 0), -1)
                    thresh_y = roi_cfg['y'] + bar_h - int(min(1.0, thresh_ratio) * bar_h)
                    cv2.line(frame, (bar_x - 2, thresh_y), (bar_x + 17, thresh_y), (0, 255, 255), 2)

                    # Text HUD
                    y_off = 30
                    alpha_val = self.config.get('background_learning_alpha', 0.02)
                    hud_info = [
                        (f"MODE: {mode_label}", mode_color),
                        (f"INTENSITY: {intensity:.2%}", (255, 255, 255)),
                        (f"THRESH: {self.config['color_change_threshold']} (+/-)", (0, 255, 255)),
                        (f"TIMER: {self.config['timerDuration']:.1f}s ([/])", (255, 150, 0)),
                        (f"ALPHA: {alpha_val:.3f} (A/Z)", (180, 100, 255)),
                        (f"PERF: {self.current_fps} FPS", (200, 200, 200)),
                        ("R:ROI B:BASE +/-:THRESH []:TIMER A/Z:ALPHA ESC:EXIT", (100, 255, 255))
                    ]
                    for text, color in hud_info:
                        cv2.putText(frame, text, (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 3)
                        cv2.putText(frame, text, (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
                        y_off += 25

                    cv2.imshow(self.window_name, frame)
                
                # Always pump events to prevent "Not Responding" ghosting
                key = cv2.waitKey(1) & 0xFF
                
                if self.show_hud:
                    if key == 27: # ESC
                        self._menu_exit()
                    elif key == ord('r'):
                        self.select_roi(frame)
                    elif key == ord('b') and roi_valid and thresh_img is not None:
                        self.add_base_color(roi, thresh_img)
                    elif key == ord('=') or key == ord('+'):
                        self.config['color_change_threshold'] += 100
                        self.config_dirty = True
                    elif key == ord('-') or key == ord('_'):
                        self.config['color_change_threshold'] = max(100, self.config['color_change_threshold'] - 100)
                        self.config_dirty = True
                    elif key == ord(']'):
                        self.config['timerDuration'] += 0.5
                        self.config_dirty = True
                    elif key == ord('['):
                        self.config['timerDuration'] = max(0.5, self.config['timerDuration'] - 0.5)
                        self.config_dirty = True
                    elif key == ord('a'):
                        cur = self.config.get('background_learning_alpha', 0.02)
                        self.config['background_learning_alpha'] = min(0.5, round(cur + 0.005, 3))
                        self.config_dirty = True
                    elif key == ord('z'):
                        cur = self.config.get('background_learning_alpha', 0.02)
                        self.config['background_learning_alpha'] = max(0.001, round(cur - 0.005, 3))
                        self.config_dirty = True
                else:
                    time.sleep(0.01)
        finally:
            self.save_config(force=True)
            if self.cap:
                self.cap.release()
            cv2.destroyAllWindows()
            if self.tray_icon:
                self.tray_icon.stop()
            print("[*] Application closed.")


if __name__ == "__main__":
    detector = ZoneDetector()
    detector.run()
