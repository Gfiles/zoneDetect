# zoneDetect - Premium Motion Control 🚀

`zoneDetect` is a high-performance, background-oriented motion detection utility designed for triggering automation via OSC (Open Sound Control). It features a professional-grade detection algorithm that adapts to lighting changes while remaining resilient to background noise.

![zoneDetect HUD Example](https://via.placeholder.com/800x450.png?text=zoneDetect+HUD+Interface) *(Add a screenshot of the HUD here for maximum impact!)*

## ✨ Key Features

- **Advanced Motion Algorithm**: Uses a two-phase background model (fast-learning on startup, slow-adaptation during operation) with background freezing during cooldown events.
- **Visual HUD**: Real-time intensity monitoring with a calibrated threshold line and state indicators.
- **OSC Integration**: Sends triggers to any OSC-compatible software (e.g., QLab, Resolume, TouchDesigner, Home Assistant).
- **System Tray Operation**: Run the application entirely in the background. Toggle the HUD visibility whenever needed via the tray icon.
- **Live Calibration**: Adjust sensitivity (`+/-`), cooldown timer (`[`/`]`), and adaptation rate (`A`/`Z`) in real-time.
- **Smart Color Filtering**: Define "Base Colors" to ignore specific recurring movements (like a swinging light or moving shadow).
- **Persistent Settings**: All configurations are saved automatically to `zoneDetect.json`.

## 🛠 Installation

### Option 1: Run from Source (Recommended for Developers)

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd zoneDetect
   ```

2. **Install Dependencies**:
   It is recommended to use a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
   *Note: If requirements.txt is missing, install manually:*
   `pip install opencv-python numpy pystray python-osc Pillow`

3. **Run the Application**:
   ```bash
   python zoneDetect.py
   ```

### Option 2: Build Executable (.exe)

**Ensure you have run `pip install pyinstaller` first, if needed.**

Use the provided build script to create a standalone Windows executable:
```bash
python build.py
```
The compiled executable will be located in the `dist/` folder.

## 🚀 How to Use

1. **Start the App**: Launch `zoneDetect.exe` or `python zoneDetect.py`.
2. **Define Zone (ROI)**: Press **`R`** to open the ROI Selector. Draw a rectangle over the area you want to monitor and press **ENTER**.
3. **Calibrate Sensitivity**:
   - Use **`+`** / **`-`** to adjust the threshold. The yellow line on the HUD intensity bar represents your trigger point.
   - Use **`[`** / **`]`** to set the cooldown timer (how long the system waits before sending the next trigger).
4. **Ignore Background (Base Colors)**: If there is a static object or minor movement you want to ignore, move it into the ROI and press **`B`**. The average color will be added to the exclusion list.
5. **Background Mode**: Right-click the green square in your System Tray and select **Hide HUD** to let the app run silently in the background.

## ⌨️ Keybindings (When HUD is Visible)

| Key | Action |
| :--- | :--- |
| **`R`** | Re-define Region of Interest (ROI) |
| **`B`** | Add current ROI color to ignore list (Base Color) |
| **`+` / `-`** | Increase / Decrease sensitivity threshold |
| **`[` / `]`** | Increase / Decrease cooldown timer duration |
| **`A` / `Z`** | Increase / Decrease background adaptation rate (Alpha) |
| **`ESC`** | Exit Application |

## ⚙️ Configuration (`zoneDetect.json`)

The configuration file is generated automatically on the first run. You can manually edit it to change the OSC IP/Port or startup behavior:

- `"show_hud"`: Set to `false` to start the app hidden in the tray by default.
- `"osc"`: Configure the `ip`, `port`, and `address`.

---
*Developed with Passion for Performance.*
