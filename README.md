# CamHB

CamHB is an ultra lightweight Raspberry Pi security camera service for CSI ribbon cameras on the modern `Picamera2` / `libcamera` stack.

It avoids MotionEye, MMAL, V4L2 compatibility wrappers, Flask, OpenCV, and databases. One Python process owns the camera, runs a local web portal, shows a live low-resolution preview, detects motion from low-resolution frames, and writes high-resolution clips from a circular pre-roll buffer.

## What It Does

- Uses `Picamera2` directly, so it matches current Raspberry Pi OS camera architecture.
- Keeps one camera pipeline running for live preview, motion detection, and recording.
- Detects motion from low-resolution luma-frame differences.
- Shows a constant local preview from the same low-resolution motion frames.
- Records high-resolution MP4 clips during configured time windows.
- Includes roughly `pre_record_seconds` of footage before detected motion.
- Provides optional web pan controls for a GPIO stepper mount.
- Stores recordings by date under `recordings/`.
- Serves a local web portal for playback, deletion, and basic tuning.
- Prunes old footage by retention days and maximum storage size.

## Requirements

- Raspberry Pi OS with `rpicam-apps`, `python3-picamera2`, `python3-gpiozero`, and `python3-lgpio`.
- A working CSI ribbon camera verified with:

```bash
rpicam-hello
rpicam-still -o test.jpg
```

- Python 3. Use Raspberry Pi OS packages; do not install Picamera2 with `pip`.

CamHB records MP4 clips through Picamera2's circular output path. The high-resolution encoder stays warm so clips can include footage from just before motion was detected.

Raspberry Pi's Picamera2 circular output supports time-shifted recording to outputs such as MP4, which is the pattern CamHB now uses.

## Quick Start

```bash
cp config.example.json config.json
python3 camhb.py --config config.json
```

Open:

```text
http://<pi-ip-address>:8080/
```

The portal opens on the live feed. This preview is intentionally the low-resolution monitoring stream, so it is lightweight and does not start a second camera process. Recording no longer halts the live feed.

## Pan Control

The example config enables a small pan mount:

- Stepper driver IN1, IN2, IN3, and IN4 on GP18, GP23, GP24, and GP25.
- Stepper pan range defaults to -100 to +100 degrees around the position it is in when CamHB starts.

Open **Camera Control** in the web portal and enable **Control mode** before using the left/right arrow buttons or keyboard Left/Right keys. Holding an arrow button or key repeats movement until released. The **0** button returns to the startup-centered pan position. Control mode disarms motion recording while you move the camera and for `manual_control_settle_seconds` after you leave control mode, so manual movement does not create motion clips. Use the Settings panel's **Pan limit** field to adjust the symmetric left/right range while testing.

If the controls move the wrong way, flip `pan_invert` in `config.json`. If the portal says the motor is disabled in config, set `pan_enabled` to `true`. Older configs can also copy the `pan_enabled`, `stepper_*`, `pan_limit_degrees`, and `pan_step_degrees` fields from `config.example.json` when you want the values visible in the file.

## Install As A Service

Clone the project on the Pi:

```bash
CAMHB_USER="${SUDO_USER:-$USER}"
sudo apt update
sudo apt install -y git python3 python3-picamera2 python3-gpiozero python3-lgpio rpicam-apps
sudo usermod -aG video "$CAMHB_USER"
sudo install -d -o "$CAMHB_USER" -g video /opt/camhb /etc/camhb /var/lib/camhb/recordings
sudo -u "$CAMHB_USER" git clone https://github.com/SydFloyd/CamHB.git /opt/camhb
cp /opt/camhb/config.example.json /etc/camhb/config.json
sudo sed "s/^User=.*/User=$CAMHB_USER/" /opt/camhb/systemd/camhb.service | sudo tee /etc/systemd/system/camhb.service >/dev/null
sudo chown -R "$CAMHB_USER":video /etc/camhb /var/lib/camhb
```

Edit `/etc/camhb/config.json`, especially `host`, `port`, `data_dir`, and `active_windows`. For the systemd install, set:

```json
"data_dir": "/var/lib/camhb/recordings"
```

The install commands patch the service to run as your current Pi user. On your Pi that should be `admin`, not `pi`.

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now camhb
sudo journalctl -u camhb -f
```

## Update From Git

Pull updates on the Pi, then restart the service:

```bash
CAMHB_USER="${SUDO_USER:-$USER}"
sudo -u "$CAMHB_USER" git -C /opt/camhb pull --ff-only
sudo sed "s/^User=.*/User=$CAMHB_USER/" /opt/camhb/systemd/camhb.service | sudo tee /etc/systemd/system/camhb.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart camhb
sudo journalctl -u camhb -f
```

If you already installed the service and see `status=217/USER`, patch the installed unit in place:

```bash
CAMHB_USER="${SUDO_USER:-$USER}"
sudo usermod -aG video "$CAMHB_USER"
sudo sed -i "s/^User=.*/User=$CAMHB_USER/" /etc/systemd/system/camhb.service
sudo chown -R "$CAMHB_USER":video /etc/camhb /var/lib/camhb
sudo systemctl daemon-reload
sudo systemctl restart camhb
sudo journalctl -u camhb -f
```

## Troubleshooting

If the log shows `Pipeline handler in use by another process`, stop any other camera command and restart CamHB:

```bash
sudo systemctl stop camhb
pkill -f rpicam || true
pkill -f libcamera || true
sudo systemctl restart camhb
sudo journalctl -u camhb -f
```

That error means libcamera thinks another process still owns the CSI camera. CamHB itself now uses a single long-running camera pipeline, so the usual cause is a separate command still running in another shell.

## Schedule Format

`active_windows` is a list. Empty means always armed.

Days use Python weekday numbers:

- `0` Monday
- `1` Tuesday
- `2` Wednesday
- `3` Thursday
- `4` Friday
- `5` Saturday
- `6` Sunday

Example, every night from 8 PM to 6 AM:

```json
[
  {
    "start": "20:00",
    "end": "06:00",
    "days": [0, 1, 2, 3, 4, 5, 6]
  }
]
```

## Motion Tuning

Start with the defaults. If you get too many clips:

- Increase `motion_threshold` from `18` to `24`.
- Increase `motion_ratio` from `0.025` to `0.04`.
- Lower `monitor_fps` to reduce sensitivity and CPU.

If motion is missed:

- Decrease `motion_threshold` toward `12`.
- Decrease `motion_ratio` toward `0.01`.
- Increase `monitor_fps` to `5` or `6`.

The detector intentionally favors simple frame-difference logic. It is lightweight and transparent, but it will still react to lighting changes, shadows, rain, headlights, and camera shake.

The live feed uses the same monitoring settings. Increase `monitor_fps` for smoother preview, or lower it to reduce CPU and network use.

`pre_record_seconds` controls how much footage before motion is included in each clip. The default is `1`, which keeps storage use low while catching the beginning of movement.

## Security

This is intended for a trusted local network. Do not expose it directly to the internet.

For basic protection, set `access_token` in the config and open the portal with:

```text
http://<pi-ip-address>:8080/?token=<your-token>
```

## Expected Reliability Versus MotionEye

For your specific problem, the expected camera-connection reliability should be better than MotionEye because CamHB talks to the modern Picamera2/libcamera stack directly instead of asking MotionEye/Motion to enumerate the CSI camera through older MMAL/V4L2 expectations.

Overall maturity is lower. MotionEye is a full surveillance product with years of field use, more camera types, more UI features, and more edge-case handling. CamHB is intentionally tiny and should be easier to reason about, but it will need tuning in your physical scene.

My practical rating:

- Camera stack compatibility on modern Raspberry Pi OS: CamHB 8/10, MotionEye 4-6/10 for CSI cameras without wrappers.
- Motion detection sophistication: CamHB 5/10, MotionEye 7/10.
- Operational simplicity: CamHB 8/10, MotionEye 6/10.
- Feature completeness: CamHB 4/10, MotionEye 8/10.
- Expected reliability for a single OV5647 Pi CSI camera on Bookworm/Trixie: CamHB 7/10 after tuning, MotionEye 5/10 unless the compatibility layer is stable on that exact install.

If you only need timed motion clips and local review/delete, CamHB is likely the more dependable path for this Pi. If you need multi-camera dashboards, masks, notifications, streaming modes, or mature event logic, MotionEye still has the deeper feature set when it can actually see the camera.
