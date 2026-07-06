#!/usr/bin/env python3
"""CamHB: a tiny motion-triggered Raspberry Pi camera recorder."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import os
import posixpath
import signal
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
    "pre_record_seconds": 1,
    "record_seconds": 20,
    "cooldown_seconds": 5,
    "bitrate": 2_000_000,
    "retention_days": 14,
    "max_storage_mb": 20_480,
    "pan_enabled": True,
    "stepper_pins": [18, 23, 24, 25],
    "stepper_steps_per_rev": 4096,
    "stepper_step_delay": 0.0025,
    "pan_limit_degrees": 100,
    "pan_step_degrees": 5,
    "pan_invert": False,
    "manual_control_settle_seconds": 2,
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
    "pre_record_seconds",
    "record_seconds",
    "cooldown_seconds",
    "bitrate",
    "retention_days",
    "max_storage_mb",
    "pan_limit_degrees",
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
    video, canvas {
      width: 100%;
      max-height: 72vh;
      aspect-ratio: 16 / 9;
      background: #050605;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 50px var(--shadow);
      display: block;
    }
    canvas {
      image-rendering: auto;
    }
    .hidden {
      display: none;
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
    button:disabled {
      cursor: not-allowed;
      opacity: .48;
    }
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
    .control-panel {
      display: grid;
      gap: 12px;
      padding: 14px;
    }
    .control-pad {
      display: grid;
      grid-template-columns: repeat(2, 46px);
      gap: 8px;
      justify-content: center;
    }
    .control-pad button {
      width: 46px;
      height: 46px;
      min-height: 46px;
      padding: 0;
      font-size: 22px;
      line-height: 1;
    }
    .control-state {
      min-height: 18px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
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
    label.control-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
    }
    label.control-toggle input {
      width: auto;
      min-height: 0;
      padding: 0;
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
      <canvas id="live" width="320" height="240"></canvas>
      <video id="player" class="hidden" controls playsinline></video>
      <div class="selected">
        <span id="selected">Live feed</span>
        <div class="toolbar">
          <button id="show-live" class="primary">Live</button>
          <button id="refresh">Refresh</button>
          <button id="delete" class="danger">Delete</button>
        </div>
      </div>
    </div>
    <aside>
      <section>
        <h2>Camera Control</h2>
        <div class="control-panel">
          <label class="control-toggle">Control mode<input id="control-mode" type="checkbox"></label>
          <div class="control-pad" aria-label="Pan controls">
            <button class="control-left" type="button" data-move="left" title="Pan left" aria-label="Pan left">&#8592;</button>
            <button class="control-right" type="button" data-move="right" title="Pan right" aria-label="Pan right">&#8594;</button>
          </div>
          <div id="control-state" class="control-state">Unavailable</div>
        </div>
      </section>
      <section>
        <h2>Recordings</h2>
        <div id="clips" class="clips"><div class="empty">Loading</div></div>
      </section>
      <section>
        <h2>Settings</h2>
        <form id="settings" class="settings">
          <div class="grid2">
            <label>Clip seconds<input name="record_seconds" type="number" min="2" max="600"></label>
            <label>Pre-roll<input name="pre_record_seconds" type="number" min="1" max="10"></label>
          </div>
          <div class="grid2">
            <label>Cooldown<input name="cooldown_seconds" type="number" min="0" max="600"></label>
            <label>Bitrate<input name="bitrate" type="number" min="250000" max="25000000" step="250000"></label>
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
          <label>Pan limit<input name="pan_limit_degrees" type="number" min="5" max="180" step="1"></label>
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
    const live = document.getElementById('live');
    const liveCtx = live.getContext('2d');
    const selectedEl = document.getElementById('selected');
    const form = document.getElementById('settings');
    const controlModeEl = document.getElementById('control-mode');
    const controlStateEl = document.getElementById('control-state');
    const moveButtons = Array.from(document.querySelectorAll('[data-move]'));
    const keyDirections = new Map([
      ['ArrowLeft', 'left'],
      ['ArrowRight', 'right'],
    ]);
    let selected = null;
    let settings = {};
    let control = {};
    let controlBusy = false;
    let moveInFlight = false;
    let moveTimer = null;
    let activeMoveKey = null;

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

    function fmtDeg(value) {
      return Number(value || 0).toFixed(1).replace(/\.0$/, '');
    }

    function renderStatus(status) {
      const controlStatus = status.control || {};
      const parts = [status.active ? 'Armed' : 'Idle'];
      if (controlStatus.motion_suppressed) parts[0] = 'Control';
      if (status.recording) parts[0] = 'Recording';
      if (status.last_motion) parts.push('last motion ' + new Date(status.last_motion * 1000).toLocaleTimeString());
      stateEl.textContent = parts.join(' | ');
      dotEl.className = 'dot' + (status.recording ? ' recording' : status.active ? ' active' : '');
      settings = status.config;
      renderControl(controlStatus);
      fillSettings();
    }

    function renderControl(nextControl = control) {
      control = nextControl || {};
      if (document.activeElement !== controlModeEl) {
        controlModeEl.checked = Boolean(control.mode);
      }
      const canMove = Boolean(control.available && control.mode && !controlBusy && !moveInFlight);
      for (const button of moveButtons) button.disabled = !canMove;
      if (!control.enabled) {
        controlStateEl.textContent = control.mode ? 'Control mode on | motor disabled in config' : 'Motor disabled in config';
      } else if (!control.available) {
        const detail = control.error || 'Unavailable';
        controlStateEl.textContent = control.mode ? `${detail} | control mode on` : detail;
      } else {
        controlStateEl.textContent = `pan ${fmtDeg(control.pan_degrees)} deg / +/-${fmtDeg(control.pan_limit_degrees)} deg`;
      }
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
          live.classList.add('hidden');
          player.classList.remove('hidden');
          player.src = clip.url;
          selectedEl.textContent = clip.name;
          renderClips(clips);
        });
        clipsEl.appendChild(btn);
      }
    }

    async function refreshLive() {
      if (live.classList.contains('hidden')) return;
      try {
        const frame = await api('/api/frame');
        if (!frame.data) return;
        if (live.width !== frame.width || live.height !== frame.height) {
          live.width = frame.width;
          live.height = frame.height;
        }
        const y = Uint8Array.from(atob(frame.data), c => c.charCodeAt(0));
        const image = liveCtx.createImageData(frame.width, frame.height);
        for (let i = 0, j = 0; i < y.length; i++, j += 4) {
          image.data[j] = y[i];
          image.data[j + 1] = y[i];
          image.data[j + 2] = y[i];
          image.data[j + 3] = 255;
        }
        liveCtx.putImageData(image, 0, 0);
      } catch (_err) {
        // Keep the last frame visible if the camera is busy recording.
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

    async function setControlMode(enabled) {
      controlBusy = true;
      renderControl();
      try {
        const result = await api('/api/control-mode', {method: 'POST', body: JSON.stringify({enabled})});
        renderControl(result.control);
        await refresh();
      } catch (err) {
        stateEl.textContent = String(err.message || err);
        controlModeEl.checked = Boolean(control.mode);
      } finally {
        controlBusy = false;
        renderControl();
      }
    }

    async function moveCamera(direction) {
      if (moveInFlight || controlBusy) return;
      moveInFlight = true;
      renderControl();
      try {
        const result = await api('/api/move', {method: 'POST', body: JSON.stringify({direction})});
        renderControl(result.control);
      } catch (err) {
        stateEl.textContent = String(err.message || err);
        await refresh();
      } finally {
        moveInFlight = false;
        renderControl();
      }
    }

    function startRepeatedMove(direction) {
      stopMove();
      moveCamera(direction);
      moveTimer = setInterval(() => moveCamera(direction), 320);
    }

    function startMove(event) {
      event.preventDefault();
      if (event.currentTarget.disabled) return;
      startRepeatedMove(event.currentTarget.dataset.move);
    }

    function stopMove() {
      if (!moveTimer) return;
      clearInterval(moveTimer);
      moveTimer = null;
    }

    function isTypingTarget(target) {
      return target?.closest?.('input, textarea, select, [contenteditable="true"]');
    }

    function canUseKeyboardControl() {
      return Boolean(control.available && control.mode && !controlBusy);
    }

    controlModeEl.addEventListener('change', () => setControlMode(controlModeEl.checked));
    for (const button of moveButtons) {
      button.addEventListener('pointerdown', startMove);
      button.addEventListener('pointerleave', stopMove);
      button.addEventListener('pointercancel', stopMove);
      button.addEventListener('contextmenu', (event) => event.preventDefault());
      button.addEventListener('click', (event) => {
        if (event.detail === 0 && !button.disabled) moveCamera(button.dataset.move);
      });
    }
    window.addEventListener('keydown', (event) => {
      const direction = keyDirections.get(event.key);
      if (!direction || isTypingTarget(event.target)) return;
      if (control.mode) event.preventDefault();
      if (!canUseKeyboardControl()) return;
      if (event.repeat && activeMoveKey === event.key) return;
      activeMoveKey = event.key;
      startRepeatedMove(direction);
    });
    window.addEventListener('keyup', (event) => {
      if (!keyDirections.has(event.key) || activeMoveKey !== event.key) return;
      event.preventDefault();
      activeMoveKey = null;
      stopMove();
    });
    window.addEventListener('pointerup', stopMove);
    window.addEventListener('blur', () => {
      activeMoveKey = null;
      stopMove();
    });

    document.getElementById('refresh').addEventListener('click', refresh);
    document.getElementById('show-live').addEventListener('click', () => {
      selected = null;
      player.pause();
      player.removeAttribute('src');
      player.load();
      player.classList.add('hidden');
      live.classList.remove('hidden');
      selectedEl.textContent = 'Live feed';
      refreshLive();
      refresh();
    });
    document.getElementById('delete').addEventListener('click', async () => {
      if (!selected) return;
      await api('/api/delete', {method: 'POST', body: JSON.stringify({path: selected.path})});
      selected = null;
      player.removeAttribute('src');
      player.load();
      player.classList.add('hidden');
      live.classList.remove('hidden');
      selectedEl.textContent = 'Live feed';
      await refresh();
    });

    refresh();
    refreshLive();
    setInterval(refresh, 5000);
    setInterval(refreshLive, 300);
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


def clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PanController:
    HALF_STEP_SEQUENCE = (
        (1, 0, 0, 0),
        (1, 1, 0, 0),
        (0, 1, 0, 0),
        (0, 1, 1, 0),
        (0, 0, 1, 0),
        (0, 0, 1, 1),
        (0, 0, 0, 1),
        (1, 0, 0, 1),
    )

    def __init__(self, config: dict[str, Any]) -> None:
        self.lock = threading.RLock()
        self.enabled = bool(config.get("pan_enabled", True))
        self.available = False
        self.error = "pan disabled"
        self.stepper_pins = [int(pin) for pin in config["stepper_pins"]]
        self.stepper_steps_per_rev = int(config["stepper_steps_per_rev"])
        self.stepper_step_delay = float(config["stepper_step_delay"])
        self.pan_limit = self.configured_pan_limit(config)
        self.pan_step = 0.0
        self.pan_invert = False
        self.update_config(config)
        self.pan_degrees = 0.0
        self.sequence_index = 0
        self._stepper_outputs: list[Any] = []

        if not self.enabled:
            return

        try:
            from gpiozero import OutputDevice

            self._stepper_outputs = [
                OutputDevice(pin, active_high=True, initial_value=False) for pin in self.stepper_pins
            ]
            self.available = True
            self.error = ""
            logging.info(
                "pan ready: stepper GP%s",
                ",".join(str(pin) for pin in self.stepper_pins),
            )
        except Exception as exc:  # noqa: BLE001 - hardware stack may be absent on dev hosts
            self.error = f"pan unavailable: {exc}"
            logging.warning(self.error)
            self.close()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "enabled": self.enabled,
                "available": self.available,
                "error": self.error,
                "pan_degrees": round(self.pan_degrees, 2),
                "pan_limit_degrees": round(self.pan_limit, 2),
                "pan_min_degrees": -round(self.pan_limit, 2),
                "pan_max_degrees": round(self.pan_limit, 2),
            }

    def update_config(self, config: dict[str, Any]) -> None:
        with self.lock:
            self.pan_limit = self.configured_pan_limit(config)
            self.pan_step = float(config["pan_step_degrees"])
            self.pan_invert = bool(config.get("pan_invert", False))

    def configured_pan_limit(self, config: dict[str, Any]) -> float:
        if "pan_limit_degrees" in config:
            return float(config["pan_limit_degrees"])
        low = abs(float(config.get("pan_min_degrees", -100)))
        high = abs(float(config.get("pan_max_degrees", 100)))
        return max(low, high)

    def move(self, direction: str) -> None:
        with self.lock:
            if not self.enabled:
                raise RuntimeError("pan is disabled")
            if not self.available:
                raise RuntimeError(self.error or "pan is unavailable")
            if direction == "left":
                self.move_pan(-1)
            elif direction == "right":
                self.move_pan(1)
            else:
                raise ValueError("direction must be left or right")

    def move_pan(self, direction: int) -> None:
        if self.pan_invert:
            direction *= -1
        target = self.next_pan_target(direction)
        delta = target - self.pan_degrees
        if delta == 0:
            return
        steps = int(round(abs(delta) * self.stepper_steps_per_rev / 360.0))
        if steps == 0:
            self.pan_degrees = target
            return
        step_direction = 1 if delta > 0 else -1
        for _ in range(steps):
            self.sequence_index = (self.sequence_index + step_direction) % len(self.HALF_STEP_SEQUENCE)
            self.write_step(self.HALF_STEP_SEQUENCE[self.sequence_index])
            time.sleep(self.stepper_step_delay)
        self.release_stepper()
        self.pan_degrees = target

    def next_pan_target(self, direction: int) -> float:
        low = -self.pan_limit
        high = self.pan_limit
        if self.pan_degrees > high:
            if direction > 0:
                return self.pan_degrees
            return max(self.pan_degrees - self.pan_step, high)
        if self.pan_degrees < low:
            if direction < 0:
                return self.pan_degrees
            return min(self.pan_degrees + self.pan_step, low)
        return clamp_float(self.pan_degrees + (self.pan_step * direction), low, high)

    def write_step(self, values: tuple[int, int, int, int]) -> None:
        for output, value in zip(self._stepper_outputs, values):
            output.on() if value else output.off()

    def release_stepper(self) -> None:
        for output in self._stepper_outputs:
            try:
                output.off()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        with self.lock:
            self.release_stepper()
            for output in self._stepper_outputs:
                try:
                    output.close()
                except Exception:  # noqa: BLE001
                    pass
            self._stepper_outputs = []


class CameraService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        validate_config(self.config)
        self.data_dir = Path(self.config["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="camhb-camera", daemon=True)
        self.active = False
        self.recording = False
        self.last_motion: float | None = None
        self.last_error = ""
        self.current_clip = ""
        self.backend = "picamera2"
        self.latest_frame: bytes | None = None
        self.latest_frame_width = int(self.config["monitor_width"])
        self.latest_frame_height = int(self.config["monitor_height"])
        self.latest_frame_at: float | None = None
        self.control_mode = False
        self.motion_suppressed_until = 0.0
        self.pan_controller = PanController(self.config)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=8)
        self.pan_controller.close()

    def update_settings(self, changes: dict[str, Any]) -> None:
        with self.lock:
            for key, value in changes.items():
                if key in EDITABLE_KEYS:
                    self.config[key] = value
            validate_config(self.config)
            save_config(self.config_path, self.config)
            self.pan_controller.update_config(self.config)

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
                "backend": self.backend,
                "latest_frame_at": self.latest_frame_at,
                "control": self.control_status(),
                "config": public_config,
            }

    def control_status(self) -> dict[str, Any]:
        with self.lock:
            now = time.time()
            control_mode = self.control_mode
            motion_suppressed = self.motion_suppressed_locked(now)
            settle_remaining = max(0.0, self.motion_suppressed_until - now)
        status = self.pan_controller.status()
        status.update(
            {
                "mode": control_mode,
                "motion_suppressed": motion_suppressed,
                "settle_remaining": round(settle_remaining, 2),
            }
        )
        return status

    def motion_suppressed_locked(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.control_mode or now < self.motion_suppressed_until

    def manual_control_settle_seconds_locked(self) -> float:
        return max(0.0, float(self.config.get("manual_control_settle_seconds", 2)))

    def suppress_motion_locked(self) -> None:
        settle_seconds = self.manual_control_settle_seconds_locked()
        self.motion_suppressed_until = max(self.motion_suppressed_until, time.time() + settle_seconds)

    def set_control_mode(self, enabled: bool) -> dict[str, Any]:
        with self.lock:
            self.control_mode = bool(enabled)
            self.suppress_motion_locked()
        return {"ok": True, "control": self.control_status()}

    def move_camera(self, direction: str) -> dict[str, Any]:
        direction = direction.lower()
        with self.lock:
            if not self.control_mode:
                raise RuntimeError("enable control mode before moving the camera")
            self.suppress_motion_locked()
        self.pan_controller.move(direction)
        with self.lock:
            self.suppress_motion_locked()
        return {"ok": True, "control": self.control_status()}

    def latest_frame_payload(self) -> dict[str, Any]:
        with self.lock:
            if self.latest_frame is None:
                return {
                    "width": self.latest_frame_width,
                    "height": self.latest_frame_height,
                    "mtime": None,
                    "data": "",
                }
            return {
                "width": self.latest_frame_width,
                "height": self.latest_frame_height,
                "mtime": self.latest_frame_at,
                "data": base64.b64encode(self.latest_frame).decode("ascii"),
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
                self.run_picamera_loop()
            except Exception as exc:  # noqa: BLE001 - keep daemon alive
                logging.exception("camera loop failed")
                with self.lock:
                    self.last_error = str(exc)
                    self.active = False
                    self.recording = False
                time.sleep(5)

    def run_picamera_loop(self) -> None:
        try:
            from picamera2 import Picamera2
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import CircularOutput2, PyavOutput
        except ImportError as exc:
            raise RuntimeError("CamHB now requires python3-picamera2 on the Raspberry Pi") from exc

        cfg = self.snapshot_config()
        monitor_width = int(cfg["monitor_width"])
        monitor_height = int(cfg["monitor_height"])
        record_width = int(cfg["record_width"])
        record_height = int(cfg["record_height"])
        record_fps = int(cfg["record_fps"])
        pre_record_seconds = max(1.0, float(cfg["pre_record_seconds"]))

        picam2 = Picamera2(int(cfg["camera"]))
        main = {"size": (record_width, record_height), "format": "YUV420"}
        lores = {"size": (monitor_width, monitor_height), "format": "YUV420"}
        controls = {"FrameRate": record_fps}
        video_config = picam2.create_video_configuration(main, lores=lores, controls=controls)
        picam2.configure(video_config)

        encoder = H264Encoder(bitrate=int(cfg["bitrate"]), repeat=True)
        output = CircularOutput2(buffer_duration_ms=int(pre_record_seconds * 1000))
        logging.info(
            "starting picamera2 pipeline: main=%sx%s lores=%sx%s fps=%s pre=%.1fs",
            record_width,
            record_height,
            monitor_width,
            monitor_height,
            record_fps,
            pre_record_seconds,
        )
        picam2.start_recording(encoder, output)
        self.prune_storage()

        previous: bytes | None = None
        frames = 0
        encoding = False
        last_motion_in_clip = 0.0
        next_record_allowed = 0.0
        try:
            while not self.stop_event.is_set():
                loop_started = time.monotonic()
                dyn_cfg = self.snapshot_config()
                output.buffer_duration_ms = int(max(1.0, float(dyn_cfg["pre_record_seconds"])) * 1000)
                post_motion_seconds = max(1.0, float(dyn_cfg["record_seconds"]))
                cooldown_seconds = max(0.0, float(dyn_cfg["cooldown_seconds"]))
                monitor_interval = 1.0 / max(1.0, float(dyn_cfg["monitor_fps"]))
                stride = max(1, int(dyn_cfg["sample_stride"]))
                now_wall = time.time()
                with self.lock:
                    scheduled_active = is_active_now(dyn_cfg.get("active_windows", []))
                    still_active = scheduled_active and not self.motion_suppressed_locked(now_wall)
                    self.active = still_active

                frame = picam2.capture_array("lores")
                y_plane = frame[:monitor_height, :monitor_width].tobytes()
                with self.lock:
                    self.latest_frame = y_plane
                    self.latest_frame_width = monitor_width
                    self.latest_frame_height = monitor_height
                    self.latest_frame_at = time.time()

                frames += 1
                motion = False
                if previous is not None and frames > int(dyn_cfg["warmup_frames"]):
                    ratio = changed_ratio(previous, y_plane, stride, int(dyn_cfg["motion_threshold"]))
                    motion = still_active and ratio >= float(dyn_cfg["motion_ratio"])
                    if motion:
                        now = time.time()
                        self.last_motion = now
                        last_motion_in_clip = now
                        logging.info("motion detected ratio=%.4f", ratio)
                        if not encoding and now >= next_record_allowed:
                            output_path = self.open_motion_output(output, PyavOutput, cfg)
                            encoding = True
                            with self.lock:
                                self.recording = True
                                self.current_clip = str(output_path)

                if encoding:
                    now = time.time()
                    if not still_active or now - last_motion_in_clip >= post_motion_seconds:
                        output.close_output()
                        encoding = False
                        next_record_allowed = now + cooldown_seconds
                        with self.lock:
                            self.recording = False
                            self.current_clip = ""
                        self.prune_storage()

                previous = y_plane

                elapsed = time.monotonic() - loop_started
                if elapsed < monitor_interval:
                    self.stop_event.wait(monitor_interval - elapsed)
        finally:
            if encoding:
                try:
                    output.close_output()
                except Exception:  # noqa: BLE001
                    logging.exception("failed to close active output")
            picam2.stop_recording()
            with self.lock:
                self.recording = False
                self.current_clip = ""

    def open_motion_output(self, output: Any, output_cls: Any, cfg: dict[str, Any]) -> Path:
        now = datetime.now().astimezone()
        day_dir = self.data_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        container = "mp4"
        path = day_dir / f"{now.strftime('%H%M%S')}.{container}"
        output.open_output(output_cls(str(path)))
        logging.info("recording with pre-roll: %s", path)
        return path

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


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config.get("active_windows", []), list):
        raise ValueError("active_windows must be a list")
    for window in config.get("active_windows", []):
        parse_minutes(window["start"])
        parse_minutes(window["end"])
        for day in window.get("days", list(range(7))):
            if not isinstance(day, int) or day < 0 or day > 6:
                raise ValueError("days must use 0=Monday through 6=Sunday")
    for key in ("record_seconds", "pre_record_seconds", "cooldown_seconds", "monitor_fps", "record_fps"):
        if float(config[key]) < 0:
            raise ValueError(f"{key} must be positive")
    if float(config["motion_ratio"]) <= 0:
        raise ValueError("motion_ratio must be positive")
    stepper_pins = config.get("stepper_pins", [])
    if not isinstance(stepper_pins, list) or len(stepper_pins) != 4:
        raise ValueError("stepper_pins must list four GPIO pins")
    for pin in stepper_pins:
        if not isinstance(pin, int) or pin < 0:
            raise ValueError("GPIO pins must be non-negative integers")
    for key in (
        "pan_limit_degrees",
        "stepper_steps_per_rev",
        "stepper_step_delay",
        "pan_step_degrees",
    ):
        if float(config[key]) <= 0:
            raise ValueError(f"{key} must be positive")
    if float(config["manual_control_settle_seconds"]) < 0:
        raise ValueError("manual_control_settle_seconds must be non-negative")


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
            elif path == "/api/frame":
                self.send_json(self.app.latest_frame_payload())
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
            elif path == "/api/control-mode":
                self.send_json(self.app.set_control_mode(bool(body.get("enabled", False))))
            elif path == "/api/move":
                self.send_json(self.app.move_camera(str(body["direction"])))
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
    parser = argparse.ArgumentParser(description="Tiny motion security camera for Raspberry Pi Picamera2.")
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
