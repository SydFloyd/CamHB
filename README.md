# CamHB

CamHB is an ultra lightweight Raspberry Pi security camera service for CSI ribbon cameras on the modern `rpicam` / `libcamera` stack.

It avoids MotionEye, MMAL, V4L2 compatibility wrappers, Flask, OpenCV, and databases. One Python process runs a local web portal, watches low-resolution YUV frames from `rpicam-vid`, records when motion is detected, and lets you review or delete clips in a browser.

## What It Does

- Uses `rpicam-vid` directly, so it matches current Raspberry Pi OS camera architecture.
- Detects motion from low-resolution luma-frame differences.
- Records clips during configured time windows.
- Stores recordings by date under `recordings/`.
- Serves a local web portal for playback, deletion, and basic tuning.
- Prunes old footage by retention days and maximum storage size.

## Requirements

- Raspberry Pi OS with `rpicam-apps`.
- A working CSI ribbon camera verified with:

```bash
rpicam-hello
rpicam-still -o test.jpg
```

- Python 3. No Python packages are required.

For MP4 output on Raspberry Pi 4 or earlier, `rpicam-vid --codec libav` must be available. CamHB falls back to raw `.h264` clips if MP4 recording fails and `fallback_to_h264` is true. Browser playback is best with MP4.

Raspberry Pi's camera docs show that `rpicam-vid` supports uncompressed `yuv420` output and MP4/libav recording, which are the two pieces CamHB uses.

## Quick Start

```bash
cp config.example.json config.json
python3 camhb.py --config config.json
```

Open:

```text
http://<pi-ip-address>:8080/
```

## Install As A Service

Clone the project on the Pi:

```bash
sudo apt update
sudo apt install -y git python3 rpicam-apps
sudo install -d -o pi -g video /opt/camhb /etc/camhb /var/lib/camhb/recordings
sudo -u pi git clone https://github.com/SydFloyd/CamHB.git /opt/camhb
cp /opt/camhb/config.example.json /etc/camhb/config.json
sudo cp /opt/camhb/systemd/camhb.service /etc/systemd/system/camhb.service
sudo chown -R pi:video /etc/camhb /var/lib/camhb
```

Edit `/etc/camhb/config.json`, especially `host`, `port`, `data_dir`, and `active_windows`. For the systemd install, set:

```json
"data_dir": "/var/lib/camhb/recordings"
```

If your user is not `pi`, change the `User=` line in `systemd/camhb.service`.

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now camhb
sudo journalctl -u camhb -f
```

## Update From Git

Pull updates on the Pi, then restart the service:

```bash
sudo -u pi git -C /opt/camhb pull --ff-only
sudo cp /opt/camhb/systemd/camhb.service /etc/systemd/system/camhb.service
sudo systemctl daemon-reload
sudo systemctl restart camhb
sudo journalctl -u camhb -f
```

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

## Security

This is intended for a trusted local network. Do not expose it directly to the internet.

For basic protection, set `access_token` in the config and open the portal with:

```text
http://<pi-ip-address>:8080/?token=<your-token>
```

## Expected Reliability Versus MotionEye

For your specific problem, the expected camera-connection reliability should be better than MotionEye because CamHB talks to `rpicam-vid` directly instead of asking MotionEye/Motion to enumerate the CSI camera through older MMAL/V4L2 expectations.

Overall maturity is lower. MotionEye is a full surveillance product with years of field use, more camera types, more UI features, and more edge-case handling. CamHB is intentionally tiny and should be easier to reason about, but it will need tuning in your physical scene.

My practical rating:

- Camera stack compatibility on modern Raspberry Pi OS: CamHB 8/10, MotionEye 4-6/10 for CSI cameras without wrappers.
- Motion detection sophistication: CamHB 5/10, MotionEye 7/10.
- Operational simplicity: CamHB 8/10, MotionEye 6/10.
- Feature completeness: CamHB 4/10, MotionEye 8/10.
- Expected reliability for a single OV5647 Pi CSI camera on Bookworm/Trixie: CamHB 7/10 after tuning, MotionEye 5/10 unless the compatibility layer is stable on that exact install.

If you only need timed motion clips and local review/delete, CamHB is likely the more dependable path for this Pi. If you need multi-camera dashboards, masks, notifications, streaming modes, or mature event logic, MotionEye still has the deeper feature set when it can actually see the camera.
