# 打包 pyinstaller --onefile --noconsole --name "makevideo" --icon "myicon.ico" --add-data "myicon.ico;." makevideo.py
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import sys
import os
import re
import json
import shutil
import queue
import threading
import subprocess
import datetime
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import sounddevice as sd
import soundfile as sf
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageGrab

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import pyloudnorm as pyln
    HAS_PYLN = True
except Exception:
    HAS_PYLN = False

try:
    import lameenc
    HAS_LAME = True
except Exception:
    HAS_LAME = False

try:
    from opencc import OpenCC
    _CC_T2S = OpenCC("t2s")
except Exception:
    _CC_T2S = None

SR = 44100
CH = 1
DEFAULT_VIEW_LEN = 10.0
TOP_ZONE_RATIO = 0.18
TARGET_LUFS = -14.0
TARGET_TRUE_PEAK_DB = -1.0
MP3_BITRATE = 192
MIN_LUFS_SECONDS = 0.4

CLIP_COLORS = ["#dbeafe", "#dcfce7", "#fef9c3", "#fae8ff", "#ffe4e6", "#e0f2fe"]

HELP_TEXT = """【快捷键】

R = 录制
P = 暂停
I = 插入录制（需先点出光标）
O = 导入 WAV（有光标插到光标处，否则接在末尾）
S = 转字幕（选一个 WAV 文件，生成同名 SRT）
E = 导出（固定导出到 input/）
+ / - = 缩放
空格 = 从光标播放 / 停止

【录音声音太小的排查】

1. 打开 Realtek Audio Console（开始菜单搜 "Realtek"）：
   - 找到「麦克风加强 / Microphone Boost」，调到 +20dB 或中间
   - 找到「录音音量」，拉满
2. Windows 声音设置：
   - 右键任务栏喇叭 → 声音设置 → 输入 → 选「麦克风阵列」
   - 「输入音量」拉到 100
   - 设备属性 → 高级 → 取消勾选「允许应用程序独占控制此设备」
3. 如果还是小：重启电脑；检查是否有别的程序（会议/语音/浏览器）占用麦克风。

【基本操作】

- 录制 / 暂停：每次暂停生成一个新区块，接在末尾
- 插入录制：先在块内部点出光标，按钮变亮，点击后从光标处插入一段新录音；
  如果光标在某个块中间，该块会被切成前后两块，新块夹在中间。
- 导入 WAV：点"导入 (O)"选一个 .wav 文件；有光标就插到光标处，否则接在末尾。
- 转字幕：点"转字幕 (S)"，弹窗选一个 .wav 文件，识别后在同目录生成同名 .srt（已有则覆盖）。
- 点区块顶部灰色条：选中整块，按 Delete 删除整块
- 点区块内部：放红色光标
- 在区块内部按住拖：框选（橙色），按 Delete 删除选中范围
- 空格：从光标处播放，再按空格停止
- + / −：缩放；底部滚动条：平移
- 导出：固定导出到 input/ 文件夹

【导出响度】

导出自动走 YouTube 标准 -14 LUFS + 真峰值限幅 -1 dBTP。
音频过短（<0.4 秒）时跳过响度处理，直接导出。
"""


TITLE1 = ""
TITLE2 = ""

SLIDE_TIME = 4.0
HOLD_TIME = 0.1
XFADE = 0.2

OUT_W = 720
OUT_H = 1280
FPS = 30
FG_HEIGHT_RATIO = 0.60
IMG_W = 960
IMG_H = 720
BLUR_RADIUS = 50

WHISPER_MODEL = "models"
WHISPER_LANGUAGE = "zh"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
WHISPER_PROMPT = ""

FONT_CANDIDATES = [
    os.path.join("fonts", "msyhbd.ttc"),
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/Dengb.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
]

TITLE_FONT_SIZE = 60
TITLE_FONT_SIZE_LINE2 = 50
TITLE_LINE_GAP = 15
TITLE_TOP_MARGIN = 85
TITLE_SHRINK_THRESHOLD = 9
TITLE_SHRINK_PX = 12
TITLE_LINE1_EXTRA_PX = 2
TITLE_SKEW = 0.18
TITLE_BOLD_OFFSET = 1
TITLE_STROKE_COLOR = (0, 0, 0, 255)
TITLE_STROKE_WIDTH = 2
TITLE_COLOR = (255, 220, 0, 255)
TITLE_SHADOW = True
TITLE_SHADOW_COLOR = (0, 0, 0, 120)
TITLE_SHADOW_OFFSET = (2, 2)
TITLE_SHADOW_BLUR = 2

SUB_FONT_SIZE = 42
SUB_COLOR = (255, 255, 255, 255)
SUB_STROKE_COLOR = (0, 0, 0, 255)
SUB_STROKE_WIDTH = 2
SUB_BOLD_OFFSET = 1
SUB_LINE_GAP = 8
SUB_MAX_WIDTH_RATIO = 0.90
SUB_BOTTOM_MARGIN = 130

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IN_FOLDER = os.path.join(BASE_DIR, "input")
TMP_CROP_FOLDER = os.path.join(BASE_DIR, "output", "_tmp_crop")
OUT_FOLDER = os.path.join(BASE_DIR, "output")

SHOT_MODE = "ratio"
SHOT_RATIO_W, SHOT_RATIO_H = 4, 3
SHOT_FIXED_W, SHOT_FIXED_H = 960, 720
SHOT_EDGE_TOLERANCE = 14
SHOT_RECT_WIDTH = 4
SHOT_TOAST_MS = 1500
SHOT_GRAB_DELAY = 150

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

ENV_TITLE1 = "VM_TITLE1"
ENV_TITLE2 = "VM_TITLE2"
ENV_OUTNAME = "VM_OUTNAME"


def _font_search_dirs():
    dirs = [BASE_DIR]
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows"
    dirs.append(os.path.join(win, "Fonts"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    out = []
    for d in dirs:
        if d and os.path.isdir(d):
            out.append(d)
    return out


def _resolve_font_path(rel_or_abs):
    if not rel_or_abs:
        return None
    if os.path.isabs(rel_or_abs):
        return rel_or_abs if os.path.exists(rel_or_abs) else None
    for d in _font_search_dirs():
        p = os.path.join(d, rel_or_abs)
        if os.path.exists(p):
            return p
    return rel_or_abs if os.path.exists(rel_or_abs) else None


def resolve_first_available_font():
    for cand in FONT_CANDIDATES:
        p = _resolve_font_path(cand)
        if p:
            return p
    return None


RESOLVED_FONT_PATH = resolve_first_available_font()
if RESOLVED_FONT_PATH:
    print(f"Font resolved: {RESOLVED_FONT_PATH}")
else:
    print("Font resolved: none, will use PIL default font")


def sanitize_filename(name):
    if not name:
        return ""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'[\x00-\x1f]', "", name)
    name = name.strip().strip(".").strip()
    return name


def _load_wav(path):
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != SR:
        n = int(len(data) * SR / sr)
        data = np.interp(
            np.linspace(0, len(data) - 1, n),
            np.arange(len(data)),
            data,
        ).astype(np.float32)
    return data.astype(np.float32)


def _format_srt_time(seconds):
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h = ms // 3600000
    ms -= h * 3600000
    m = ms // 60000
    ms -= m * 60000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_time(s):
    s = s.strip().replace(".", ",")
    m = re.match(r"(\d+):(\d+):(\d+),(\d+)", s)
    if not m:
        return 0.0
    h, mi, sec, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mi * 60 + sec + ms / 1000.0


def _write_srt(segments, out_path):
    lines = []
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{_format_srt_time(seg['start'])} --> {_format_srt_time(seg['end'])}")
        lines.append(text)
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def _read_srt(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", content.strip())
    result = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue
        idx = 0
        if re.match(r"^\d+$", lines[0].strip()):
            idx = 1
        if idx >= len(lines):
            continue
        time_line = lines[idx]
        m = re.match(r"\s*(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", time_line)
        if not m:
            continue
        start = _parse_srt_time(m.group(1))
        end = _parse_srt_time(m.group(2))
        text = " ".join(lines[idx + 1:]).strip()
        if not text:
            continue
        result.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return result


class ScreenshotTool:
    def __init__(self, root, on_saved=None):
        self.root = root
        self.on_saved = on_saved
        self.overlay = None
        self.canvas = None
        self.rect = None
        self.outline = None
        self.state = "idle"
        self.box = [0, 0, 0, 0]
        self.drag_mode = None
        self.drag_start = (0, 0)
        self.box_start = [0, 0, 0, 0]
        self._near = (False, False, False, False)
        self._hint = None
        self.enabled = True

    def start_capture(self):
        if not self.enabled:
            return
        if self.overlay is not None:
            return
        self.root.withdraw()
        self.root.after(200, self._open_overlay)

    def _open_overlay(self):
        try:
            self.overlay = tk.Toplevel()
            self.overlay.attributes("-fullscreen", True)
            self.overlay.attributes("-alpha", 0.25)
            self.overlay.attributes("-topmost", True)
            self.overlay.configure(bg="black", cursor="cross")
        except Exception as e:
            print("Create overlay failed:", repr(e))
            self.root.deiconify()
            return

        self.canvas = tk.Canvas(self.overlay, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.state = "drawing"
        self.rect = None
        self.outline = None
        self.box = [0, 0, 0, 0]
        self._hint = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_hover)
        self.overlay.bind("<Escape>", lambda e: self.cancel())
        self.overlay.bind("<Return>", lambda e: self.confirm())
        self.overlay.bind("<KP_Enter>", lambda e: self.confirm())
        self.overlay.focus_force()

    def _redraw_rect(self):
        if self.outline:
            self.canvas.delete(self.outline)
        if self.rect:
            self.canvas.delete(self.rect)
        l, t, r, b = self.box
        self.outline = self.canvas.create_rectangle(
            l, t, r, b, outline="white", width=SHOT_RECT_WIDTH + 3
        )
        self.rect = self.canvas.create_rectangle(
            l, t, r, b, outline="red", width=SHOT_RECT_WIDTH
        )

    def on_press(self, event):
        if self.state == "drawing":
            self.start_x, self.start_y = event.x, event.y
            self.box = [event.x, event.y, event.x, event.y]
            self._redraw_rect()
        elif self.state == "adjusting":
            l, t, r, b = self.box
            tol = SHOT_EDGE_TOLERANCE
            inside = l <= event.x <= r and t <= event.y <= b
            near_left = abs(event.x - l) <= tol
            near_right = abs(event.x - r) <= tol
            near_top = abs(event.y - t) <= tol
            near_bottom = abs(event.y - b) <= tol
            self._near = (near_left, near_right, near_top, near_bottom)

            if inside and (near_left or near_right or near_top or near_bottom):
                self.drag_mode = "edge"
            else:
                self.drag_mode = "move"

            self.drag_start = (event.x, event.y)
            self.box_start = list(self.box)

    def on_drag(self, event):
        if self.state == "drawing":
            x1, y1 = self.start_x, self.start_y
            self.box = self._constrain_rect(x1, y1, event.x, event.y)
            self._redraw_rect()
        elif self.state == "adjusting":
            if self.drag_mode == "move":
                dx = event.x - self.drag_start[0]
                dy = event.y - self.drag_start[1]
                l, t, r, b = self.box_start
                w, h = r - l, b - t
                sw = self.overlay.winfo_screenwidth()
                sh = self.overlay.winfo_screenheight()
                max_l = max(0, sw - w)
                max_t = max(0, sh - h)
                new_l = max(0, min(l + dx, max_l))
                new_t = max(0, min(t + dy, max_t))
                self.box = [new_l, new_t, new_l + w, new_t + h]
                self._redraw_rect()
                self._update_hint()
            elif self.drag_mode == "edge":
                self._resize_edge(event.x, event.y)

    def on_release(self, event):
        if self.state == "drawing":
            l, t, r, b = self.box
            if r - l < 10 or b - t < 10:
                if self.rect:
                    self.canvas.delete(self.rect)
                if self.outline:
                    self.canvas.delete(self.outline)
                self.rect = self.outline = None
                return
            self.state = "adjusting"
            self._draw_hint()
        elif self.state == "adjusting":
            self.drag_mode = None

    def on_hover(self, event):
        if self.state != "adjusting":
            return
        l, t, r, b = self.box
        tol = SHOT_EDGE_TOLERANCE
        near_left = abs(event.x - l) <= tol
        near_right = abs(event.x - r) <= tol
        near_top = abs(event.y - t) <= tol
        near_bottom = abs(event.y - b) <= tol
        inside = l <= event.x <= r and t <= event.y <= b

        if (near_left or near_right) and (near_top or near_bottom):
            self.canvas.config(cursor="sizing")
        elif near_left or near_right:
            self.canvas.config(cursor="sb_h_double_arrow")
        elif near_top or near_bottom:
            self.canvas.config(cursor="sb_v_double_arrow")
        elif inside:
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="cross")

    def _constrain_rect(self, x1, y1, x2, y2):
        sign_x = 1 if x2 >= x1 else -1
        sign_y = 1 if y2 >= y1 else -1
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)

        if SHOT_MODE == "ratio":
            if dx / SHOT_RATIO_W > dy / SHOT_RATIO_H:
                dy = dx * SHOT_RATIO_H / SHOT_RATIO_W
            else:
                dx = dy * SHOT_RATIO_W / SHOT_RATIO_H
        else:
            dx = SHOT_FIXED_W
            dy = SHOT_FIXED_H

        x2 = x1 + sign_x * dx
        y2 = y1 + sign_y * dy
        l, r = min(x1, x2), max(x1, x2)
        t, b = min(y1, y2), max(y1, y2)
        return [l, t, r, b]

    def _resize_edge(self, mx, my):
        l, t, r, b = self.box_start
        w, h = r - l, b - t
        near_left, near_right, near_top, near_bottom = self._near

        ratio = (SHOT_RATIO_W / SHOT_RATIO_H) if SHOT_MODE == "ratio" else (SHOT_FIXED_W / SHOT_FIXED_H)
        new_w, new_h = w, h

        if near_left:
            new_w = max(20, r - mx); new_h = new_w / ratio
        elif near_right:
            new_w = max(20, mx - l); new_h = new_w / ratio
        elif near_top:
            new_h = max(20, b - my); new_w = new_h * ratio
        elif near_bottom:
            new_h = max(20, my - t); new_w = new_h * ratio

        if SHOT_MODE == "size":
            new_w, new_h = SHOT_FIXED_W, SHOT_FIXED_H

        new_l, new_r = (r - new_w, r) if near_left else (l, l + new_w)
        new_t, new_b = (b - new_h, b) if near_top else (t, t + new_h)

        sw = self.overlay.winfo_screenwidth()
        sh = self.overlay.winfo_screenheight()
        new_l = max(0, min(new_l, sw)); new_t = max(0, min(new_t, sh))
        new_r = max(0, min(new_r, sw)); new_b = max(0, min(new_b, sh))

        self.box = [new_l, new_t, new_r, new_b]
        self._redraw_rect()
        self._update_hint()

    def _draw_hint(self):
        l, t, r, b = self.box
        text = f"{int(r - l)} x {int(b - t)}   Enter save / Esc cancel"
        tx, ty = l, b + 20
        if ty > self.overlay.winfo_screenheight() - 20:
            ty = t - 20
        if self._hint:
            self.canvas.delete(self._hint)
        self._hint = self.canvas.create_text(
            tx, ty, text=text, fill="yellow", anchor="nw",
            font=("Arial", 12, "bold")
        )

    def _update_hint(self):
        if self.state == "adjusting":
            self._draw_hint()

    def confirm(self):
        if self.state != "adjusting":
            return
        l, t, r, b = [int(v) for v in self.box]

        sw_logical = self.overlay.winfo_screenwidth() if self.overlay else 1920
        try:
            sw_physical = ctypes.windll.user32.GetSystemMetrics(0)
            sh_physical = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            sw_physical = sw_logical
            sh_physical = self.overlay.winfo_screenheight() if self.overlay else 1080

        scale = sw_physical / sw_logical if sw_logical else 1.0
        l2 = max(0, min(int(l * scale), sw_physical))
        r2 = max(0, min(int(r * scale), sw_physical))
        t2 = max(0, min(int(t * scale), sh_physical))
        b2 = max(0, min(int(b * scale), sh_physical))

        if r2 - l2 < 1 or b2 - t2 < 1:
            print("Invalid shot area, cancel")
            self.cancel()
            return

        print(f"[debug] logical=({l},{t},{r},{b}) scale={scale:.4f} physical=({l2},{t2},{r2},{b2})")

        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
            self.canvas = None
            self.rect = None
            self.outline = None
            self._hint = None
            self.state = "idle"

        self.root.after(SHOT_GRAB_DELAY, lambda: self._grab_and_save(l2, t2, r2, b2))

    def _grab_and_save(self, l, t, r, b):
        try:
            os.makedirs(IN_FOLDER, exist_ok=True)
            img = ImageGrab.grab(bbox=(l, t, r, b))
            filename = datetime.datetime.now().strftime("shot_%Y%m%d_%H%M%S_%f")[:-3] + ".png"
            path = os.path.join(IN_FOLDER, filename)
            img.save(path)
            print("Saved to input:", path, img.size)

            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._show_toast(success=True)
            if self.on_saved:
                try:
                    self.on_saved(path)
                except Exception:
                    pass
        except Exception as e:
            print("Screenshot failed:", repr(e))
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._show_toast(success=False, text=str(e)[:60])

    def _show_toast(self, success=True, text=None):
        try:
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.attributes("-alpha", 0.92)
            toast.configure(bg="#222222")
        except Exception:
            return

        w, h = 200, 60
        sw = toast.winfo_screenwidth()
        sh = toast.winfo_screenheight()
        x = sw - w - 40
        y = sh - h - 60
        toast.geometry(f"{w}x{h}+{x}+{y}")

        canvas = tk.Canvas(toast, width=w, height=h, bg="#222222",
                           highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        if text is None:
            text = "Saved to input" if success else "Screenshot failed"

        if success:
            canvas.create_oval(12, 12, 48, 48, fill="#22aa44", outline="")
            canvas.create_line(20, 30, 28, 38, 42, 22,
                               fill="white", width=4, capstyle="round",
                               joinstyle="round")
            canvas.create_text(58, 30, text=text, fill="white",
                               font=("Microsoft YaHei", 12, "bold"),
                               anchor="w")
        else:
            canvas.create_oval(12, 12, 48, 48, fill="#cc3333", outline="")
            canvas.create_line(22, 22, 38, 38, fill="white", width=4,
                               capstyle="round")
            canvas.create_line(38, 22, 22, 38, fill="white", width=4,
                               capstyle="round")
            canvas.create_text(58, 30, text=text, fill="white",
                               font=("Microsoft YaHei", 12, "bold"),
                               anchor="w")

        def fade(alpha=0.92):
            if alpha <= 0:
                try:
                    toast.destroy()
                except tk.TclError:
                    pass
                return
            try:
                toast.attributes("-alpha", alpha)
                toast.after(30, lambda: fade(alpha - 0.08))
            except tk.TclError:
                pass

        toast.after(SHOT_TOAST_MS, lambda: fade(0.92))

    def cancel(self):
        self._close_overlay()

    def _close_overlay(self):
        if self.overlay is not None:
            try:
                self.overlay.destroy()
            except tk.TclError:
                pass
            self.overlay = None
            self.canvas = None
            self.rect = None
            self.outline = None
            self._hint = None
            self.state = "idle"
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass


def _run_video_pipeline_impl():
    from moviepy import (ImageClip, AudioFileClip, CompositeVideoClip,
                         concatenate_videoclips, VideoFileClip, vfx)

    title1 = os.environ.get(ENV_TITLE1, TITLE1)
    title2 = os.environ.get(ENV_TITLE2, TITLE2)
    out_name_raw = os.environ.get(ENV_OUTNAME, "")
    print(f"Title1: {title1!r}")
    print(f"Title2: {title2!r}")
    print(f"OutName: {out_name_raw!r}")

    os.makedirs(OUT_FOLDER, exist_ok=True)
    os.makedirs(TMP_CROP_FOLDER, exist_ok=True)

    W, H = OUT_W, OUT_H

    for f in os.listdir(OUT_FOLDER):
        if f.endswith("_segments.json") or f.endswith("_text.txt") or f.lower().endswith(".mp4"):
            p = os.path.join(OUT_FOLDER, f)
            try:
                os.remove(p)
                print(f"Clean old file: {f}")
            except Exception as e:
                print(f"Clean failed {f}: {e}")

    AUDIO_EXTS = (".mp3", ".wav")
    all_audio = [
        f for f in sorted(os.listdir(IN_FOLDER))
        if f.lower().endswith(AUDIO_EXTS)
    ]

    if len(all_audio) == 0:
        print("Error: no audio file in input folder. Put one MP3 or WAV.")
        return 1

    if len(all_audio) > 1:
        print("Error: only one audio file allowed. Found:")
        for f in all_audio:
            print("  -", f)
        print("Move extra audio files out of input and run again.")
        return 1

    audio_name = all_audio[0]
    audio_path = os.path.join(IN_FOLDER, audio_name)
    audio_base = os.path.splitext(audio_name)[0]
    print(f"Audio: {audio_name}")

    out_stem = sanitize_filename(out_name_raw)
    if not out_stem:
        out_stem = audio_base
    out_path = os.path.join(OUT_FOLDER, out_stem + ".mp4")
    print(f"Output will be: {os.path.basename(out_path)}")

    srt_path = os.path.join(IN_FOLDER, audio_base + ".srt")
    if not os.path.exists(srt_path):
        print(f"Error: no srt file. Expected: {audio_base}.srt")
        return 1

    print(f"Subtitle source: srt ({os.path.basename(srt_path)})")
    subtitle_segments = _read_srt(srt_path)
    if not subtitle_segments:
        print("Error: srt file is empty or invalid.")
        return 1
    print(f"Subtitle loaded: {len(subtitle_segments)} segments")

    def get_font(size):
        if RESOLVED_FONT_PATH and os.path.exists(RESOLVED_FONT_PATH):
            try:
                return ImageFont.truetype(RESOLVED_FONT_PATH, size)
            except Exception as e:
                print(f"Load font failed: {e}. Use system font.")
        for cand in FONT_CANDIDATES:
            p = _resolve_font_path(cand)
            if p:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _title_sizes(t1, t2):
        has1 = bool(t1.strip())
        has2 = bool(t2.strip())
        n1 = len(t1.strip())
        n2 = len(t2.strip())

        size2 = TITLE_FONT_SIZE_LINE2
        if has2 and n2 > TITLE_SHRINK_THRESHOLD:
            size2 = max(20, TITLE_FONT_SIZE_LINE2 - TITLE_SHRINK_PX)

        size1 = TITLE_FONT_SIZE
        if has1 and n1 > TITLE_SHRINK_THRESHOLD:
            base_for_line1 = max(20, TITLE_FONT_SIZE_LINE2 - TITLE_SHRINK_PX)
            size1 = base_for_line1 + TITLE_LINE1_EXTRA_PX
            size1 = min(size1, TITLE_FONT_SIZE)

        return size1, size2

    def make_title_png(t1, t2, out_path):
        if not t1.strip() and not t2.strip():
            return None

        s1, s2 = _title_sizes(t1, t2)
        print(f"Title font sizes: line1={s1}, line2={s2}")

        line_specs = []
        if t1.strip():
            line_specs.append((t1, get_font(s1), s1))
        if t2.strip():
            line_specs.append((t2, get_font(s2), s2))

        dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(dummy)
        max_w = 0
        total_h = 0
        for line, font, size in line_specs:
            bbox = d.textbbox((0, 0), line, font=font, stroke_width=TITLE_STROKE_WIDTH)
            max_w = max(max_w, bbox[2] - bbox[0])
            total_h += size + TITLE_LINE_GAP

        pad_top = 8
        pad_bottom = 8
        total_h = pad_top + total_h + pad_bottom

        skew_margin = int(abs(TITLE_SKEW) * total_h) + 20 + TITLE_BOLD_OFFSET + TITLE_STROKE_WIDTH * 2
        shadow_margin_x = abs(TITLE_SHADOW_OFFSET[0]) + TITLE_SHADOW_BLUR * 2
        shadow_margin_y = abs(TITLE_SHADOW_OFFSET[1]) + TITLE_SHADOW_BLUR * 2
        canvas_w = max_w + skew_margin * 2 + shadow_margin_x * 2
        canvas_h = total_h + shadow_margin_y * 2

        shadow_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_img)

        y = pad_top + shadow_margin_y
        for line, font, size in line_specs:
            bbox = shadow_draw.textbbox((0, 0), line, font=font, stroke_width=TITLE_STROKE_WIDTH)
            tw = bbox[2] - bbox[0]
            x = (canvas_w - tw) // 2 + TITLE_SHADOW_OFFSET[0]
            shadow_draw.text(
                (x, y + TITLE_SHADOW_OFFSET[1]), line,
                font=font,
                fill=TITLE_SHADOW_COLOR,
                stroke_width=TITLE_STROKE_WIDTH,
                stroke_fill=TITLE_SHADOW_COLOR,
            )
            y += size + TITLE_LINE_GAP

        if TITLE_SHADOW_BLUR > 0:
            shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(TITLE_SHADOW_BLUR))

        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = pad_top + shadow_margin_y
        for line, font, size in line_specs:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=TITLE_STROKE_WIDTH)
            tw = bbox[2] - bbox[0]
            x = (canvas_w - tw) // 2
            for dx in range(-TITLE_BOLD_OFFSET, TITLE_BOLD_OFFSET + 1):
                for dy in range(-TITLE_BOLD_OFFSET, TITLE_BOLD_OFFSET + 1):
                    draw.text(
                        (x + dx, y + dy), line,
                        font=font,
                        fill=TITLE_COLOR,
                        stroke_width=TITLE_STROKE_WIDTH,
                        stroke_fill=TITLE_STROKE_COLOR,
                    )
            y += size + TITLE_LINE_GAP

        if TITLE_SKEW != 0:
            img = img.transform(img.size, Image.AFFINE, (1, TITLE_SKEW, 0, 0, 1, 0), resample=Image.BICUBIC)
            shadow_img = shadow_img.transform(shadow_img.size, Image.AFFINE, (1, TITLE_SKEW, 0, 0, 1, 0), resample=Image.BICUBIC)

        combined = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        combined.paste(shadow_img, (0, 0), shadow_img)
        combined.paste(img, (0, 0), img)

        bbox = combined.getbbox()
        if bbox:
            combined = combined.crop(bbox)

        final = Image.new("RGBA", (W, combined.size[1]), (0, 0, 0, 0))
        x = (W - combined.size[0]) // 2
        final.paste(combined, (x, 0), combined)
        final.save(out_path)
        return out_path

    TITLE_PNG = os.path.join(TMP_CROP_FOLDER, "_title.png")
    title_path = make_title_png(title1, title2, TITLE_PNG)

    def crop_to_ratio(img, target_w, target_h):
        iw, ih = img.size
        target_ratio = target_w / target_h
        img_ratio = iw / ih
        if img_ratio > target_ratio:
            new_w = int(ih * target_ratio)
            left = (iw - new_w) // 2
            img = img.crop((left, 0, left + new_w, ih))
        else:
            new_h = int(iw / target_ratio)
            top = (ih - new_h) // 2
            img = img.crop((0, top, iw, top + new_h))
        return img.resize((target_w, target_h), Image.LANCZOS)

    raw_images = sorted([
        f for f in os.listdir(IN_FOLDER)
        if f.lower().endswith(IMAGE_EXTS) and "_bg" not in f
    ])
    if not raw_images:
        print("Error: no image file in input folder")
        return 1

    cropped_images = []
    for f in raw_images:
        src = os.path.join(IN_FOLDER, f)
        dst_name = os.path.splitext(f)[0] + f"_{IMG_W}x{IMG_H}.jpg"
        dst = os.path.join(TMP_CROP_FOLDER, dst_name)
        img = Image.open(src).convert("RGB")
        img = crop_to_ratio(img, IMG_W, IMG_H)
        img.save(dst, quality=90)
        cropped_images.append(dst)

    print(f"Images loaded: {len(cropped_images)} images, cropped to {IMG_W}x{IMG_H}")

    def make_blurred_bg(path):
        tmp = os.path.join(TMP_CROP_FOLDER, os.path.basename(path).rsplit(".", 1)[0] + "_bg.jpg")
        if os.path.exists(tmp):
            return tmp
        img = Image.open(path).convert("RGB")
        iw, ih = img.size
        scale = max(W / iw, H / ih)
        img = img.resize((int(iw * scale) + 1, int(ih * scale) + 1), Image.LANCZOS)
        iw, ih = img.size
        left = (iw - W) // 2
        top = (ih - H) // 2
        img = img.crop((left, top, left + W, top + H))
        img = img.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        img.save(tmp, quality=85)
        return tmp

    def wrap_text(text, font, max_width):
        lines = []
        current = ""
        dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(dummy)
        for ch in text:
            test = current + ch
            bbox = d.textbbox((0, 0), test, font=font, stroke_width=SUB_STROKE_WIDTH)
            if bbox[2] - bbox[0] > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
        return lines

    def make_sub_png(text, out_path):
        font = get_font(SUB_FONT_SIZE)
        max_text_w = int(W * SUB_MAX_WIDTH_RATIO)
        lines = wrap_text(text, font, max_text_w)

        dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(dummy)
        max_w = 0
        for line in lines:
            bbox = d.textbbox((0, 0), line, font=font, stroke_width=SUB_STROKE_WIDTH)
            max_w = max(max_w, bbox[2] - bbox[0])

        line_h = SUB_FONT_SIZE + SUB_LINE_GAP
        text_h = line_h * len(lines)
        canvas_w = min(W, max_w + SUB_STROKE_WIDTH * 2 + 10)
        canvas_h = text_h + SUB_STROKE_WIDTH * 2

        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = 0
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=SUB_STROKE_WIDTH)
            tw = bbox[2] - bbox[0]
            x = (canvas_w - tw) // 2
            for dx in range(-SUB_BOLD_OFFSET, SUB_BOLD_OFFSET + 1):
                for dy in range(-SUB_BOLD_OFFSET, SUB_BOLD_OFFSET + 1):
                    draw.text(
                        (x + dx, y + dy), line,
                        font=font,
                        fill=SUB_COLOR,
                        stroke_width=SUB_STROKE_WIDTH,
                        stroke_fill=SUB_STROKE_COLOR,
                    )
            y += line_h

        img.save(out_path)
        return out_path

    sub_pngs = []
    for i, seg in enumerate(subtitle_segments):
        text = seg["text"].strip()
        if not text:
            sub_pngs.append(None)
            continue
        p = os.path.join(TMP_CROP_FOLDER, f"_sub_{i}.png")
        make_sub_png(text, p)
        sub_pngs.append(p)

    def make_clip(path, duration, direction="left_to_right", clip_start=0.0):
        bg_path = make_blurred_bg(path)
        bg = ImageClip(bg_path).with_duration(duration)

        fg_h = int(H * FG_HEIGHT_RATIO)
        fg_w = int(fg_h * IMG_W / IMG_H)
        fg = ImageClip(path).resized((fg_w, fg_h))

        y = (H - fg_h) / 2
        max_shift = max(fg_w - W, 1)
        slide_dur = min(SLIDE_TIME, duration)

        def pos(t, dur=slide_dur, sh=max_shift, d=direction):
            p = min(t / dur, 1.0)
            if d == "left_to_right":
                return (-sh * p, y)
            else:
                return (-sh * (1 - p), y)
        fg = fg.with_duration(duration).with_position(pos)

        layers = [bg, fg]

        if title_path:
            title_clip = ImageClip(title_path).with_duration(duration).with_position(("center", TITLE_TOP_MARGIN))
            layers.append(title_clip)

        clip_end = clip_start + duration
        for i, seg in enumerate(subtitle_segments):
            if sub_pngs[i] is None:
                continue
            s_start = seg["start"]
            s_end = seg["end"]
            if s_end <= clip_start or s_start >= clip_end:
                continue

            local_start = max(0.0, s_start - clip_start)
            local_end = min(duration, s_end - clip_start)
            if local_end <= local_start:
                continue

            sub_clip = ImageClip(sub_pngs[i]).with_duration(local_end - local_start)
            sub_w, sub_h = sub_clip.size
            sub_x = (W - sub_w) // 2
            sub_y = H - SUB_BOTTOM_MARGIN - sub_h
            sub_clip = sub_clip.with_position((sub_x, sub_y)).with_start(local_start)
            layers.append(sub_clip)

        return CompositeVideoClip(layers, size=(W, H))

    audio = AudioFileClip(audio_path)
    total = audio.duration

    clips = []
    t_used = 0.0
    idx = 0
    while t_used < total:
        p = cropped_images[idx % len(cropped_images)]
        direction = "left_to_right" if idx % 2 == 0 else "right_to_left"

        remaining = total - t_used
        seg = SLIDE_TIME + HOLD_TIME + XFADE
        dur = min(seg, remaining + XFADE)
        dur = max(dur, XFADE + 0.1)

        clip = make_clip(p, dur, direction, clip_start=t_used)
        if idx > 0:
            clip = clip.with_effects([vfx.CrossFadeIn(XFADE)])
        clips.append(clip)

        t_used += dur - XFADE
        idx += 1

    print(f"\n{audio_name} ({total:.1f}s) - Clips ready: {len(clips)} clips, slide {SLIDE_TIME}s + hold {HOLD_TIME}s + fade {XFADE}s")

    video = concatenate_videoclips(clips, method="compose", padding=-XFADE)
    video = video.subclipped(0, total).with_audio(audio)

    video.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=os.cpu_count())
    print(f"Done: {os.path.abspath(out_path)}")

    if os.path.exists(TMP_CROP_FOLDER):
        shutil.rmtree(TMP_CROP_FOLDER)
        print(f"\nTemp folder removed: {TMP_CROP_FOLDER}")

    print("\n===== Result =====")
    clip = VideoFileClip(out_path)
    w, h = clip.size
    print(f"{os.path.basename(out_path)}: {w}x{h}, ratio {w/h:.4f}, duration {clip.duration:.2f}s, fps {clip.fps}, audio {clip.audio is not None}")
    clip.close()

    return 0


def run_video_pipeline():
    try:
        return _run_video_pipeline_impl()
    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc()
        print(f"FATAL ERROR: {e}")
        return 1


class Recorder:
    def __init__(self, parent, notebook):
        self.frame = parent
        self.root = parent.winfo_toplevel()
        self.notebook = notebook

        self.clips = []
        self.recording = False
        self.stream = None
        self.chunks = []
        self.peak = 0.0
        self.rec_count = 0

        self.playing = False
        self.play_out = None
        self.play_data = None
        self.play_idx = 0
        self.play_start_sample = 0
        self.play_end_sample = 0

        self.sel_start = None
        self.sel_end = None
        self.drag_anchor = None
        self.press_xy = None
        self.cursor = None

        self.selected_clip = None

        self.insert_mode = False
        self.insert_pos = 0
        self.insert_prepared = False

        self.view_start = 0.0
        self.view_len = DEFAULT_VIEW_LEN
        self._updating_scroll = False

        self._srt_busy = False

        bar = tk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=6)
        tk.Button(bar, text="录制 (R)", width=10, command=self.start_rec).pack(side="left", padx=4)
        self.btn_insert = tk.Button(bar, text="插入录制 (I)", width=12, command=self.start_insert_rec, state="disabled")
        self.btn_insert.pack(side="left", padx=4)
        tk.Button(bar, text="暂停 (P)", width=10, command=self.pause_rec).pack(side="left", padx=4)
        tk.Button(bar, text="导入 (O)", width=10, command=self.import_audio).pack(side="left", padx=4)
        self.btn_srt = tk.Button(bar, text="转字幕 (S)", width=10, command=self.transcribe_wav_to_srt)
        self.btn_srt.pack(side="left", padx=4)
        tk.Button(bar, text="导出 (E)", width=10, command=self.export_dialog).pack(side="left", padx=4)
        tk.Button(bar, text="+ (+)", width=6, command=self.zoom_in).pack(side="left", padx=(20, 2))
        tk.Button(bar, text="− (-)", width=6, command=self.zoom_out).pack(side="left", padx=2)
        tk.Button(bar, text="帮助", width=8, command=self.show_help).pack(side="left", padx=(20, 2))

        self.status = tk.Label(self.frame, text="未录音    时长：0.0 秒")
        self.status.pack(anchor="w", padx=8)

        self.fig = Figure(figsize=(10, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("sec")
        self.ax.set_yticks([])
        self.ax.set_ylim(-1.0, 1.0)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("button_release_event", self.on_release)

        self.scroll = tk.Scrollbar(self.frame, orient="horizontal", command=self.on_scroll)
        self.scroll.pack(fill="x", padx=6, pady=(0, 6))

        self.root.bind("<Delete>", self.on_delete)
        self.root.bind("<space>", self.on_space)
        self.root.bind("<KeyPress-r>", self.on_key_r)
        self.root.bind("<KeyPress-R>", self.on_key_r)
        self.root.bind("<KeyPress-p>", self.on_key_p)
        self.root.bind("<KeyPress-P>", self.on_key_p)
        self.root.bind("<KeyPress-o>", self.on_key_o)
        self.root.bind("<KeyPress-O>", self.on_key_o)
        self.root.bind("<KeyPress-s>", self.on_key_s)
        self.root.bind("<KeyPress-S>", self.on_key_s)
        self.root.bind("<KeyPress-e>", self.on_key_e)
        self.root.bind("<KeyPress-E>", self.on_key_e)
        self.root.bind("<KeyPress-i>", self.on_key_i)
        self.root.bind("<KeyPress-I>", self.on_key_i)
        self.root.bind("<KeyPress-plus>", self.on_key_plus)
        self.root.bind("<KeyPress-equal>", self.on_key_plus)
        self.root.bind("<KeyPress-KP_Add>", self.on_key_plus)
        self.root.bind("<KeyPress-minus>", self.on_key_minus)
        self.root.bind("<KeyPress-KP_Subtract>", self.on_key_minus)

        self._reset_view()
        self._draw()
        self._tick()

    def _tab_active(self):
        try:
            return self.notebook.select() == str(self.frame)
        except Exception:
            return True

    def on_key_r(self, event=None):
        if not self._tab_active():
            return
        self.start_rec(); return "break"
    def on_key_p(self, event=None):
        if not self._tab_active():
            return
        self.pause_rec(); return "break"
    def on_key_o(self, event=None):
        if not self._tab_active():
            return
        self.import_audio(); return "break"
    def on_key_s(self, event=None):
        if not self._tab_active():
            return
        self.transcribe_wav_to_srt(); return "break"
    def on_key_e(self, event=None):
        if not self._tab_active():
            return
        self.export_dialog(); return "break"
    def on_key_i(self, event=None):
        if not self._tab_active():
            return
        if str(self.btn_insert["state"]) == "normal":
            self.start_insert_rec()
        return "break"
    def on_key_plus(self, event=None):
        if not self._tab_active():
            return
        self.zoom_in(); return "break"
    def on_key_minus(self, event=None):
        if not self._tab_active():
            return
        self.zoom_out(); return "break"

    def on_space(self, event=None):
        if not self._tab_active():
            return
        if self.recording:
            return
        if self.playing:
            self.stop_play()
        else:
            self.start_play()
        return "break"

    def on_delete(self, event=None):
        if not self._tab_active():
            return
        if self.recording or self.playing:
            return
        if self.selected_clip is not None and 0 <= self.selected_clip < len(self.clips):
            c = self.clips.pop(self.selected_clip)
            self.selected_clip = None
            self._snap_clips()
            self._adjust_cursor_after_delete_int(len(c["data"]), int(c["start"] * SR))
            self._reset_view()
            self._draw()
            self.status.config(text=f"已删除整块    时长：{self._total_dur():.2f} 秒")
            self._update_insert_button()
            return
        if self.sel_start is None or self.sel_end is None:
            return
        s = min(self.sel_start, self.sel_end)
        e = max(self.sel_start, self.sel_end)
        if s >= e:
            return
        self._delete_range(s, e)
        self.sel_start = self.sel_end = None
        self._snap_clips()
        self._reset_view()
        self._draw()
        self.status.config(text=f"已删除选区    时长：{self._total_dur():.2f} 秒")
        self._update_insert_button()

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用帮助")
        win.geometry("680x600")
        txt = tk.Text(win, wrap="word", font=("Microsoft YaHei", 10))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", HELP_TEXT)
        txt.config(state="disabled")

    def _merged(self):
        if not self.clips:
            return np.zeros(0, dtype=np.float32)
        clips_sorted = sorted(self.clips, key=lambda c: c["start"])
        end = max(c["start"] + len(c["data"]) / SR for c in clips_sorted)
        total = int(end * SR) + 1
        out = np.zeros(total, dtype=np.float32)
        for c in clips_sorted:
            s = int(c["start"] * SR)
            e = s + len(c["data"])
            out[s:e] += c["data"]
        return out

    def _total_dur(self):
        if not self.clips:
            return 0.0
        return max(c["start"] + len(c["data"]) / SR for c in self.clips)

    def _snap_clips(self):
        if not self.clips:
            return
        self.clips.sort(key=lambda c: c["start"])
        t = 0.0
        for c in self.clips:
            c["start"] = t
            t += len(c["data"]) / SR

    def _reset_view(self):
        total = self._total_dur()
        if total <= 0:
            self.view_start = 0.0
            self.view_len = DEFAULT_VIEW_LEN
        else:
            self.view_start = 0.0
            self.view_len = max(total, 0.1)
        self._sync_scroll()

    def _clamp_view(self):
        total = self._total_dur()
        if total <= 0:
            self.view_start = 0.0
            return
        self.view_len = max(0.05, self.view_len)
        max_start = max(total - self.view_len, 0.0)
        if self.view_start > max_start:
            self.view_start = max_start
        if self.view_start < 0:
            self.view_start = 0.0

    def _sync_scroll(self):
        total = self._total_dur()
        self._updating_scroll = True
        try:
            if total <= 0 or self.view_len >= total:
                self.scroll.set(0.0, 1.0)
            else:
                lo = self.view_start / total
                hi = (self.view_start + self.view_len) / total
                self.scroll.set(lo, hi)
        finally:
            self._updating_scroll = False

    def on_scroll(self, *args):
        if self._updating_scroll or self.playing:
            return
        total = self._total_dur()
        if total <= 0:
            return
        if args[0] == "moveto":
            self.view_start = float(args[1]) * total
        elif args[0] == "scroll":
            self.view_start += int(args[1]) * self.view_len * 0.1
        self._clamp_view()
        self._sync_scroll()
        self._draw()

    def zoom_in(self):
        self._zoom(0.5)

    def zoom_out(self):
        self._zoom(2.0)

    def _zoom(self, factor):
        if self.playing:
            return
        total = self._total_dur()
        if total <= 0:
            return
        center = self.view_start + self.view_len / 2
        new_len = max(0.05, min(self.view_len * factor, max(total, 0.05)))
        self.view_len = new_len
        self.view_start = center - new_len / 2
        self._clamp_view()
        self._sync_scroll()
        self._draw()

    def _update_insert_button(self):
        if self.recording or self.playing or self.cursor is None:
            self.btn_insert.config(state="disabled")
        else:
            self.btn_insert.config(state="normal")

    def start_rec(self):
        if self.recording:
            return
        if self.playing:
            self.stop_play()
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None
        try:
            self.chunks = []
            self.peak = 0.0
            self.rec_count += 1
            self.insert_mode = False
            self.insert_prepared = False
            self.stream = sd.InputStream(samplerate=SR, channels=CH, dtype="float32", callback=self._cb)
            self.stream.start()
            self.recording = True
            self.selected_clip = None
            self.status.config(text="录音中…")
            self._update_insert_button()
        except Exception as e:
            messagebox.showerror("录音失败", str(e))
            self.recording = False

    def start_insert_rec(self):
        if self.recording or self.playing:
            return
        if self.cursor is None:
            return
        self.insert_mode = True
        self.insert_pos = int(self.cursor)
        self.insert_prepared = False
        self.rec_count += 1
        try:
            self.chunks = []
            self.peak = 0.0
            self.stream = sd.InputStream(samplerate=SR, channels=CH, dtype="float32", callback=self._cb)
            self.stream.start()
            self.recording = True
            self.selected_clip = None
            self.status.config(text="插入录音中…")
            self._update_insert_button()
        except Exception as e:
            messagebox.showerror("录音失败", str(e))
            self.recording = False
            self.insert_mode = False

    def _cb(self, indata, frames, time_info, status):
        self.chunks.append(indata.copy())
        m = float(np.abs(indata).max()) if indata.size else 0.0
        if m > self.peak:
            self.peak = m

    def _prepare_insert_split(self):
        if not self.insert_mode or self.insert_prepared:
            return
        self.insert_prepared = True
        pos = self.insert_pos
        new_clips = []
        for c in self.clips:
            cs = int(c["start"] * SR)
            ce = cs + len(c["data"])
            if pos <= cs or pos >= ce:
                new_clips.append(c)
                continue
            cut = pos - cs
            left_data = c["data"][:cut]
            right_data = c["data"][cut:]
            if len(left_data) > 0:
                new_clips.append({"start": c["start"], "data": left_data, "color": c["color"]})
            if len(right_data) > 0:
                new_clips.append({"start": pos / SR, "data": right_data, "color": c["color"]})
        self.clips = new_clips

    def pause_rec(self):
        if not self.recording:
            return
        self.recording = False
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass
        self.stream = None

        new = None
        if self.chunks:
            new = np.concatenate(self.chunks, axis=0).reshape(-1).astype(np.float32)

        if self.insert_mode and new is not None and len(new) > 0:
            self._prepare_insert_split()
            new_len = len(new) / SR
            pos_sec = self.insert_pos / SR
            for c in self.clips:
                if c["start"] >= pos_sec - 1e-9:
                    c["start"] += new_len
            color = CLIP_COLORS[len(self.clips) % len(CLIP_COLORS)]
            self.clips.append({"start": pos_sec, "data": new, "color": color})
            self._snap_clips()
        elif new is not None and len(new) > 0:
            start = self._total_dur()
            color = CLIP_COLORS[len(self.clips) % len(CLIP_COLORS)]
            self.clips.append({"start": start, "data": new, "color": color})
            self._snap_clips()

        self.chunks = []
        self.insert_mode = False
        self.insert_prepared = False
        self.sel_start = self.sel_end = None
        self.selected_clip = None
        self.status.config(text="已暂停")
        self._reset_view()
        self._draw()
        self._update_insert_button()

    def _live_array(self):
        if self.chunks:
            live = np.concatenate(self.chunks, axis=0).reshape(-1).astype(np.float32)
        else:
            live = np.zeros(0, dtype=np.float32)

        if self.insert_mode:
            if len(live) > 0:
                self._prepare_insert_split()
            new_len = len(live) / SR
            pos_sec = self.insert_pos / SR
            base = []
            for c in self.clips:
                if c["start"] >= pos_sec - 1e-9:
                    base.append({"start": c["start"] + new_len, "data": c["data"], "color": c["color"]})
                else:
                    base.append(c)
            if len(live) > 0:
                color = CLIP_COLORS[len(self.clips) % len(CLIP_COLORS)]
                base.append({"start": pos_sec, "data": live, "color": color})
            clips = base
        else:
            if len(live) > 0:
                start = self._total_dur()
                color = CLIP_COLORS[len(self.clips) % len(CLIP_COLORS)]
                clips = self.clips + [{"start": start, "data": live, "color": color}]
            else:
                clips = self.clips

        if not clips:
            return np.zeros(0, dtype=np.float32), clips
        end = max(c["start"] + len(c["data"]) / SR for c in clips)
        total = int(end * SR) + 1
        out = np.zeros(total, dtype=np.float32)
        for c in sorted(clips, key=lambda x: x["start"]):
            s = int(c["start"] * SR)
            e = s + len(c["data"])
            out[s:e] += c["data"]
        return out, clips

    def _tick(self):
        if self.recording:
            live, live_clips = self._live_array()
            dur = len(live) / SR
            tag = "插入录音中…" if self.insert_mode else "录音中…"
            self.status.config(text=f"{tag}  时长：{dur:.1f} 秒  峰值：{self.peak:.4f}")
            if self.insert_mode:
                tail = self.insert_pos / SR + sum(len(c) for c in self.chunks) / SR
                if tail > self.view_start + self.view_len * 0.85:
                    self.view_start = max(0.0, tail - self.view_len * 0.85)
            else:
                self.view_start = 0.0
                self.view_len = max(dur, 0.1)
            self._clamp_view()
            self._sync_scroll()
            self._draw(live, live_clips=live_clips)
        elif self.playing:
            self._update_play_head()
        self.root.after(50, self._tick)

    def start_play(self):
        merged = self._merged()
        if len(merged) == 0:
            return
        total_samples = len(merged)
        start = self.cursor if self.cursor is not None else 0
        start = max(0, min(start, total_samples - 1))
        self.play_data = merged
        self.play_start_sample = start
        self.play_end_sample = total_samples
        self.play_idx = start
        self.playing = True
        self._update_insert_button()

        def callback(outdata, frames, time_info, status):
            remaining = self.play_end_sample - self.play_idx
            n = min(frames, remaining)
            if n <= 0:
                outdata[:] = 0
                raise sd.CallbackStop
            chunk = self.play_data[self.play_idx:self.play_idx + n]
            outdata[:n, 0] = chunk
            if n < frames:
                outdata[n:] = 0
            self.play_idx += n

        try:
            self.play_out = sd.OutputStream(samplerate=SR, channels=CH, dtype="float32",
                                            callback=callback)
            self.play_out.start()
        except Exception:
            self.playing = False
            self.play_out = None
            self._update_insert_button()

    def stop_play(self, auto=False):
        if not self.playing:
            return
        try:
            if self.play_out is not None:
                self.play_out.stop(); self.play_out.close()
        except Exception:
            pass
        self.play_out = None
        self.playing = False
        pos_idx = min(self.play_idx, len(self.play_data) if self.play_data is not None else 0)
        self.cursor = pos_idx
        self.status.config(text=f"光标：{pos_idx/SR:.2f} 秒    时长：{self._total_dur():.2f} 秒")
        self._draw()
        self._update_insert_button()

    def _update_play_head(self):
        if not self.playing or self.play_data is None:
            return
        pos = self.play_idx
        total = len(self.play_data)
        if pos >= total:
            self.stop_play(auto=True)
            return
        self.cursor = pos
        pos_sec = pos / SR
        total_sec = self._total_dur()

        if pos_sec > self.view_start + self.view_len * 0.85:
            self.view_start = pos_sec - self.view_len * 0.85
            self._clamp_view()
            self._sync_scroll()
        elif pos_sec < self.view_start:
            self.view_start = max(pos_sec - self.view_len * 0.15, 0.0)
            self._clamp_view()
            self._sync_scroll()

        self.status.config(text=f"播放中…  {pos_sec:.2f} / {total_sec:.2f} 秒")
        self._draw()

    def import_audio(self):
        if self.recording:
            messagebox.showwarning("提示", "请先停止录音")
            return
        if self.playing:
            self.stop_play()
        path = filedialog.askopenfilename(
            title="导入 WAV",
            filetypes=[("WAV", "*.wav"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            data = _load_wav(path)
        except Exception as e:
            messagebox.showerror("导入失败", str(e))
            return
        if len(data) == 0:
            messagebox.showwarning("提示", "文件为空")
            return

        color = CLIP_COLORS[len(self.clips) % len(CLIP_COLORS)]

        if self.cursor is not None:
            self.insert_mode = True
            self.insert_pos = int(self.cursor)
            self.insert_prepared = False
            self._prepare_insert_split()
            pos_sec = self.insert_pos / SR
            new_len = len(data) / SR
            for c in self.clips:
                if c["start"] >= pos_sec - 1e-9:
                    c["start"] += new_len
            self.clips.append({"start": pos_sec, "data": data, "color": color, "src": path})
            self.insert_mode = False
            self.insert_prepared = False
        else:
            start = self._total_dur()
            self.clips.append({"start": start, "data": data, "color": color, "src": path})

        self._snap_clips()
        if self.cursor is not None:
            self.cursor = min(self.cursor, len(self._merged()))
        self._reset_view()
        self._draw()
        self.status.config(text=f"已导入：{os.path.basename(path)}    时长：{self._total_dur():.2f} 秒")
        self._update_insert_button()

    def transcribe_wav_to_srt(self):
        if self._srt_busy:
            messagebox.showinfo("提示", "正在转字幕，请稍候…")
            return
        if self.recording:
            messagebox.showwarning("提示", "请先停止录音")
            return
        if self.playing:
            self.stop_play()

        path = filedialog.askopenfilename(
            title="选择要转字幕的 WAV 文件",
            filetypes=[("WAV", "*.wav"), ("所有文件", "*.*")],
        )
        if not path:
            return
        if not path.lower().endswith(".wav"):
            messagebox.showwarning("提示", "请选择 .wav 文件")
            return
        if not os.path.exists(path):
            messagebox.showerror("错误", "文件不存在")
            return

        out_dir = os.path.dirname(os.path.abspath(path))
        base = os.path.splitext(os.path.basename(path))[0]
        srt_path = os.path.join(out_dir, base + ".srt")

        self._srt_busy = True
        self.btn_srt.config(state="disabled", text="转字幕中…")
        self.status.config(text=f"转字幕中… {os.path.basename(path)}  加载模型…")

        def worker():
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
                self.root.after(0, lambda: self.status.config(
                    text=f"转字幕中… {os.path.basename(path)}  识别中（较慢，请稍候）…"))

                segments, info = model.transcribe(
                    path,
                    language=WHISPER_LANGUAGE,
                    initial_prompt=WHISPER_PROMPT if WHISPER_PROMPT.strip() else None,
                    vad_filter=False,
                    beam_size=5,
                    condition_on_previous_text=False,
                )

                result = []
                for seg in segments:
                    text = seg.text.strip()
                    if _CC_T2S is not None and text:
                        try:
                            text = _CC_T2S.convert(text)
                        except Exception:
                            pass
                    result.append({
                        "start": round(seg.start, 2),
                        "end": round(seg.end, 2),
                        "text": text,
                    })

                _write_srt(result, srt_path)
                self.root.after(0, lambda: self._on_srt_done(srt_path, len(result), None))
            except Exception as e:
                traceback.print_exc()
                self.root.after(0, lambda: self._on_srt_done(srt_path, 0, e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_srt_done(self, srt_path, n_seg, err):
        self._srt_busy = False
        self.btn_srt.config(state="normal", text="转字幕 (S)")
        if err is not None:
            msg = str(err)
            if "LocalEntryNotFoundError" in msg or "models" in msg.lower():
                msg += "\n\n请检查 models/ 四个文件是否齐全（config.json, model.bin, tokenizer.json, vocabulary.txt）"
            self.status.config(text=f"转字幕失败：{msg[:80]}")
            messagebox.showerror("转字幕失败", msg)
            return
        self.status.config(text=f"字幕已生成：{os.path.basename(srt_path)}（{n_seg} 段）")
        messagebox.showinfo("转字幕完成", f"已生成：\n{srt_path}\n\n共 {n_seg} 段字幕。")

    def _normalize_loudness(self, audio):
        if len(audio) == 0:
            raise RuntimeError("没有可导出的音频")
        audio64 = audio.astype(np.float64)
        if len(audio64) / SR < MIN_LUFS_SECONDS:
            return audio, "short-skip"
        if not HAS_PYLN:
            raise RuntimeError("未安装 pyloudnorm，无法做 -14 LUFS 响度标准化。\n请执行：pip install pyloudnorm 后重启程序。")
        meter = pyln.Meter(SR)
        loudness = meter.integrated_loudness(audio64)
        if not np.isfinite(loudness):
            raise RuntimeError("LUFS 计算失败（音频可能整段静音或数据异常）。")
        gain_db = TARGET_LUFS - loudness
        gain = 10 ** (gain_db / 20.0)
        out = audio64 * gain
        peak = float(np.max(np.abs(out))) if len(out) > 0 else 0.0
        if peak > 0:
            peak_db = 20 * np.log10(peak)
            if peak_db > TARGET_TRUE_PEAK_DB:
                limit_gain = 10 ** ((TARGET_TRUE_PEAK_DB - peak_db) / 20.0)
                out = out * limit_gain
        return out.astype(np.float32), "lufs-done"

    def _write_mp3(self, path, audio, bitrate=MP3_BITRATE):
        int16 = np.clip(audio, -1.0, 1.0)
        int16 = (int16 * 32767).astype(np.int16)
        enc = lameenc.Encoder()
        enc.set_bit_rate(bitrate)
        enc.set_in_sample_rate(SR)
        enc.set_channels(CH)
        enc.set_quality(2)
        data = enc.encode(int16.tobytes())
        data += enc.flush()
        with open(path, "wb") as f:
            f.write(data)

    def export_dialog(self):
        if not self.clips:
            return
        if self.playing:
            self.stop_play()

        os.makedirs(IN_FOLDER, exist_ok=True)

        win = tk.Toplevel(self.root)
        win.title("导出到 input/")
        win.geometry("360x220")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="文件名（不含扩展名）：", font=("Microsoft YaHei", 11)).pack(pady=(16, 4))
        entry_name = tk.Entry(win, width=32, font=("Arial", 11))
        entry_name.pack(pady=4)
        entry_name.insert(0, "recording")
        entry_name.focus_set()

        tk.Label(win, text=f"保存位置：{IN_FOLDER}", fg="gray", font=("Arial", 9)).pack(pady=4)

        frm = tk.Frame(win)
        frm.pack(pady=10)

        def do_wav():
            name = entry_name.get().strip()
            if not name:
                messagebox.showwarning("提示", "文件名不能为空", parent=win)
                return
            path = os.path.join(IN_FOLDER, sanitize_filename(name) + ".wav")
            win.destroy()
            self._do_export_to(path, "wav")

        def do_mp3():
            if not HAS_LAME:
                messagebox.showerror("缺少组件", "未安装 lameenc，无法导出 MP3。\n请执行：pip install lameenc", parent=win)
                return
            name = entry_name.get().strip()
            if not name:
                messagebox.showwarning("提示", "文件名不能为空", parent=win)
                return
            path = os.path.join(IN_FOLDER, sanitize_filename(name) + ".mp3")
            win.destroy()
            self._do_export_to(path, "mp3")

        tk.Button(frm, text="WAV（无损）", width=14, command=do_wav).pack(side="left", padx=8)
        tk.Button(frm, text="MP3（方便听）", width=14, command=do_mp3).pack(side="left", padx=8)
        tk.Button(win, text="取消", width=8, command=win.destroy).pack(pady=8)

    def _do_export_to(self, path, fmt):
        if os.path.exists(path):
            if not messagebox.askyesno("文件已存在", f"{os.path.basename(path)} 已存在，覆盖吗？"):
                return
        try:
            out = self._merged()
            norm, _ = self._normalize_loudness(out)
            if fmt == "wav":
                sf.write(path, norm, SR)
            else:
                self._write_mp3(path, norm)
            self.status.config(text=f"已导出：{os.path.basename(path)}    时长：{self._total_dur():.2f} 秒")
            messagebox.showinfo("导出完成", f"已保存到：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _adjust_cursor_after_delete_int(self, cut_len, cut_start):
        if self.cursor is None:
            return
        if self.cursor >= cut_start + cut_len:
            self.cursor -= cut_len
        elif self.cursor > cut_start:
            self.cursor = cut_start

    def _delete_range(self, s, e):
        cut_len = e - s
        new_clips = []
        for c in self.clips:
            cs = int(c["start"] * SR)
            ce = cs + len(c["data"])
            if ce <= s or cs >= e:
                new_clips.append(c)
                continue
            a = max(cs, s) - cs
            b = min(ce, e) - cs
            left = c["data"][:a]
            right = c["data"][b:]
            remain = np.concatenate([left, right])
            if len(remain) > 0:
                new_clips.append({"start": c["start"], "data": remain, "color": c["color"]})
        self.clips = [c for c in new_clips if len(c["data"]) > 0]
        if self.cursor is not None:
            if self.cursor >= e:
                self.cursor -= cut_len
            elif self.cursor > s:
                self.cursor = s

    def _draw(self, data=None, live_clips=None):
        if data is None:
            data = self._merged()
        clips_to_draw = live_clips if live_clips is not None else self.clips

        self.ax.clear()
        self.ax.set_yticks([])
        self.ax.set_xlabel("sec")
        self.ax.set_ylim(-1.0, 1.0)
        self.ax.set_xlim(self.view_start, self.view_start + self.view_len)

        y_lo, y_hi = -1.0, 1.0
        top_lo = y_hi - (y_hi - y_lo) * TOP_ZONE_RATIO

        if clips_to_draw:
            vis_s = self.view_start
            vis_e = self.view_start + self.view_len
            for idx, c in enumerate(clips_to_draw):
                cs = c["start"]
                ce = cs + len(c["data"]) / SR
                if ce < vis_s or cs > vis_e:
                    continue
                self.ax.axvspan(cs, ce, color=c["color"], alpha=0.7, zorder=0)
                self.ax.add_patch(Rectangle((cs, top_lo), ce - cs, y_hi - top_lo,
                                            facecolor="#94a3b8", alpha=0.55, edgecolor="none", zorder=1))
                if self.selected_clip is not None and not self.recording and not self.playing and idx == self.selected_clip:
                    self.ax.add_patch(Rectangle((cs, -1.0), ce - cs, 2.0,
                                                facecolor="none", edgecolor="#ef4444", linewidth=2.0, zorder=4))
                self.ax.axvline(cs, color="#64748b", linewidth=0.6, zorder=2)
                self.ax.axvline(ce, color="#64748b", linewidth=0.6, zorder=2)

                seg_s = int(max(cs, vis_s) * SR) - int(cs * SR)
                seg_e = int(min(ce, vis_e) * SR) - int(cs * SR)
                seg_s = max(0, seg_s)
                seg_e = max(seg_s + 1, min(seg_e, len(c["data"])))
                seg = c["data"][seg_s:seg_e]
                m = len(seg)
                if m > 0:
                    max_points = 2000
                    base_t = cs + seg_s / SR
                    if m > max_points:
                        step = max(1, m // max_points)
                        trimmed = seg[: step * (m // step)].reshape(-1, step)
                        upper = trimmed.max(axis=1) * 0.78
                        lower = trimmed.min(axis=1) * 0.78
                        x = base_t + np.arange(len(upper)) * step / SR
                        self.ax.fill_between(x, lower, upper, color="#1d4ed8", linewidth=0, zorder=3)
                    else:
                        x = base_t + np.arange(m) / SR
                        self.ax.plot(x, seg * 0.78, color="#1d4ed8", linewidth=0.6, zorder=3)

            if self.sel_start is not None and self.sel_end is not None and not self.recording:
                s = min(self.sel_start, self.sel_end) / SR
                e = max(self.sel_start, self.sel_end) / SR
                self.ax.axvspan(s, e, color="orange", alpha=0.35, zorder=5)

            if self.cursor is not None and not self.recording:
                self.ax.axvline(self.cursor / SR, color="red", linewidth=1.4, zorder=6)
        else:
            self.ax.set_xlim(0, DEFAULT_VIEW_LEN)
        self.canvas.draw_idle()

    def _hit_clip(self, xdata, ydata):
        if not self.clips:
            return None, False
        y_lo, y_hi = -1.0, 1.0
        top_lo = y_hi - (y_hi - y_lo) * TOP_ZONE_RATIO
        for idx, c in enumerate(self.clips):
            cs = c["start"]
            ce = cs + len(c["data"]) / SR
            if cs <= xdata <= ce:
                return idx, (ydata >= top_lo)
        return None, False

    def _x_to_sample(self, event):
        if event.xdata is None:
            return None
        idx = int(event.xdata * SR)
        total = len(self._merged())
        return max(0, min(idx, total))

    def on_press(self, event):
        if event.inaxes != self.ax or self.recording or self.playing:
            return
        if event.button != 1:
            return
        self.press_xy = (event.x, event.y)
        if event.xdata is None or event.ydata is None:
            return
        clip_idx, in_top = self._hit_clip(event.xdata, event.ydata)
        if clip_idx is not None and in_top:
            self.selected_clip = clip_idx
            self.sel_start = self.sel_end = None
            self.status.config(text=f"已选中区块 #{clip_idx+1}    时长：{self._total_dur():.2f} 秒")
            self._draw()
            return
        idx = self._x_to_sample(event)
        if idx is None:
            return
        self.drag_anchor = idx
        self.sel_start = idx
        self.sel_end = idx
        self.selected_clip = None

    def on_motion(self, event):
        if self.drag_anchor is None or event.inaxes != self.ax:
            return
        idx = self._x_to_sample(event)
        if idx is None:
            return
        self.sel_end = idx
        self._draw()

    def on_release(self, event):
        if self.press_xy is None and self.drag_anchor is None:
            return
        moved = False
        if self.press_xy is not None and event.x is not None:
            moved = (abs(event.x - self.press_xy[0]) > 3 or abs(event.y - self.press_xy[1]) > 3)
        if self.drag_anchor is not None:
            if not moved:
                self.cursor = self.drag_anchor
                self.sel_start = self.sel_end = None
                self.selected_clip = None
                self.status.config(text=f"光标：{self.cursor/SR:.2f} 秒    时长：{self._total_dur():.2f} 秒")
            else:
                if self.sel_start == self.sel_end:
                    self.sel_start = self.sel_end = None
                if self.sel_start is not None and self.sel_end is not None:
                    s = min(self.sel_start, self.sel_end) / SR
                    e = max(self.sel_start, self.sel_end) / SR
                    self.status.config(text=f"选区：{s:.2f} ~ {e:.2f} 秒    时长：{self._total_dur():.2f} 秒")
        self.drag_anchor = None
        self.press_xy = None
        self._draw()
        self._update_insert_button()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("makevideo")
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ico = os.path.join(base, "myicon.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.tab1 = tk.Frame(self.notebook)
        self.notebook.add(self.tab1, text="录音编辑")

        self.tab2 = tk.Frame(self.notebook)
        self.notebook.add(self.tab2, text="制作视频")

        self.recorder = Recorder(self.tab1, self.notebook)

        title_frame = tk.Frame(self.tab2)
        title_frame.pack(pady=8)

        tk.Label(title_frame, text="Title:", font=("Arial", 10)).grid(
            row=0, column=0, sticky="e", padx=4, pady=3)
        self.entry_outname = tk.Entry(title_frame, width=32, font=("Arial", 10))
        self.entry_outname.insert(0, "")
        self.entry_outname.grid(row=0, column=1, padx=4, pady=3)

        tk.Label(title_frame, text="事件:", font=("Arial", 10)).grid(
            row=1, column=0, sticky="e", padx=4, pady=3)
        self.entry_title1 = tk.Entry(title_frame, width=32, font=("Arial", 10))
        self.entry_title1.insert(0, TITLE1)
        self.entry_title1.grid(row=1, column=1, padx=4, pady=3)

        tk.Label(title_frame, text="我想说的:", font=("Arial", 10)).grid(
            row=2, column=0, sticky="e", padx=4, pady=3)
        self.entry_title2 = tk.Entry(title_frame, width=32, font=("Arial", 10))
        self.entry_title2.insert(0, TITLE2)
        self.entry_title2.grid(row=2, column=1, padx=4, pady=3)

        tk.Label(self.tab2,
                 text="(Title 留空 = 用音频同名；事件/我想说的 留空 = 不显示该行)",
                 fg="gray", font=("Arial", 9)).pack()

        tk.Label(self.tab2, text="需要 input/ 里有同名 .srt 字幕文件",
                 font=("Arial", 11), fg="#b45309").pack(pady=6)

        row_btns = tk.Frame(self.tab2)
        row_btns.pack(pady=6)
        self.btn_shot = tk.Button(row_btns, text="截图 (F1)", width=14, height=2,
                                  command=self.do_start_shot)
        self.btn_shot.pack(side="left", padx=6)
        self.btn_clear = tk.Button(row_btns, text="清空 input 图片", width=14, height=2,
                                   command=self.do_clear_images)
        self.btn_clear.pack(side="left", padx=6)

        self.btn_video = tk.Button(self.tab2, text="开始制作视频",
                                   command=self.do_start_video, height=2, width=24)
        self.btn_video.pack(pady=8)

        self.progress = ttk.Progressbar(self.tab2, orient="horizontal",
                                        length=460, mode="determinate", maximum=100)
        self.progress.pack(pady=10)
        self.status_label = tk.Label(self.tab2, text="Ready", font=("Arial", 10))
        self.status_label.pack(pady=5)

        self.btn_open_output = tk.Button(self.tab2, text="打开 output 文件夹",
                                         command=self.do_open_output, height=1, width=24)
        self.btn_open_output.pack(pady=6)

        self.shot_tool = ScreenshotTool(root)

        root.bind("<F1>", lambda e: self.do_start_shot())
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.proc = None
        self.log_queue = queue.Queue()
        self.poll_proc = None
        self.poll_queue = None
        self._creep_timer = None
        self._creep_max = 0
        self._wait_count = 0

    def do_start_shot(self):
        if not self.shot_tool.enabled:
            return
        self.shot_tool.start_capture()

    def do_clear_images(self):
        if not os.path.isdir(IN_FOLDER):
            self.shot_tool._show_toast(success=False, text="input folder not found")
            return
        imgs = [f for f in os.listdir(IN_FOLDER) if f.lower().endswith(IMAGE_EXTS)]
        if not imgs:
            self.shot_tool._show_toast(success=False, text="No images in input")
            return
        if not messagebox.askyesno(
            "Confirm",
            f"Delete {len(imgs)} image file(s) in input/ ?\n\nAudio files will NOT be touched."
        ):
            return
        deleted = 0
        for f in imgs:
            try:
                os.remove(os.path.join(IN_FOLDER, f))
                deleted += 1
            except Exception as e:
                print(f"Delete failed {f}: {e}")
        self.shot_tool._show_toast(success=True, text=f"Deleted {deleted} image(s)")

    def do_open_output(self):
        try:
            os.makedirs(OUT_FOLDER, exist_ok=True)
        except Exception:
            pass
        try:
            if sys.platform.startswith("win"):
                os.startfile(OUT_FOLDER)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", OUT_FOLDER])
            else:
                subprocess.Popen(["xdg-open", OUT_FOLDER])
        except Exception as e:
            self.status_label.config(text=f"Open failed: {e}")

    def set_running(self, running):
        state = "disabled" if running else "normal"
        self.btn_video.config(state=state, text="Running..." if running else "开始制作视频")
        self.btn_shot.config(state=state)
        self.btn_clear.config(state=state)
        self.entry_outname.config(state=state)
        self.entry_title1.config(state=state)
        self.entry_title2.config(state=state)
        self.shot_tool.enabled = not running
        if not running:
            self._stop_creep()

    def _start_creep(self, max_val):
        self._creep_max = max_val
        if self._creep_timer:
            try:
                self.root.after_cancel(self._creep_timer)
            except Exception:
                pass
            self._creep_timer = None
        self._creep_tick()

    def _creep_tick(self):
        try:
            cur = float(self.progress["value"])
        except Exception:
            cur = 0.0
        if cur < self._creep_max:
            self.progress["value"] = min(cur + 0.2, self._creep_max)
            self._creep_timer = self.root.after(1000, self._creep_tick)
        else:
            self._creep_timer = None

    def _stop_creep(self):
        if self._creep_timer:
            try:
                self.root.after_cancel(self._creep_timer)
            except Exception:
                pass
            self._creep_timer = None

    def do_start_video(self):
        if self.proc is not None:
            return
        if not os.path.isdir(IN_FOLDER):
            self.status_label.config(text="input folder not found")
            return

        self.progress["value"] = 0
        self.status_label.config(text="Starting...")
        self.set_running(True)
        self._wait_count = 0

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env[ENV_TITLE1] = self.entry_title1.get()
        env[ENV_TITLE2] = self.entry_title2.get()
        env[ENV_OUTNAME] = self.entry_outname.get()

        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", os.path.abspath(__file__), "--run-video"],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except Exception as e:
            self.proc = None
            self.set_running(False)
            self.status_label.config(text=f"Start failed: {e}")
            return

        def reader():
            buf = ""
            try:
                while True:
                    ch = self.proc.stdout.read(1)
                    if not ch:
                        break
                    if ch in ("\n", "\r"):
                        if buf.strip():
                            self.log_queue.put(buf)
                        buf = ""
                    else:
                        buf += ch
            except Exception:
                pass
            if buf.strip():
                self.log_queue.put(buf)
            self.log_queue.put(None)

        threading.Thread(target=reader, daemon=True).start()

        self.poll_queue = self.root.after(100, self._drain_queue)
        self.poll_proc = self.root.after(300, self._check_proc)

    def _drain_queue(self):
        got_end = False
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line is None:
                    got_end = True
                    break
                try:
                    print(line)
                except Exception:
                    pass
                self._update_progress_by_line(line)
        except queue.Empty:
            pass

        if not got_end:
            self.poll_queue = self.root.after(100, self._drain_queue)
        else:
            self.poll_queue = None

    def _update_progress_by_line(self, line):
        pct = None
        text = None
        creep_to = None

        if line.startswith("Font resolved:"):
            pct, text = 1, "检查字体…"
        elif line.startswith("Title1:"):
            pct, text = 2, "读取标题…"
        elif line.startswith("OutName:"):
            pct, text = 2, "读取输出名…"
        elif line.startswith("Audio:"):
            pct, text = 5, "检查素材…"
        elif line.startswith("Output will be:"):
            pct, text = 8, "输出名已确定"
        elif line.startswith("Subtitle source:"):
            pct, text = 15, "读取字幕…"
        elif line.startswith("Subtitle loaded:"):
            pct, text = 30, "字幕已加载"
        elif line.startswith("Images loaded:"):
            pct, text = 50, "处理图片…"
        elif "Clips ready" in line:
            pct, text = 60, "合成视频（慢，请稍候）…"
            creep_to = 99
        elif line.startswith("Done:"):
            pct, text = 100, "完成"
        elif line.startswith("Error: no srt"):
            text = "input 里缺少同名 .srt 字幕"
        elif ("Error" in line) or ("Fail" in line) or ("FATAL" in line) or ("Traceback" in line):
            text = line[:80]

        if pct is not None:
            self._stop_creep()
            self.progress["value"] = pct
            if creep_to is not None:
                self._start_creep(creep_to)
        if text is not None:
            self.status_label.config(text=text)

    def _check_proc(self):
        if self.proc is None:
            return
        code = self.proc.poll()
        if code is None:
            self.poll_proc = self.root.after(300, self._check_proc)
            return
        if self.poll_queue is not None and self._wait_count < 10:
            self._wait_count += 1
            self.poll_proc = self.root.after(200, self._check_proc)
            return
        self._wait_count = 0
        self.proc = None
        self.set_running(False)
        if code == 0:
            self.progress["value"] = 100
            self.status_label.config(text="完成")
        else:
            self.status_label.config(text=f"失败 (exit code {code})")
            self._maybe_show_srt_missing()

    def _maybe_show_srt_missing(self):
        try:
            if not os.path.isdir(IN_FOLDER):
                return
            audios = [f for f in os.listdir(IN_FOLDER)
                      if f.lower().endswith((".wav", ".mp3"))]
            if len(audios) == 1:
                base = os.path.splitext(audios[0])[0]
                srt = os.path.join(IN_FOLDER, base + ".srt")
                if not os.path.exists(srt):
                    messagebox.showwarning(
                        "缺少字幕",
                        f"input 里没有 {base}.srt\n\n请先在 Tab1 转好字幕放进 input。"
                    )
        except Exception:
            pass

    def on_close(self):
        if self.proc is not None:
            if not messagebox.askyesno("Confirm", "视频正在生成，停止并退出？"):
                return
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
            except Exception:
                pass
            self.proc = None
        try:
            if self.poll_proc is not None:
                self.root.after_cancel(self.poll_proc)
            if self.poll_queue is not None:
                self.root.after_cancel(self.poll_queue)
        except Exception:
            pass
        self._stop_creep()
        try:
            self.root.destroy()
        except Exception:
            pass

if __name__ == "__main__":
    if "--run-video" in sys.argv:
        sys.exit(run_video_pipeline())
    else:
        root = tk.Tk()
        try:
            os.makedirs(IN_FOLDER, exist_ok=True)
            os.makedirs(OUT_FOLDER, exist_ok=True)
        except Exception:
            pass
        try:
            root.state("zoomed")
        except Exception:
            try:
                root.attributes("-zoomed", True)
            except Exception:
                w = root.winfo_screenwidth()
                h = root.winfo_screenheight()
                root.geometry(f"{w}x{h}+0+0")
        app = App(root)
        root.mainloop()