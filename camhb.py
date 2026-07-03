#!/usr/bin/env python3
"""CamHB: a tiny motion-triggered Raspberry Pi camera recorder."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import posixpath
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_NAME = "camhb"
CONFIG_VERSION = 1


DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "host": "0.0.0.0",
    "port": 8080,
    "access_token": "",
    "data_dir": "recordings",
    "camera": 0,
    "active_windows": [],
    "monitor_width": 320,
    "monitor_height": 240,
    "monitor_fps": 4,
    "sample_stride": 8,
    "motion_threshold": 18,
    "motion_ratio": 0.025,
    "warmup_frames": 8,
    "record_width": 1280,
    "record_height": 720,
    "record_fps": 15,
    "record_seconds": 20,
    "cooldown_seconds": 5,
    "bitrate": 2_000_000,
    "container": "mp4",
    "fallback_to_h264": True,
    "retention_days": 14,
    "max_storage_mb": 20_480,
    "rpicam_vid": "rpicam-vid",
}


EDITABLE_KEYS = {
    "active_windows",
    "monitor_fps",
    "sample_stride",
    "motion_threshold",
    "motion_ratio",
    "record_width",
    "record_height",
    "record_fps",
    "record_seconds",
    "cooldown_seconds",
    "bitrate",
    "container",
    "retention_days",
    "max_storage_mb",
}


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CamHB</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #111412;
      --panel: #181d1b;
      --panel-2: #202622;
      --text: #eef4ef;
      --muted: #aab7ad;
      --line: #303a34;
      --accent: #7cc58a;
      --danger: #ff7b72;
      --shadow: rgba(0, 0, 0, .2);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px clamp(16px, 4vw, 40px);
      border-bottom: 1px solid var(--line);
      background: #121613;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      font-size: clamp(20px, 3vw, 28px);
      margin: 0;
      font-weight: 720;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 22px;
      padding: 22px clamp(16px, 4vw, 40px) 40px;
      max-width: 1440px;
      margin: 0 auto;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #66706a;
      box-shadow: 0 0 0 4px rgba(124, 197, 138, 0);
    }
    .dot.active { background: var(--accent); box-shadow: 0 0 0 4px rgba(124, 197, 138, .16); }
    .dot.recording { background: var(--danger); box-shadow: 0 0 0 4px rgba(255, 123, 114, .16); }
    .viewer {
      min-width: 0;
    }
    video {
      width: 100%;
      max-height: 72vh;
      aspect-ratio: 16 / 9;
      background: #050605;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 50px var(--shadow);
      display: block;
    }
    .selected {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    button, input, select, textarea {
      font: inherit;
      color: var(--text);
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 7px;
    }
    button {
      min-height: 36px;
      padding: 0 12px;
      cursor: pointer;
    }
    button:hover { border-color: #516056; }
    button.primary {
      background: #203a28;
      border-color: #31583d;
    }
    button.danger {
      background: #3a2020;
      border-color: #643332;
    }
    aside {
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-width: 0;
    }
    section {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    section h2 {
      font-size: 14px;
      line-height: 1;
      margin: 0;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }
    .clips {
      max-height: 52vh;
      overflow: auto;
    }
    .clip {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      width: 100%;
      text-align: left;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      background: transparent;
      padding: 12px 14px;
    }
    .clip:last-child { border-bottom: 0; }
    .clip.active { background: #203026; }
    .clip-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
    }
    .clip-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .settings {
      display: grid;
      gap: 10px;
      padding: 14px;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
    }
    input, select, textarea {
      width: 100%;
      padding: 8px 9px;
      min-height: 36px;
    }
    textarea {
      min-height: 98px;
      resize: vertical;
      font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
    }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .empty {
      padding: 18px 14px;
      color: var(--muted);
      font-size: 14px;
    }
    @media (max-width: 920px) {
      main { grid-template-columns: 1fr; }
      video { max-height: 58vh; }
      aside { order: -1; }
      .clips { max-height: 34vh; }
    }
  </style>
</head>
<body>
  <header>
    <h1>CamHB</h1>
    <div class="status"><span id="dot" class="dot"></span><span id="state">Starting</span></div>
  </header>
  <main>
    <div class="viewer">
      <video id="player" controls playsinline></video>
      <div class="selected">
        <span id="selected">No clip selected</span>
        <div class="toolbar">
          <button id="refresh">Refresh</button>
          <button id="delete" class="danger">Delete</button>
        </div>
      </div>
    </div>
    <aside>
      <section>
        <h2>Recordings</h2>
        <div id="clips" class="clips"><div class="empty">Loading</div></div>
      </section>
      <section>
        <h2>Settings</h2>
        <form id="settings" class="settings">
          <div class="grid2">
            <label>Clip seconds<input name="record_seconds" type="number" min="2" max="600"></label>
            <label>Cooldown<input name="cooldown_seconds" type="number" min="0" max="600"></label>
          </div>
          <div class="grid2">
            <label>Motion threshold<input name="motion_threshold" type="number" min="1" max="80"></label>
            <label>Motion ratio<input name="motion_ratio" type="number" min="0.001" max="1" step="0.001"></label>
          </div>
          <div class="grid2">
            <label>Width<input name="record_width" type="number" min="320" max="4056"></label>
            <label>Height<input name="record_height" type="number" min="240" max="3040"></label>
          </div>
          <div class="grid2">
            <label>FPS<input name="record_fps" type="number" min="1" max="120"></label>
            <label>Retention days<input name="retention_days" type="number" min="1" max="3650"></label>
          </div>
          <label>Active windows<textarea name="active_windows"></textarea></label>
          <button class="primary" type="submit">Save</button>
        </form>
      </section>
    </aside>
  </main>
  <script>
    const queryToken = new URLSearchParams(location.search).get('token');
    if (queryToken) localStorage.setItem('camhb-token', queryToken);
    const accessToken = queryToken || localStorage.getItem('camhb-token') || '';
    const stateEl = document.getElementById('state');
    const dotEl = document.getElementById('dot');
    const clipsEl = document.getElementById('clips');
    const player = document.getElementById('player');
    const selectedEl = document.getElementById('selected');
    const form = document.getElementById('settings');
    let selected = null;
    let settings = {};

    async function api(path, options = {}) {
      const headers = options.headers || {};
      if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
      if (accessToken) headers['X-CamHB-Token'] = accessToken;
      const response = await fetch(path, {...options, headers});
      if (!response.ok) throw new Error(await response.text());
      return response.headers.get('content-type')?.includes('application/json') ? response.json() : response.text();
    }

    function fmtBytes(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function renderStatus(status) {
      const parts = [status.active ? 'Armed' : 'Idle'];
      if (status.recording) parts[0] = 'Recording';
      if (status.last_motion) parts.push('last motion ' + new Date(status.last_motion * 1000).toLocaleTimeString());
      stateEl.textContent = parts.join(' | ');
      dotEl.className = 'dot' + (status.recording ? ' recording' : status.active ? ' active' : '');
      settings = status.config;
      fillSettings();
    }

    function fillSettings() {
      for (const el of form.elements) {
        if (!el.name || settings[el.name] === undefined || el.dataset.dirty) continue;
        el.value = el.name === 'active_windows' ? JSON.stringify(settings[el.name], null, 2) : settings[el.name];
      }
    }

    function renderClips(clips) {
      clipsEl.innerHTML = '';
      if (!clips.length) {
        clipsEl.innerHTML = '<div class="empty">No recordings yet</div>';
        return;
      }
      for (const clip of clips) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'clip' + (selected && selected.path === clip.path ? ' active' : '');
        btn.innerHTML = `<span><span class="clip-name">${clip.name}</span><br><span class="clip-meta">${new Date(clip.mtime * 1000).toLocaleString()}</span></span><span class="clip-meta">${fmtBytes(clip.size)}</span>`;
        btn.addEventListener('click', () => {
          selected = clip;
          player.src = clip.url;
          selectedEl.textContent = clip.name;
          renderClips(clips);
        });
        clipsEl.appendChild(btn);
      }
    }

    async function refresh() {
      try {
        const [status, clips] = await Promise.all([api('/api/status'), api('/api/clips')]);
        renderStatus(status);
        renderClips(clips.clips);
      } catch (err) {
        stateEl.textContent = String(err.message || err);
        dotEl.className = 'dot';
      }
    }

    form.addEventListener('input', (event) => {
      if (event.target.name) event.target.dataset.dirty = '1';
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = {};
      for (const el of form.elements) {
        if (!el.name) continue;
        body[el.name] = el.name === 'active_windows' ? JSON.parse(el.value || '[]') : Number(el.value);
        delete el.dataset.dirty;
      }
      await api('/api/settings', {method: 'POST', body: JSON.stringify(body)});
      await refresh();
    });

    document.getElementById('refresh').addEventListener('click', refresh);
    document.getElementById('delete').addEventListener('click', async () => {
      if (!selected) return;
      await api('/api/delete', {method: 'POST', body: JSON.stringify({path: selected.path})});
      selected = null;
      player.removeAttribute('src');
      player.load();
      selectedEl.textContent = 'No clip selected';
      await refresh();
    });

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""


def load_config(path: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            user_config = json.load(handle)
        config.update(user_config)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_config(path, config)
    base = path.parent
    data_dir = Path(config["data_dir"])
    if not data_dir.is_absolute():
        data_dir = base / data_dir
    config["data_dir"] = str(data_dir)
    return config


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = dict(config)
    if path.parent in Path(serializable["data_dir"]).parents:
        try:
            serializable["data_dir"] = str(Path(serializable["data_dir"]).relative_to(path.parent))
        except ValueError:
            pass
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def parse_minutes(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour == 24 and minute == 0:
        return 24 * 60
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time {value!r}")
    return hour * 60 + minute


def is_active_now(windows: list[dict[str, Any]], now: datetime | None = None) -> bool:
    if not windows:
        return True
    now = now or datetime.now().astimezone()
    minute = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7
    for window in windows:
        days = window.get("days", list(range(7)))
        start = parse_minutes(window["start"])
        end = parse_minutes(window["end"])
        if start == end:
            continue
        if start < end:
            if today in days and start <= minute < end:
                return True
        else:
            if today in days and minute >= start:
                return True
            if yesterday in days and minute < end:
                return True
    return False


def exact_read(stream: Any, length: int) -> bytes | None:
    parts = []
    remaining = length
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=4)


class CameraService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self.data_dir = Path(self.config["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="camhb-camera", daemon=True)
        self.monitor_proc: subprocess.Popen[bytes] | None = None
        self.record_proc: subprocess.Popen[bytes] | None = None
        self.active = False
        self.recording = False
        self.last_motion: float | None = None
        self.last_error = ""
        self.current_clip = ""

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        terminate_process(self.monitor_proc)
        terminate_process(self.record_proc)
        self.thread.join(timeout=8)

    def update_settings(self, changes: dict[str, Any]) -> None:
        with self.lock:
            for key, value in changes.items():
                if key in EDITABLE_KEYS:
                    self.config[key] = value
            validate_config(self.config)
            save_config(self.config_path, self.config)

    def status(self) -> dict[str, Any]:
        with self.lock:
            public_config = {key: self.config[key] for key in sorted(EDITABLE_KEYS)}
            public_config["active_windows"] = self.config.get("active_windows", [])
            return {
                "active": self.active,
                "recording": self.recording,
                "last_motion": self.last_motion,
                "last_error": self.last_error,
                "current_clip": self.current_clip,
                "config": public_config,
            }

    def list_clips(self) -> list[dict[str, Any]]:
        clips = []
        for path in self.data_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".mp4", ".h264"}:
                continue
            rel = path.relative_to(self.data_dir).as_posix()
            stat = path.stat()
            clips.append(
                {
                    "name": path.name,
                    "path": rel,
                    "url": "/media/" + urllib.parse.quote(rel),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
        clips.sort(key=lambda item: item["mtime"], reverse=True)
        return clips

    def delete_clip(self, rel_path: str) -> None:
        target = safe_media_path(self.data_dir, rel_path)
        if target.exists() and target.is_file():
            target.unlink()
            prune_empty_dirs(self.data_dir)

    def run(self) -> None:
        logging.info("camera thread started")
        while not self.stop_event.is_set():
            try:
                self.prune_storage()
                with self.lock:
                    windows = list(self.config.get("active_windows", []))
                active = is_active_now(windows)
                with self.lock:
                    self.active = active
                if not active:
                    time.sleep(2)
                    continue
                self.monitor_until_motion()
            except Exception as exc:  # noqa: BLE001 - keep daemon alive
                logging.exception("camera loop failed")
                with self.lock:
                    self.last_error = str(exc)
                    self.active = False
                    self.recording = False
                terminate_process(self.monitor_proc)
                terminate_process(self.record_proc)
                time.sleep(5)

    def monitor_until_motion(self) -> None:
        cfg = self.snapshot_config()
        width = int(cfg["monitor_width"])
        height = int(cfg["monitor_height"])
        frame_size = width * height * 3 // 2
        y_size = width * height
        stride = max(1, int(cfg["sample_stride"]))
        cmd = [
            str(cfg["rpicam_vid"]),
            "-n",
            "-t",
            "0",
            "--camera",
            str(cfg["camera"]),
            "--width",
            str(width),
            "--height",
            str(height),
            "--framerate",
            str(cfg["monitor_fps"]),
            "--codec",
            "yuv420",
            "-o",
            "-",
        ]
        logging.info("starting monitor: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.monitor_proc = proc
        previous: bytes | None = None
        frames = 0
        motion_detected = False
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    still_active = is_active_now(self.config.get("active_windows", []))
                    self.active = still_active
                if not still_active:
                    return
                frame = exact_read(proc.stdout, frame_size) if proc.stdout else None
                if frame is None:
                    stderr = read_process_stderr(proc)
                    raise RuntimeError(f"monitor stopped unexpectedly: {stderr}")
                y_plane = frame[:y_size]
                frames += 1
                if previous is not None and frames > int(cfg["warmup_frames"]):
                    ratio = changed_ratio(previous, y_plane, stride, int(cfg["motion_threshold"]))
                    if ratio >= float(cfg["motion_ratio"]):
                        self.last_motion = time.time()
                        logging.info("motion detected ratio=%.4f", ratio)
                        motion_detected = True
                        break
                previous = y_plane
        finally:
            terminate_process(proc)
            self.monitor_proc = None
        if motion_detected and not self.stop_event.is_set():
            time.sleep(0.5)
            self.record_clip()

    def record_clip(self) -> None:
        cfg = self.snapshot_config()
        now = datetime.now().astimezone()
        day_dir = self.data_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        container = str(cfg["container"]).lower()
        if container not in {"mp4", "h264"}:
            container = "mp4"
        path = day_dir / f"{now.strftime('%H%M%S')}.{container}"
        ok = self.run_record_command(path, container, cfg)
        if not ok and container == "mp4" and cfg.get("fallback_to_h264", True):
            fallback = path.with_suffix(".h264")
            ok = self.run_record_command(fallback, "h264", cfg)
        with self.lock:
            self.recording = False
            self.current_clip = ""
        time.sleep(float(cfg["cooldown_seconds"]))
        self.prune_storage()

    def run_record_command(self, path: Path, container: str, cfg: dict[str, Any]) -> bool:
        cmd = [
            str(cfg["rpicam_vid"]),
            "-n",
            "--camera",
            str(cfg["camera"]),
            "-t",
            str(int(float(cfg["record_seconds"]) * 1000)),
            "--width",
            str(cfg["record_width"]),
            "--height",
            str(cfg["record_height"]),
            "--framerate",
            str(cfg["record_fps"]),
            "--bitrate",
            str(cfg["bitrate"]),
            "-o",
            str(path),
        ]
        if container == "mp4":
            cmd[1:1] = ["--codec", "libav"]
        logging.info("recording: %s", " ".join(cmd))
        with self.lock:
            self.recording = True
            self.current_clip = str(path)
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.record_proc = proc
        try:
            rc = proc.wait(timeout=float(cfg["record_seconds"]) + 20)
        except subprocess.TimeoutExpired:
            terminate_process(proc)
            rc = 124
        finally:
            self.record_proc = None
        if rc != 0:
            stderr = read_process_stderr(proc)
            with self.lock:
                self.last_error = f"record failed: {stderr}"
            logging.error("record failed rc=%s stderr=%s", rc, stderr)
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
            return False
        return path.exists() and path.stat().st_size > 0

    def prune_storage(self) -> None:
        cfg = self.snapshot_config()
        retention_days = int(cfg["retention_days"])
        max_storage = int(cfg["max_storage_mb"]) * 1024 * 1024
        cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
        for path in self.data_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".mp4", ".h264"}:
                if datetime.fromtimestamp(path.stat().st_mtime).astimezone() < cutoff:
                    path.unlink()
        clips = [Path(self.data_dir, item["path"]) for item in self.list_clips()]
        total = sum(path.stat().st_size for path in clips if path.exists())
        for path in reversed(clips):
            if total <= max_storage:
                break
            if path.exists():
                size = path.stat().st_size
                path.unlink()
                total -= size
        prune_empty_dirs(self.data_dir)

    def snapshot_config(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.config)


def changed_ratio(previous: bytes, current: bytes, stride: int, threshold: int) -> float:
    changed = 0
    total = 0
    for index in range(0, min(len(previous), len(current)), stride):
        if abs(previous[index] - current[index]) >= threshold:
            changed += 1
        total += 1
    return changed / max(1, total)


def read_process_stderr(proc: subprocess.Popen[bytes]) -> str:
    if not proc.stderr:
        return ""
    try:
        return proc.stderr.read().decode("utf-8", errors="replace").strip()[-1200:]
    except Exception:  # noqa: BLE001
        return ""


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config.get("active_windows", []), list):
        raise ValueError("active_windows must be a list")
    for window in config.get("active_windows", []):
        parse_minutes(window["start"])
        parse_minutes(window["end"])
        for day in window.get("days", list(range(7))):
            if not isinstance(day, int) or day < 0 or day > 6:
                raise ValueError("days must use 0=Monday through 6=Sunday")
    for key in ("record_seconds", "cooldown_seconds", "monitor_fps", "record_fps"):
        if float(config[key]) < 0:
            raise ValueError(f"{key} must be positive")
    if float(config["motion_ratio"]) <= 0:
        raise ValueError("motion_ratio must be positive")


def safe_media_path(root: Path, rel_path: str) -> Path:
    decoded = urllib.parse.unquote(rel_path)
    normalized = posixpath.normpath(decoded).lstrip("/")
    target = (root / normalized).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError("invalid media path")
    return target


def prune_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


class CamHandler(BaseHTTPRequestHandler):
    server_version = "CamHB/1.0"

    @property
    def app(self) -> CameraService:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        try:
            if not self.authorized():
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/":
                self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/status":
                self.send_json(self.app.status())
            elif path == "/api/clips":
                self.send_json({"clips": self.app.list_clips()})
            elif path.startswith("/media/"):
                self.send_media(path[len("/media/") :])
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            logging.exception("GET failed")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            if not self.authorized():
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            path = urllib.parse.urlsplit(self.path).path
            body = self.read_json()
            if path == "/api/delete":
                self.app.delete_clip(str(body["path"]))
                self.send_json({"ok": True})
            elif path == "/api/settings":
                self.app.update_settings(body)
                self.send_json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            logging.exception("POST failed")
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def authorized(self) -> bool:
        token = str(self.app.config.get("access_token", ""))
        if not token:
            return True
        supplied = self.headers.get("X-CamHB-Token", "")
        if supplied == token:
            return True
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return query.get("token", [""])[0] == token

    def send_json(self, data: Any) -> None:
        self.send_bytes(json.dumps(data).encode("utf-8"), "application/json")

    def send_bytes(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_media(self, rel_path: str) -> None:
        target = safe_media_path(self.app.data_dir, rel_path)
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = target.stat().st_size
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            status = HTTPStatus.PARTIAL_CONTENT
            spec = range_header.removeprefix("bytes=").split(",", 1)[0]
            start_text, _, end_text = spec.partition("-")
            if start_text:
                start = int(start_text)
            if end_text:
                end = int(end_text)
            end = min(end, size - 1)
        if start < 0 or end < start or start >= size:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with target.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)


class CamServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], app: CameraService) -> None:
        super().__init__(address, handler)
        self.app = app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny motion security camera for Raspberry Pi rpicam.")
    parser.add_argument("--config", default=os.environ.get("CAMHB_CONFIG", "config.json"))
    parser.add_argument("--log-level", default=os.environ.get("CAMHB_LOG_LEVEL", "INFO"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config_path = Path(args.config).resolve()
    app = CameraService(config_path)
    validate_config(app.config)
    app.start()
    host = str(app.config["host"])
    port = int(app.config["port"])
    server = CamServer((host, port), CamHandler, app)

    def shutdown(_signum: int, _frame: Any) -> None:
        logging.info("shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.info("web portal listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
