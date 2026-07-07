"""
Auto Clicker Pro - Modern UI (Windows)
---------------------------------------
ฟีเจอร์ทั้งหมด:
  - ตั้งชื่อ step, save/load preset (.json), ทำ Combo ต่อเนื่องหลาย preset
  - Loop พร้อมเวลาพักก่อนรอบถัดไป
  - แก้ไข / ทดสอบ / จัดลำดับ (▲▼) แต่ละ step และ preset ใน combo
  - หยุดฉุกเฉิน (เลื่อนเมาส์ชนมุมจอ) + จำกัดเวลารันสูงสุด (auto-stop)
  - โหมดธรรมชาติ: สุ่มเบี่ยงตำแหน่ง + สุ่ม delay
  - บันทึก log การทำงานเป็นไฟล์ .txt
  - [ใหม่] Image Recognition: ยึดจุดคลิกจากภาพอ้างอิงแทนพิกัดตายตัว (กันปัญหาหน้าจอ/หน้าต่างขยับ)
  - [ใหม่] ตรวจสอบหน้าต่างเป้าหมาย: เช็ค title หน้าต่างที่ active ก่อนรัน preset
  - [ใหม่] Export / Import preset+combo+images ทั้งหมดเป็นไฟล์ .zip
  - [ใหม่] ตั้งคีย์ลัดเอง (Start / Stop / Capture) ในแท็บ Settings

การติดตั้ง (จำเป็น):
    pip install customtkinter pyautogui pynput

การติดตั้ง (เสริม เพื่อเปิดใช้ฟีเจอร์ใหม่เต็มรูปแบบ):
    pip install opencv-python pygetwindow
    - ไม่มี opencv-python: image recognition ยังทำงานได้ แต่ต้องภาพตรงเป๊ะ (แม่นยำน้อยลง)
    - ไม่มี pygetwindow: ฟีเจอร์ตรวจสอบหน้าต่างเป้าหมายจะถูกข้ามไปอัตโนมัติ

การใช้งาน:
    python auto_clicker.py
"""

import customtkinter as ctk
from tkinter import messagebox, filedialog
import threading
import time
import json
import os
import random
import uuid
import zipfile
from datetime import datetime

import pyautogui
from pynput import keyboard

try:
    import pygetwindow as gw
    HAS_PYGETWINDOW = True
except ImportError:
    HAS_PYGETWINDOW = False

try:
    import cv2  # noqa: F401  (ใช้ตรวจว่ามี opencv ให้ confidence matching ทำงานได้)
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

pyautogui.FAILSAFE = True

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PRESET_DIR = "presets"
COMBO_DIR = "combos"
LOG_DIR = "logs"
IMAGE_DIR = "images"
CONFIG_FILE = "config.json"

for d in (PRESET_DIR, COMBO_DIR, LOG_DIR, IMAGE_DIR):
    os.makedirs(d, exist_ok=True)

VALID_KEYS = [f"f{i}" for i in range(1, 13)]
DEFAULT_HOTKEYS = {"start": "f6", "stop": "f7", "capture": "f8"}


# =====================================================================
#  Config (hotkeys) helpers
# =====================================================================
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            hotkeys = data.get("hotkeys", {})
            merged = dict(DEFAULT_HOTKEYS)
            merged.update({k: v for k, v in hotkeys.items() if v in VALID_KEYS})
            return {"hotkeys": merged}
        except Exception:
            pass
    return {"hotkeys": dict(DEFAULT_HOTKEYS)}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# =====================================================================
#  Preset / Combo data helpers
#  Preset file format: {"window_title": "...", "steps": [ {name,x,y,delay,image} ]}
# =====================================================================
def list_presets():
    return sorted(f[:-5] for f in os.listdir(PRESET_DIR) if f.endswith(".json"))


def list_combos():
    return sorted(f[:-5] for f in os.listdir(COMBO_DIR) if f.endswith(".json"))


def save_preset(name, steps, window_title=""):
    data = {"window_title": window_title, "steps": steps}
    with open(os.path.join(PRESET_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_preset(name):
    with open(os.path.join(PRESET_DIR, f"{name}.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):  # ไฟล์รูปแบบเก่า (list ของ steps ตรงๆ)
        return {"window_title": "", "steps": data}
    return {"window_title": data.get("window_title", ""), "steps": data.get("steps", [])}


def delete_preset(name):
    path = os.path.join(PRESET_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)


def save_combo(name, preset_names):
    with open(os.path.join(COMBO_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(preset_names, f, ensure_ascii=False, indent=2)


def load_combo(name):
    with open(os.path.join(COMBO_DIR, f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def delete_combo(name):
    path = os.path.join(COMBO_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)


def write_log(message):
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def capture_reference_image(x, y, size=60):
    """
    ถ่ายภาพรอบตำแหน่ง (x,y) ไว้ใช้เป็นภาพอ้างอิงสำหรับ image recognition
    คืนค่า (path, error_message) — ถ้าสำเร็จ error_message จะเป็น None
    """
    try:
        screen_w, screen_h = pyautogui.size()
    except Exception as e:
        write_log(f"ถ่ายภาพไม่สำเร็จ: อ่านขนาดหน้าจอไม่ได้ ({e})")
        return None, f"อ่านขนาดหน้าจอไม่ได้: {e}"

    half = size // 2
    left = max(0, min(x - half, screen_w - size))
    top = max(0, min(y - half, screen_h - size))
    width = min(size, screen_w - left)
    height = min(size, screen_h - top)

    if width <= 0 or height <= 0:
        msg = "ตำแหน่งอยู่นอกขอบเขตหน้าจอ ไม่สามารถถ่ายภาพได้"
        write_log(f"ถ่ายภาพไม่สำเร็จ: {msg} (x={x}, y={y})")
        return None, msg

    try:
        img = pyautogui.screenshot(region=(left, top, width, height))
        filename = f"{uuid.uuid4().hex}.png"
        path = os.path.join(IMAGE_DIR, filename)
        img.save(path)
        return path, None
    except NameError as e:
        # มักเกิดจากไม่มี Pillow ติดตั้ง (pyautogui.screenshot ต้องพึ่ง Pillow)
        msg = f"ไม่พบไลบรารีที่จำเป็น (ลองรัน: pip install pillow) — {e}"
        write_log(f"ถ่ายภาพไม่สำเร็จ: {msg}")
        return None, msg
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        write_log(f"ถ่ายภาพไม่สำเร็จ: {msg}")
        return None, msg


def resolve_click_position(step, timeout=3.0):
    """
    หาตำแหน่งคลิกจริงของ step นี้ ลำดับความสำคัญ:
      1. region (กรอบพื้นที่) — สุ่มตำแหน่งภายในกรอบทุกครั้งที่คลิก
      2. image (ภาพอ้างอิง) — หาตำแหน่งจากภาพบนหน้าจอ
      3. coords (พิกัดตายตัว) — ใช้พิกัดที่บันทึกไว้ตรงๆ
    คืนค่า (x, y, source) โดย source เป็น 'region' | 'image' | 'coords'
    """
    region = step.get("region")
    if region:
        x = random.randint(region["x1"], region["x2"])
        y = random.randint(region["y1"], region["y2"])
        return x, y, "region"

    image_path = step.get("image")
    if image_path and os.path.exists(image_path):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if HAS_OPENCV:
                    loc = pyautogui.locateCenterOnScreen(image_path, confidence=0.8)
                else:
                    loc = pyautogui.locateCenterOnScreen(image_path)
            except Exception:
                loc = None
            if loc:
                return loc.x, loc.y, "image"
            time.sleep(0.3)

    return step["x"], step["y"], "coords"


def check_window_title(expected_substring, timeout=5.0):
    """เช็คว่าหน้าต่างที่ active ตอนนี้ title มีคำที่คาดไว้หรือไม่ คืน True/False"""
    if not expected_substring:
        return True
    if not HAS_PYGETWINDOW:
        return True  # ข้ามการเช็คถ้าไม่มีไลบรารี

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            win = gw.getActiveWindow()
            if win and expected_substring.lower() in (win.title or "").lower():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# =====================================================================
#  Edit Step dialog
# =====================================================================
class EditStepDialog(ctk.CTkToplevel):
    def __init__(self, master, step, on_save, on_recapture_pos, on_recapture_image):
        super().__init__(master)
        self.title("แก้ไข Step")
        self.geometry("380x520")
        self.resizable(False, False)
        self.grab_set()

        self.step = step
        self.on_save = on_save
        self.on_recapture_pos = on_recapture_pos
        self.on_recapture_image = on_recapture_image
        self._region_stage = 0
        self._region_corner1 = None

        ctk.CTkLabel(self, text="แก้ไข Step", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 10))

        ctk.CTkLabel(self, text="ชื่อ step:").pack(anchor="w", padx=20)
        self.name_entry = ctk.CTkEntry(self, width=320)
        self.name_entry.insert(0, step["name"])
        self.name_entry.pack(padx=20, pady=(0, 10))

        ctk.CTkLabel(self, text="Delay (วินาที):").pack(anchor="w", padx=20)
        self.delay_entry = ctk.CTkEntry(self, width=320)
        self.delay_entry.insert(0, str(step["delay"]))
        self.delay_entry.pack(padx=20, pady=(0, 10))

        self.pos_label = ctk.CTkLabel(self, text=f"ตำแหน่งปัจจุบัน: ({step['x']}, {step['y']})", text_color="gray")
        self.pos_label.pack(pady=(0, 6))
        ctk.CTkButton(self, text="📍 จับตำแหน่งใหม่ (จุดเดียว, กด F8)", fg_color="#10b981", hover_color="#0d9668",
                      command=self._start_recapture_pos).pack(pady=(0, 12))

        region = step.get("region")
        region_status = f"กรอบ: ({region['x1']},{region['y1']}) - ({region['x2']},{region['y2']})" if region else "ยังไม่มีกรอบพื้นที่"
        self.region_label = ctk.CTkLabel(self, text=region_status, text_color="gray")
        self.region_label.pack(pady=(0, 6))
        self.region_btn = ctk.CTkButton(self, text="🔲 จับกรอบใหม่ (2 จุด, กด F8)", fg_color="#4b5563", hover_color="#374151",
                      command=self._start_recapture_region)
        self.region_btn.pack(pady=(0, 6))
        ctk.CTkButton(self, text="✖ ลบกรอบ (กลับไปใช้จุดเดียว)", fg_color="#374151", hover_color="#1f2937",
                      command=self._clear_region).pack(pady=(0, 12))

        img_status = "มีภาพอ้างอิงแล้ว 🖼" if step.get("image") else "ยังไม่มีภาพอ้างอิง"
        self.img_label = ctk.CTkLabel(self, text=img_status, text_color="gray")
        self.img_label.pack(pady=(0, 6))
        ctk.CTkButton(self, text="🖼 ถ่ายภาพอ้างอิงใหม่ (กด F8)", fg_color="#4b5563", hover_color="#374151",
                      command=self._start_recapture_image).pack(pady=(0, 15))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack()
        ctk.CTkButton(btn_row, text="บันทึก", fg_color="#6d5ef8", hover_color="#5a4ce0",
                      command=self._save).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="ยกเลิก", fg_color="#374151", hover_color="#1f2937",
                      command=self.destroy).pack(side="left", padx=8)

    def _start_recapture_pos(self):
        self.on_recapture_pos(self._recapture_pos_done)

    def _recapture_pos_done(self, x, y):
        self.step["x"] = x
        self.step["y"] = y
        self.pos_label.configure(text=f"ตำแหน่งปัจจุบัน: ({x}, {y})")

    def _start_recapture_region(self):
        self._region_stage = 1
        self._region_corner1 = None
        self.region_btn.configure(text="⏳ รอกด F8 (มุมซ้ายบน)")
        self.on_recapture_pos(self._region_point_captured)

    def _region_point_captured(self, x, y):
        if self._region_stage == 1:
            self._region_corner1 = (x, y)
            self._region_stage = 2
            self.region_btn.configure(text="⏳ รอกด F8 (มุมขวาล่าง)")
            self.on_recapture_pos(self._region_point_captured)
            return

        x1, y1 = self._region_corner1
        x2, y2 = x, y
        rx1, rx2 = sorted((x1, x2))
        ry1, ry2 = sorted((y1, y2))
        self.step["region"] = {"x1": rx1, "y1": ry1, "x2": rx2, "y2": ry2}
        self.step["x"] = (rx1 + rx2) // 2
        self.step["y"] = (ry1 + ry2) // 2
        self.pos_label.configure(text=f"ตำแหน่งปัจจุบัน: ({self.step['x']}, {self.step['y']}) (จุดกึ่งกลางกรอบ)")
        self.region_label.configure(text=f"กรอบ: ({rx1},{ry1}) - ({rx2},{ry2})")
        self.region_btn.configure(text="🔲 จับกรอบใหม่ (2 จุด, กด F8)")
        self._region_stage = 0

    def _clear_region(self):
        self.step["region"] = None
        self.region_label.configure(text="ยังไม่มีกรอบพื้นที่")

    def _start_recapture_image(self):
        self.on_recapture_image(self._recapture_image_done)

    def _recapture_image_done(self, path):
        self.step["image"] = path
        self.img_label.configure(text="มีภาพอ้างอิงแล้ว 🖼" if path else "ถ่ายภาพไม่สำเร็จ")

    def _save(self):
        try:
            delay = float(self.delay_entry.get())
        except ValueError:
            delay = self.step["delay"]
        self.step["name"] = self.name_entry.get().strip() or self.step["name"]
        self.step["delay"] = delay
        self.on_save()
        self.destroy()


# =====================================================================
#  Main App
# =====================================================================
class AutoClickerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Auto Clicker Pro")
        self.geometry("880x760")
        self.minsize(720, 520)
        self.resizable(True, True)

        self.config_data = load_config()

        # State
        self.current_steps = []
        self.current_window_title = ""
        self.current_combo = []
        self.capture_mode = False
        self.capture_callback = None      # (x,y) -> None  for position capture
        self.image_capture_callback = None  # (x,y) -> None for image capture (takes screenshot too)
        self._region_add_corner1 = None   # ใช้ระหว่างจับกรอบ 2 จุดตอนเพิ่ม step ใหม่
        self.running = False
        self.run_thread = None
        self.run_start_time = None

        self._build_ui()
        self._start_hotkey_listener()

    # -----------------------------------------------------------------
    def _build_ui(self):
        self.configure(fg_color="#0d0d14")

        # Root layout: sidebar (col 0) + content (col 1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        self.content_area = ctk.CTkFrame(self, fg_color="#0d0d14")
        self.content_area.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

        self.pages = {}
        for key, builder in (
            ("preset", self._build_preset_tab),
            ("combo", self._build_combo_tab),
            ("run", self._build_run_tab),
            ("settings", self._build_settings_tab),
        ):
            page = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            builder(page)
            self.pages[key] = page

        self._select_page("preset")

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color="#131320")
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(28, 4))
        ctk.CTkLabel(brand, text="⚡", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 8))
        title_box = ctk.CTkFrame(brand, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Auto Clicker", font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="PRO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#8b7cf6").pack(anchor="w")

        self.status_badge = ctk.CTkLabel(sidebar, text="●  พร้อมทำงาน",
                                          text_color="#22c55e", font=ctk.CTkFont(size=12))
        self.status_badge.pack(anchor="w", padx=20, pady=(6, 20))

        divider = ctk.CTkFrame(sidebar, height=1, fg_color="#26263a")
        divider.pack(fill="x", padx=20, pady=(0, 16))

        self.nav_buttons = {}
        nav_items = [
            ("preset", "🎯", "Preset"),
            ("combo", "🔗", "Combo"),
            ("run", "▶", "Run"),
            ("settings", "⚙️", "Settings"),
        ]
        for key, icon, label in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=f"  {icon}   {label}", anchor="w", height=42,
                corner_radius=12, font=ctk.CTkFont(size=14),
                fg_color="transparent", hover_color="#1e1e30", text_color="#c7c7d9",
                command=lambda k=key: self._select_page(k)
            )
            btn.pack(fill="x", padx=14, pady=3)
            self.nav_buttons[key] = btn

        ctk.CTkLabel(sidebar, text="F6 เริ่ม  ·  F7 หยุด  ·  F8 จับจุด",
                     text_color="#5b5b70", font=ctk.CTkFont(size=10),
                     wraplength=170, justify="left").pack(side="bottom", padx=20, pady=20, anchor="w")

    def _select_page(self, key):
        for k, page in self.pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(fg_color="#6d5ef8", text_color="white", hover_color="#5a4ce0")
            else:
                btn.configure(fg_color="transparent", text_color="#c7c7d9", hover_color="#1e1e30")

    # =================================================================
    #  TAB 1: Preset editor
    # =================================================================
    def _build_preset_tab(self, tab):
        ctk.CTkLabel(tab, text="Preset", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(tab, text="สร้างและจัดการชุด step ที่จะให้คลิกตามลำดับ",
                     text_color="#8b8b9a", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 14))

        load_row = ctk.CTkFrame(tab, fg_color="transparent")
        load_row.pack(fill="x", pady=(10, 5))
        ctk.CTkLabel(load_row, text="Preset ที่มีอยู่:").pack(side="left", padx=(0, 8))
        self.preset_select = ctk.CTkOptionMenu(load_row, values=list_presets() or ["(ไม่มี)"],
                                                width=170, command=self._on_select_preset)
        self.preset_select.pack(side="left", padx=4)
        ctk.CTkButton(load_row, text="🗑 ลบ preset นี้", width=100, fg_color="#ef4444",
                      hover_color="#dc2626", command=self._delete_current_preset).pack(side="left", padx=4)

        wt_row = ctk.CTkFrame(tab, fg_color="transparent")
        wt_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(wt_row, text="ชื่อหน้าต่างเป้าหมาย (ไม่บังคับ):").pack(side="left")
        self.window_title_entry = ctk.CTkEntry(wt_row, width=200, placeholder_text="เช่น Notepad")
        self.window_title_entry.pack(side="left", padx=8)
        ctk.CTkLabel(tab, text="ถ้าใส่ไว้ โปรแกรมจะเช็คว่าหน้าต่างที่ active มีคำนี้ใน title ก่อนเริ่มรัน preset นี้",
                    text_color="gray", font=ctk.CTkFont(size=11), wraplength=580, justify="left").pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(tab, text="Steps ใน preset นี้", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(4, 2))
        self.steps_frame = ctk.CTkScrollableFrame(tab, height=210, corner_radius=14, fg_color="#131320")
        self.steps_frame.pack(fill="both", expand=True, pady=(0, 10))

        add_card = ctk.CTkFrame(tab, corner_radius=16, fg_color="#191927")
        add_card.pack(fill="x", pady=(0, 10))

        row1 = ctk.CTkFrame(add_card, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(row1, text="ชื่อ step:").pack(side="left")
        self.step_name_entry = ctk.CTkEntry(row1, width=140, placeholder_text="เช่น กดปุ่มยืนยัน")
        self.step_name_entry.pack(side="left", padx=8)
        ctk.CTkLabel(row1, text="Delay (วิ):").pack(side="left")
        self.step_delay_entry = ctk.CTkEntry(row1, width=55, placeholder_text="1.0")
        self.step_delay_entry.insert(0, "1.0")
        self.step_delay_entry.pack(side="left", padx=8)

        row2 = ctk.CTkFrame(add_card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 6))
        self.capture_btn = ctk.CTkButton(row2, text="📍 จับตำแหน่งเมาส์ (F8)",
                                          fg_color="#10b981", hover_color="#0d9668",
                                          command=self._toggle_capture)
        self.capture_btn.pack(side="left")
        ctk.CTkButton(row2, text="🗑 ลบ step ล่าสุด", width=120, fg_color="#374151",
                      hover_color="#1f2937", command=self._remove_last_step).pack(side="left", padx=8)

        row3 = ctk.CTkFrame(add_card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 4))
        self.use_image_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row3, text="ใช้ Image Recognition (ถ่ายภาพอ้างอิงตอนจับตำแหน่งนี้ด้วย)",
                     variable=self.use_image_var, command=self._on_toggle_use_image).pack(side="left")

        row4 = ctk.CTkFrame(add_card, fg_color="transparent")
        row4.pack(fill="x", padx=12, pady=(0, 4))
        self.use_region_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row4, text="🔲 ใช้กรอบพื้นที่ (สุ่มตำแหน่งคลิกภายในกรอบ แทนจุดเดียว)",
                     variable=self.use_region_var, command=self._on_toggle_use_region).pack(side="left")
        ctk.CTkLabel(add_card,
                    text="ถ้าเปิดไว้ ตอนกด F8 จะให้จับ 2 จุด: มุมซ้ายบน แล้วมุมขวาล่างของกรอบ ตอนคลิกจริงจะสุ่มตำแหน่งในกรอบนี้ทุกครั้ง",
                    text_color="#8b8b9a", font=ctk.CTkFont(size=11), wraplength=500, justify="left").pack(
                    anchor="w", padx=12, pady=(0, 12))

        save_row = ctk.CTkFrame(tab, fg_color="transparent")
        save_row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(save_row, text="ชื่อ preset:").pack(side="left")
        self.preset_name_entry = ctk.CTkEntry(save_row, width=200, placeholder_text="เช่น farm-1")
        self.preset_name_entry.pack(side="left", padx=8)
        ctk.CTkButton(save_row, text="💾 บันทึก preset", fg_color="#6d5ef8", hover_color="#5a4ce0",
                      command=self._save_current_preset).pack(side="left", padx=8)

        self._refresh_steps_ui()

    def _on_toggle_use_image(self):
        if self.use_image_var.get():
            self.use_region_var.set(False)

    def _on_toggle_use_region(self):
        if self.use_region_var.get():
            self.use_image_var.set(False)

    def _toggle_capture(self):
        self.capture_mode = True
        self.image_capture_callback = None

        if self.use_region_var.get():
            self._region_add_corner1 = None
            self.capture_callback = self._region_add_point_captured
            self.capture_btn.configure(text="⏳ รอกด F8 (มุมซ้ายบน)", fg_color="#f59e0b")
        else:
            self.capture_callback = None
            self.capture_btn.configure(text="⏳ รอกด F8 ...", fg_color="#f59e0b")

    def _region_add_point_captured(self, x, y):
        if self._region_add_corner1 is None:
            self._region_add_corner1 = (x, y)
            # ยังไม่จบ ต้องจับมุมที่สองต่อ — เปิดโหมดจับต่ออีกครั้ง
            self.capture_mode = True
            self.capture_callback = self._region_add_point_captured
            self.capture_btn.configure(text="⏳ รอกด F8 (มุมขวาล่าง)", fg_color="#f59e0b")
            return

        x1, y1 = self._region_add_corner1
        x2, y2 = x, y
        rx1, rx2 = sorted((x1, x2))
        ry1, ry2 = sorted((y1, y2))
        self._region_add_corner1 = None

        name = self.step_name_entry.get().strip() or f"Step {len(self.current_steps) + 1}"
        try:
            delay = float(self.step_delay_entry.get())
        except ValueError:
            delay = 1.0

        self.current_steps.append({
            "name": name,
            "x": (rx1 + rx2) // 2, "y": (ry1 + ry2) // 2,
            "delay": delay, "image": None,
            "region": {"x1": rx1, "y1": ry1, "x2": rx2, "y2": ry2},
        })
        self.step_name_entry.delete(0, "end")
        self._refresh_steps_ui()
        self.capture_btn.configure(text="📍 จับตำแหน่งเมาส์ (F8)", fg_color="#10b981")

    def _capture_current_position(self):
        if not self.capture_mode:
            return
        x, y = pyautogui.position()

        # กรณีถูกเรียกจาก dialog แก้ไข (ตำแหน่งอย่างเดียว) หรือจากโหมดจับกรอบ (2 จุด)
        if self.capture_callback is not None:
            cb = self.capture_callback
            self.capture_mode = False
            self.capture_callback = None
            cb(x, y)
            return

        # กรณีถูกเรียกจาก dialog แก้ไข (ถ่ายภาพใหม่)
        if self.image_capture_callback is not None:
            cb = self.image_capture_callback
            self.capture_mode = False
            self.image_capture_callback = None
            path, error = capture_reference_image(x, y)
            if error:
                messagebox.showerror("ถ่ายภาพไม่สำเร็จ", error)
            cb(path)
            return

        # กรณีปกติ: เพิ่ม step ใหม่ (จุดเดียว)
        name = self.step_name_entry.get().strip() or f"Step {len(self.current_steps) + 1}"
        try:
            delay = float(self.step_delay_entry.get())
        except ValueError:
            delay = 1.0

        image_path = None
        if self.use_image_var.get():
            image_path, error = capture_reference_image(x, y)
            if error:
                messagebox.showerror("ถ่ายภาพไม่สำเร็จ", f"{error}\n\nจะบันทึก step นี้โดยไม่มีภาพอ้างอิง (ใช้พิกัดตายตัวแทน)")

        self.current_steps.append({"name": name, "x": x, "y": y, "delay": delay, "image": image_path})
        self.step_name_entry.delete(0, "end")
        self._refresh_steps_ui()

        self.capture_mode = False
        self.capture_btn.configure(text="📍 จับตำแหน่งเมาส์ (F8)", fg_color="#10b981")

    def _refresh_steps_ui(self):
        for w in self.steps_frame.winfo_children():
            w.destroy()
        if not self.current_steps:
            ctk.CTkLabel(self.steps_frame, text="ยังไม่มี step — ตั้งชื่อแล้วกด F8 เพื่อจับตำแหน่ง",
                         text_color="gray").pack(pady=20)
            return
        for i, s in enumerate(self.current_steps):
            row = ctk.CTkFrame(self.steps_frame, corner_radius=12, fg_color="#1e1e2e")
            row.pack(fill="x", pady=4, padx=2)
            img_tag = " 🖼" if s.get("image") else ""
            region = s.get("region")
            if region:
                pos_text = f"🔲 ({region['x1']},{region['y1']}) - ({region['x2']},{region['y2']})"
            else:
                pos_text = f"({s['x']}, {s['y']})"
            ctk.CTkLabel(row, text=f"  {i+1}. {s['name']}   {pos_text}   ⏱ {s['delay']}s{img_tag}",
                        anchor="w").pack(side="left", padx=10, pady=8)

            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=6)
            ctk.CTkButton(btn_frame, text="▼", width=28, fg_color="#1f2937", hover_color="#12121c",
                         command=lambda i=i: self._move_step(i, 1)).pack(side="right", padx=2)
            ctk.CTkButton(btn_frame, text="▲", width=28, fg_color="#1f2937", hover_color="#12121c",
                         command=lambda i=i: self._move_step(i, -1)).pack(side="right", padx=2)
            ctk.CTkButton(btn_frame, text="▶ ทดสอบ", width=70, fg_color="#6d5ef8", hover_color="#5a4ce0",
                         command=lambda s=s: self._test_step(s)).pack(side="right", padx=2)
            ctk.CTkButton(btn_frame, text="✏️ แก้ไข", width=70, fg_color="#374151", hover_color="#1f2937",
                         command=lambda s=s: self._open_edit_dialog(s)).pack(side="right", padx=2)

    def _move_step(self, index, direction):
        new_index = index + direction
        if 0 <= new_index < len(self.current_steps):
            self.current_steps[index], self.current_steps[new_index] = \
                self.current_steps[new_index], self.current_steps[index]
            self._refresh_steps_ui()

    def _test_step(self, step):
        try:
            x, y, source = resolve_click_position(step, timeout=2.0)
            pyautogui.click(x, y)
            note_map = {"region": " (สุ่มในกรอบ)", "image": " (พบจากภาพอ้างอิง)", "coords": ""}
            note = note_map.get(source, "")
            self.status_badge.configure(text=f"●  ทดสอบ '{step['name']}' แล้ว{note}", text_color="#6d5ef8")
        except pyautogui.FailSafeException:
            messagebox.showinfo("หยุดฉุกเฉิน", "ตรวจพบเมาส์ชนมุมจอ ยกเลิกการทดสอบ")

    def _open_edit_dialog(self, step):
        def on_save():
            self._refresh_steps_ui()

        def on_recapture_pos(done_callback):
            self.capture_mode = True
            self.capture_callback = done_callback

        def on_recapture_image(done_callback):
            self.capture_mode = True
            self.image_capture_callback = done_callback

        EditStepDialog(self, step, on_save, on_recapture_pos, on_recapture_image)

    def _remove_last_step(self):
        if self.current_steps:
            self.current_steps.pop()
            self._refresh_steps_ui()

    def _save_current_preset(self):
        name = self.preset_name_entry.get().strip()
        if not name:
            messagebox.showwarning("แจ้งเตือน", "กรุณาตั้งชื่อ preset")
            return
        if not self.current_steps:
            messagebox.showwarning("แจ้งเตือน", "ยังไม่มี step ใน preset นี้")
            return
        window_title = self.window_title_entry.get().strip()
        save_preset(name, self.current_steps, window_title)
        messagebox.showinfo("สำเร็จ", f"บันทึก preset '{name}' แล้ว")
        self._refresh_preset_dropdowns()

    def _on_select_preset(self, name):
        try:
            data = load_preset(name)
            self.current_steps = data["steps"]
            self.current_window_title = data["window_title"]
            self.preset_name_entry.delete(0, "end")
            self.preset_name_entry.insert(0, name)
            self.window_title_entry.delete(0, "end")
            self.window_title_entry.insert(0, self.current_window_title)
            self._refresh_steps_ui()
        except FileNotFoundError:
            pass

    def _delete_current_preset(self):
        name = self.preset_select.get()
        if name and name != "(ไม่มี)":
            if messagebox.askyesno("ยืนยัน", f"ลบ preset '{name}' ?"):
                delete_preset(name)
                self.current_steps = []
                self._refresh_steps_ui()
                self._refresh_preset_dropdowns()

    def _refresh_preset_dropdowns(self):
        presets = list_presets() or ["(ไม่มี)"]
        self.preset_select.configure(values=presets)
        if hasattr(self, "combo_add_select"):
            self.combo_add_select.configure(values=presets)
        if hasattr(self, "run_combo_select"):
            self.run_combo_select.configure(values=list_combos() or ["(ไม่มี)"])

    # =================================================================
    #  TAB 2: Combo builder
    # =================================================================
    def _build_combo_tab(self, tab):
        ctk.CTkLabel(tab, text="Combo", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(tab, text="เรียง preset หลายชุดให้รันต่อเนื่องกันใน 1 รอบ",
                     text_color="#8b8b9a", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 14))

        add_row = ctk.CTkFrame(tab, fg_color="transparent")
        add_row.pack(fill="x", pady=5)
        ctk.CTkLabel(add_row, text="เลือก preset:").pack(side="left")
        self.combo_add_select = ctk.CTkOptionMenu(add_row, values=list_presets() or ["(ไม่มี)"], width=180)
        self.combo_add_select.pack(side="left", padx=8)
        ctk.CTkButton(add_row, text="➕ เพิ่มเข้า combo", fg_color="#10b981", hover_color="#0d9668",
                      command=self._add_to_combo).pack(side="left", padx=4)

        ctk.CTkLabel(tab, text="ลำดับการรันใน combo นี้", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", pady=(10, 2))
        self.combo_list_frame = ctk.CTkScrollableFrame(tab, height=210, corner_radius=14, fg_color="#131320")
        self.combo_list_frame.pack(fill="both", expand=True, pady=(0, 10))

        manage_row = ctk.CTkFrame(tab, fg_color="transparent")
        manage_row.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(manage_row, text="🗑 ลบรายการล่าสุด", width=130, fg_color="#374151",
                      hover_color="#1f2937", command=self._remove_last_combo_item).pack(side="left", padx=(0, 8))
        ctk.CTkButton(manage_row, text="🧹 ล้าง combo", width=110, fg_color="#ef4444",
                      hover_color="#dc2626", command=self._clear_combo).pack(side="left")

        save_row = ctk.CTkFrame(tab, fg_color="transparent")
        save_row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(save_row, text="ชื่อ combo:").pack(side="left")
        self.combo_name_entry = ctk.CTkEntry(save_row, width=200, placeholder_text="เช่น combo-เช้า")
        self.combo_name_entry.pack(side="left", padx=8)
        ctk.CTkButton(save_row, text="💾 บันทึก combo", fg_color="#6d5ef8", hover_color="#5a4ce0",
                      command=self._save_current_combo).pack(side="left", padx=8)

        load_row = ctk.CTkFrame(tab, fg_color="transparent")
        load_row.pack(fill="x")
        ctk.CTkLabel(load_row, text="โหลด combo ที่มีอยู่:").pack(side="left")
        self.combo_select = ctk.CTkOptionMenu(load_row, values=list_combos() or ["(ไม่มี)"],
                                               width=180, command=self._on_select_combo)
        self.combo_select.pack(side="left", padx=8)
        ctk.CTkButton(load_row, text="🗑 ลบ combo นี้", width=100, fg_color="#ef4444",
                      hover_color="#dc2626", command=self._delete_current_combo).pack(side="left", padx=4)

        self._refresh_combo_ui()

    def _add_to_combo(self):
        name = self.combo_add_select.get()
        if name and name != "(ไม่มี)":
            self.current_combo.append(name)
            self._refresh_combo_ui()

    def _refresh_combo_ui(self):
        for w in self.combo_list_frame.winfo_children():
            w.destroy()
        if not self.current_combo:
            ctk.CTkLabel(self.combo_list_frame, text="ยังไม่มี preset ใน combo นี้",
                        text_color="gray").pack(pady=20)
            return
        for i, name in enumerate(self.current_combo):
            row = ctk.CTkFrame(self.combo_list_frame, corner_radius=12, fg_color="#1e1e2e")
            row.pack(fill="x", pady=4, padx=2)
            ctk.CTkLabel(row, text=f"  {i+1}. {name}", anchor="w").pack(side="left", padx=10, pady=8)

            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=6)
            ctk.CTkButton(btn_frame, text="▼", width=28, fg_color="#1f2937", hover_color="#12121c",
                         command=lambda i=i: self._move_combo_item(i, 1)).pack(side="right", padx=2)
            ctk.CTkButton(btn_frame, text="▲", width=28, fg_color="#1f2937", hover_color="#12121c",
                         command=lambda i=i: self._move_combo_item(i, -1)).pack(side="right", padx=2)

    def _move_combo_item(self, index, direction):
        new_index = index + direction
        if 0 <= new_index < len(self.current_combo):
            self.current_combo[index], self.current_combo[new_index] = \
                self.current_combo[new_index], self.current_combo[index]
            self._refresh_combo_ui()

    def _remove_last_combo_item(self):
        if self.current_combo:
            self.current_combo.pop()
            self._refresh_combo_ui()

    def _clear_combo(self):
        self.current_combo.clear()
        self._refresh_combo_ui()

    def _save_current_combo(self):
        name = self.combo_name_entry.get().strip()
        if not name:
            messagebox.showwarning("แจ้งเตือน", "กรุณาตั้งชื่อ combo")
            return
        if not self.current_combo:
            messagebox.showwarning("แจ้งเตือน", "ยังไม่มี preset ใน combo นี้")
            return
        save_combo(name, self.current_combo)
        messagebox.showinfo("สำเร็จ", f"บันทึก combo '{name}' แล้ว")
        self._refresh_preset_dropdowns()
        self.combo_select.configure(values=list_combos())

    def _on_select_combo(self, name):
        try:
            self.current_combo = load_combo(name)
            self.combo_name_entry.delete(0, "end")
            self.combo_name_entry.insert(0, name)
            self._refresh_combo_ui()
        except FileNotFoundError:
            pass

    def _delete_current_combo(self):
        name = self.combo_select.get()
        if name and name != "(ไม่มี)":
            if messagebox.askyesno("ยืนยัน", f"ลบ combo '{name}' ?"):
                delete_combo(name)
                self.current_combo = []
                self._refresh_combo_ui()
                self.combo_select.configure(values=list_combos() or ["(ไม่มี)"])

    # =================================================================
    #  TAB 3: Run
    # =================================================================
    def _build_run_tab(self, tab):
        ctk.CTkLabel(tab, text="Run", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(tab, text="ตั้งค่าและเริ่มการทำงานอัตโนมัติ",
                     text_color="#8b8b9a", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 14))

        ctk.CTkLabel(tab, text="เลือก Combo ที่จะรัน", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(0, 5))
        self.run_combo_select = ctk.CTkOptionMenu(tab, values=list_combos() or ["(ไม่มี)"], width=220)
        self.run_combo_select.pack(anchor="w", pady=(0, 12))

        settings_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        settings_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(settings_card, text="ตั้งค่าการวนรอบ (Loop)",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        row1 = ctk.CTkFrame(settings_card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(row1, text="จำนวนรอบ (0 = ไม่จำกัด):").pack(side="left")
        self.loop_count_entry = ctk.CTkEntry(row1, width=80, placeholder_text="0")
        self.loop_count_entry.insert(0, "0")
        self.loop_count_entry.pack(side="left", padx=8)

        row2 = ctk.CTkFrame(settings_card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(row2, text="พักก่อนเริ่มรอบถัดไป (วินาที):").pack(side="left")
        self.loop_pause_entry = ctk.CTkEntry(row2, width=80, placeholder_text="0")
        self.loop_pause_entry.insert(0, "0")
        self.loop_pause_entry.pack(side="left", padx=8)

        natural_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        natural_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(natural_card, text="🎲 โหมดธรรมชาติ (Random Offset)",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 4))

        self.natural_var = ctk.BooleanVar(value=False)
        nrow = ctk.CTkFrame(natural_card, fg_color="transparent")
        nrow.pack(fill="x", padx=15, pady=(0, 8))
        self.natural_switch = ctk.CTkSwitch(nrow, text="เปิดใช้งาน", variable=self.natural_var,
                                             command=self._toggle_natural_entries)
        self.natural_switch.pack(side="left")

        nrow2 = ctk.CTkFrame(natural_card, fg_color="transparent")
        nrow2.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(nrow2, text="เบี่ยงตำแหน่งคลิก ± พิกเซล:").pack(side="left")
        self.offset_px_entry = ctk.CTkEntry(nrow2, width=60, placeholder_text="3", state="disabled")
        self.offset_px_entry.insert(0, "3")
        self.offset_px_entry.pack(side="left", padx=8)

        nrow3 = ctk.CTkFrame(natural_card, fg_color="transparent")
        nrow3.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(nrow3, text="สุ่ม delay เพิ่ม/ลด ± %:").pack(side="left")
        self.delay_jitter_entry = ctk.CTkEntry(nrow3, width=60, placeholder_text="15", state="disabled")
        self.delay_jitter_entry.insert(0, "15")
        self.delay_jitter_entry.pack(side="left", padx=8)

        autostop_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        autostop_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(autostop_card, text="⏲ จำกัดเวลารันสูงสุด (Auto-stop)",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 4))

        self.autostop_var = ctk.BooleanVar(value=False)
        toggle_row = ctk.CTkFrame(autostop_card, fg_color="transparent")
        toggle_row.pack(fill="x", padx=15, pady=(0, 12))
        self.autostop_switch = ctk.CTkSwitch(toggle_row, text="เปิดใช้งาน", variable=self.autostop_var,
                                              command=self._toggle_autostop_entry)
        self.autostop_switch.pack(side="left")
        ctk.CTkLabel(toggle_row, text="หยุดหลังรัน (นาที):").pack(side="left", padx=(20, 8))
        self.autostop_minutes_entry = ctk.CTkEntry(toggle_row, width=70, placeholder_text="30", state="disabled")
        self.autostop_minutes_entry.insert(0, "30")
        self.autostop_minutes_entry.pack(side="left")

        log_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        log_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(log_card, text="📝 บันทึก Log การทำงาน",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 4))
        self.logging_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(log_card, text="เปิดใช้งาน (บันทึกไฟล์ใน logs/)", variable=self.logging_var).pack(
                    anchor="w", padx=15, pady=(0, 12))

        emergency_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#2a1520")
        emergency_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(emergency_card, text="🛟 หยุดฉุกเฉิน",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#fca5a5").pack(anchor="w", padx=15, pady=(12, 4))
        ctk.CTkLabel(emergency_card,
                    text="หากโปรแกรมคลิกผิดตำแหน่งหรือค้าง ให้เลื่อนเมาส์ไปชน 'มุมใดก็ได้' ของหน้าจอ โปรแกรมจะหยุดทำงานทันที",
                    text_color="#fecaca", font=ctk.CTkFont(size=12), wraplength=560, justify="left").pack(
                    anchor="w", padx=15, pady=(0, 12))

        monitor_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        monitor_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(monitor_card, text="📊 สถานะการทำงานแบบเรียลไทม์",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        stat_row = ctk.CTkFrame(monitor_card, fg_color="transparent")
        stat_row.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(stat_row, text="⏱ เวลาที่ผ่านไป:").pack(side="left")
        self.elapsed_label = ctk.CTkLabel(stat_row, text="00:00", font=ctk.CTkFont(size=14, weight="bold"),
                                          text_color="#8b7cf6")
        self.elapsed_label.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(stat_row, text="Step:").pack(side="left")
        self.step_counter_label = ctk.CTkLabel(stat_row, text="- / -", font=ctk.CTkFont(size=14, weight="bold"),
                                               text_color="#8b7cf6")
        self.step_counter_label.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(stat_row, text="ถัดไปใน:").pack(side="left")
        self.countdown_label = ctk.CTkLabel(stat_row, text="—", font=ctk.CTkFont(size=14, weight="bold"),
                                            text_color="#f59e0b")
        self.countdown_label.pack(side="left", padx=(8, 0))

        self.progress_label = ctk.CTkLabel(monitor_card, text="ยังไม่เริ่มทำงาน", text_color="gray",
                                            wraplength=520, justify="left", anchor="w")
        self.progress_label.pack(fill="x", anchor="w", padx=15, pady=(4, 4))

        self.prevnext_label = ctk.CTkLabel(monitor_card, text="ก่อนหน้า: —      ถัดไป: —",
                                           text_color="#8b8b9a", font=ctk.CTkFont(size=12),
                                           wraplength=520, justify="left", anchor="w")
        self.prevnext_label.pack(fill="x", anchor="w", padx=15, pady=(0, 8))

        ctk.CTkLabel(monitor_card, text="ประวัติการทำงาน (เรียลไทม์)",
                    font=ctk.CTkFont(size=12, weight="bold"), text_color="#8b8b9a").pack(anchor="w", padx=15)
        self.record_box = ctk.CTkTextbox(monitor_card, height=150, corner_radius=10,
                                         fg_color="#101018", font=ctk.CTkFont(family="Consolas", size=11))
        self.record_box.pack(fill="x", padx=15, pady=(4, 15))
        self.record_box.configure(state="disabled")

        run_row = ctk.CTkFrame(tab, fg_color="transparent")
        run_row.pack(fill="x", pady=6)
        self.start_btn = ctk.CTkButton(run_row, text=f"▶  เริ่ม ({self.config_data['hotkeys']['start'].upper()})",
                                        height=45, font=ctk.CTkFont(size=15, weight="bold"),
                                        fg_color="#2f9e44", hover_color="#10b981",
                                        command=self.start_running)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.stop_btn = ctk.CTkButton(run_row, text=f"■  หยุด ({self.config_data['hotkeys']['stop'].upper()})",
                                       height=45, font=ctk.CTkFont(size=15, weight="bold"),
                                       fg_color="#ef4444", hover_color="#dc2626",
                                       command=self.stop_running)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(8, 0))

        self.hotkey_hint_label = ctk.CTkLabel(
            tab, text=self._hotkey_hint_text(), text_color="gray", font=ctk.CTkFont(size=12))
        self.hotkey_hint_label.pack(pady=(16, 0))

    def _hotkey_hint_text(self):
        hk = self.config_data["hotkeys"]
        return (f"{hk['capture'].upper()} = บันทึกตำแหน่งเมาส์ (แท็บ Preset)   |   "
                f"{hk['start'].upper()} = เริ่ม   |   {hk['stop'].upper()} = หยุด")

    def _toggle_autostop_entry(self):
        state = "normal" if self.autostop_var.get() else "disabled"
        self.autostop_minutes_entry.configure(state=state)

    def _toggle_natural_entries(self):
        state = "normal" if self.natural_var.get() else "disabled"
        self.offset_px_entry.configure(state=state)
        self.delay_jitter_entry.configure(state=state)

    # =================================================================
    #  TAB 4: Settings (hotkeys + export/import)
    # =================================================================
    def _build_settings_tab(self, tab):
        ctk.CTkLabel(tab, text="Settings", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(tab, text="ตั้งคีย์ลัด, สำรอง/กู้คืนข้อมูล, และเช็คไลบรารีเสริม",
                     text_color="#8b8b9a", font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 14))

        # Hotkeys
        hk_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        hk_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(hk_card, text="⌨️ ตั้งคีย์ลัดเอง", font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=15, pady=(15, 8))

        hk = self.config_data["hotkeys"]

        row_start = ctk.CTkFrame(hk_card, fg_color="transparent")
        row_start.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row_start, text="เริ่มทำงาน:", width=110, anchor="w").pack(side="left")
        self.hk_start_menu = ctk.CTkOptionMenu(row_start, values=[k.upper() for k in VALID_KEYS], width=100)
        self.hk_start_menu.set(hk["start"].upper())
        self.hk_start_menu.pack(side="left")

        row_stop = ctk.CTkFrame(hk_card, fg_color="transparent")
        row_stop.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row_stop, text="หยุดทำงาน:", width=110, anchor="w").pack(side="left")
        self.hk_stop_menu = ctk.CTkOptionMenu(row_stop, values=[k.upper() for k in VALID_KEYS], width=100)
        self.hk_stop_menu.set(hk["stop"].upper())
        self.hk_stop_menu.pack(side="left")

        row_cap = ctk.CTkFrame(hk_card, fg_color="transparent")
        row_cap.pack(fill="x", padx=15, pady=(4, 12))
        ctk.CTkLabel(row_cap, text="จับตำแหน่ง:", width=110, anchor="w").pack(side="left")
        self.hk_capture_menu = ctk.CTkOptionMenu(row_cap, values=[k.upper() for k in VALID_KEYS], width=100)
        self.hk_capture_menu.set(hk["capture"].upper())
        self.hk_capture_menu.pack(side="left")

        ctk.CTkButton(hk_card, text="💾 บันทึกคีย์ลัด", fg_color="#6d5ef8", hover_color="#5a4ce0",
                      command=self._save_hotkeys).pack(anchor="w", padx=15, pady=(0, 15))

        # Export / Import
        io_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        io_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(io_card, text="📦 Export / Import ข้อมูลทั้งหมด",
                    font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(15, 8))
        ctk.CTkLabel(io_card, text="รวม preset, combo และภาพอ้างอิงทั้งหมดไว้ในไฟล์ .zip ไฟล์เดียว "
                                    "ย้ายไปใช้เครื่องอื่นหรือสำรองไว้ได้ง่าย",
                    text_color="gray", font=ctk.CTkFont(size=11), wraplength=560, justify="left").pack(
                    anchor="w", padx=15, pady=(0, 10))

        io_btn_row = ctk.CTkFrame(io_card, fg_color="transparent")
        io_btn_row.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(io_btn_row, text="⬆️ Export เป็น .zip", fg_color="#10b981", hover_color="#0d9668",
                      command=self._export_zip).pack(side="left", padx=(0, 8))
        ctk.CTkButton(io_btn_row, text="⬇️ Import จาก .zip", fg_color="#4b5563", hover_color="#374151",
                      command=self._import_zip).pack(side="left")

        # Dependency status
        dep_card = ctk.CTkFrame(tab, corner_radius=18, fg_color="#191927")
        dep_card.pack(fill="x")
        ctk.CTkLabel(dep_card, text="🔧 สถานะไลบรารีเสริม",
                    font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(15, 8))
        cv_status = "✅ ติดตั้งแล้ว (image recognition แม่นยำสูง)" if HAS_OPENCV else "⚠️ ยังไม่ติดตั้ง (image recognition ใช้ได้แต่แม่นยำน้อยลง — pip install opencv-python)"
        gw_status = "✅ ติดตั้งแล้ว (ตรวจสอบหน้าต่างเป้าหมายใช้งานได้)" if HAS_PYGETWINDOW else "⚠️ ยังไม่ติดตั้ง (จะข้ามการเช็คหน้าต่างอัตโนมัติ — pip install pygetwindow)"
        ctk.CTkLabel(dep_card, text=f"opencv-python: {cv_status}", text_color="gray",
                    font=ctk.CTkFont(size=11), wraplength=560, justify="left").pack(anchor="w", padx=15, pady=(0, 4))
        ctk.CTkLabel(dep_card, text=f"pygetwindow: {gw_status}", text_color="gray",
                    font=ctk.CTkFont(size=11), wraplength=560, justify="left").pack(anchor="w", padx=15, pady=(0, 15))

    def _save_hotkeys(self):
        self.config_data["hotkeys"] = {
            "start": self.hk_start_menu.get().lower(),
            "stop": self.hk_stop_menu.get().lower(),
            "capture": self.hk_capture_menu.get().lower(),
        }
        save_config(self.config_data)
        self.start_btn.configure(text=f"▶  เริ่ม ({self.hk_start_menu.get()})")
        self.stop_btn.configure(text=f"■  หยุด ({self.hk_stop_menu.get()})")
        self.hotkey_hint_label.configure(text=self._hotkey_hint_text())
        messagebox.showinfo("สำเร็จ", "บันทึกคีย์ลัดแล้ว (มีผลทันที ไม่ต้องเปิดโปรแกรมใหม่)")

    def _export_zip(self):
        default_name = f"autoclicker_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        path = filedialog.asksaveasfilename(defaultextension=".zip", initialfile=default_name,
                                             filetypes=[("Zip files", "*.zip")])
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for folder in (PRESET_DIR, COMBO_DIR, IMAGE_DIR):
                    for fname in os.listdir(folder):
                        full = os.path.join(folder, fname)
                        if os.path.isfile(full):
                            zf.write(full, arcname=os.path.join(folder, fname))
            messagebox.showinfo("สำเร็จ", f"Export แล้วที่:\n{path}")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"Export ไม่สำเร็จ: {e}")

    def _import_zip(self):
        path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")])
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(".")
            self._refresh_preset_dropdowns()
            self.combo_select.configure(values=list_combos() or ["(ไม่มี)"])
            messagebox.showinfo("สำเร็จ", "Import ข้อมูลเรียบร้อยแล้ว")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"Import ไม่สำเร็จ: {e}")

    # -----------------------------------------------------------------
    def _format_elapsed(self, seconds):
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _tick_elapsed(self):
        if not self.running or self.run_start_time is None:
            return
        elapsed = time.time() - self.run_start_time
        self.elapsed_label.configure(text=self._format_elapsed(elapsed))
        self.after(200, self._tick_elapsed)

    def _reset_record(self):
        self.record_box.configure(state="normal")
        self.record_box.delete("1.0", "end")
        self.record_box.configure(state="disabled")

    def _append_record(self, text):
        elapsed = time.time() - self.run_start_time if self.run_start_time else 0
        line = f"[{self._format_elapsed(elapsed)}] {text}\n"
        self.record_box.configure(state="normal")
        self.record_box.insert("end", line)
        self.record_box.configure(state="disabled")
        self.record_box.see("end")

    # -----------------------------------------------------------------
    def start_running(self):
        if self.running:
            return
        combo_name = self.run_combo_select.get()
        if not combo_name or combo_name == "(ไม่มี)":
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือก combo ก่อน")
            return
        try:
            preset_names = load_combo(combo_name)
        except FileNotFoundError:
            messagebox.showerror("ผิดพลาด", "ไม่พบไฟล์ combo นี้")
            return

        presets_data = []
        for pname in preset_names:
            try:
                presets_data.append((pname, load_preset(pname)))
            except FileNotFoundError:
                messagebox.showerror("ผิดพลาด", f"ไม่พบ preset '{pname}'")
                return

        try:
            loop_count = int(self.loop_count_entry.get())
        except ValueError:
            loop_count = 0
        try:
            loop_pause = float(self.loop_pause_entry.get())
        except ValueError:
            loop_pause = 0.0

        max_runtime_seconds = None
        if self.autostop_var.get():
            try:
                minutes = float(self.autostop_minutes_entry.get())
                max_runtime_seconds = minutes * 60
            except ValueError:
                max_runtime_seconds = None

        natural_mode = self.natural_var.get()
        offset_px = 0
        delay_jitter_pct = 0.0
        if natural_mode:
            try:
                offset_px = int(self.offset_px_entry.get())
            except ValueError:
                offset_px = 0
            try:
                delay_jitter_pct = float(self.delay_jitter_entry.get())
            except ValueError:
                delay_jitter_pct = 0.0

        logging_enabled = self.logging_var.get()

        self.running = True
        self.run_start_time = time.time()
        self.status_badge.configure(text="●  กำลังทำงาน...", text_color="#f59e0b")
        self._reset_record()
        self.elapsed_label.configure(text="00:00")
        self.step_counter_label.configure(text="- / -")
        self.countdown_label.configure(text="—")
        self.prevnext_label.configure(text="ก่อนหน้า: —      ถัดไป: —")
        self._tick_elapsed()

        if logging_enabled:
            write_log(f"เริ่มรัน combo '{combo_name}' | loop={loop_count} | pause={loop_pause}s | "
                      f"natural_mode={natural_mode} | autostop={max_runtime_seconds}")

        self.run_thread = threading.Thread(
            target=self._run_loop,
            args=(combo_name, presets_data, loop_count, loop_pause, max_runtime_seconds,
                  natural_mode, offset_px, delay_jitter_pct, logging_enabled),
            daemon=True
        )
        self.run_thread.start()

    def stop_running(self):
        was_running = self.running
        self.running = False
        self.status_badge.configure(text="●  หยุดแล้ว", text_color="#ef4444")
        self.progress_label.configure(text="หยุดทำงานแล้ว")
        self.countdown_label.configure(text="—")
        if was_running:
            self._append_record("⏹ ผู้ใช้กดหยุดการทำงาน")
        if was_running and self.logging_var.get():
            write_log("ผู้ใช้กดหยุดการทำงาน")

    def _run_loop(self, combo_name, presets_data, loop_count, loop_pause, max_runtime_seconds,
                  natural_mode, offset_px, delay_jitter_pct, logging_enabled):
        # เรียง step ทั้งหมดในทุก preset ของ combo นี้ให้เป็น list เดียว เพื่อรู้ step ก่อนหน้า/ถัดไป และเลขลำดับรวม
        flat_steps = []
        for pname, pdata in presets_data:
            for s in pdata["steps"]:
                flat_steps.append((pname, pdata.get("window_title", ""), s))
        total_steps = len(flat_steps)

        count = 0
        try:
            while self.running:
                count += 1
                last_checked_preset = None

                for idx, (pname, window_title, s) in enumerate(flat_steps):
                    if not self.running:
                        break

                    if window_title and pname != last_checked_preset:
                        last_checked_preset = pname
                        self.after(0, lambda p=pname, w=window_title: self.progress_label.configure(
                            text=f"กำลังรอหน้าต่าง '{w}' สำหรับ preset '{p}'..."))
                        ok = check_window_title(window_title, timeout=5.0)
                        if not ok and logging_enabled:
                            write_log(f"คำเตือน: ไม่พบหน้าต่างที่มีคำว่า '{window_title}' — ดำเนินการต่อโดยไม่รอ")

                    if max_runtime_seconds is not None and (time.time() - self.run_start_time) >= max_runtime_seconds:
                        self.running = False
                        self.after(0, lambda: self.status_badge.configure(
                            text="●  หยุดอัตโนมัติ (ครบเวลาที่ตั้งไว้)", text_color="#f59e0b"))
                        self.after(0, lambda: self.progress_label.configure(text="ครบเวลาที่จำกัดไว้ — หยุดอัตโนมัติแล้ว"))
                        self.after(0, lambda: self._append_record("⏲ หยุดอัตโนมัติ: ครบเวลาที่ตั้งไว้"))
                        if logging_enabled:
                            write_log("หยุดอัตโนมัติ: ครบเวลาที่ตั้งไว้")
                        return

                    step_no = idx + 1
                    prev_name = flat_steps[idx - 1][2]["name"] if idx > 0 else "— (step แรก)"
                    next_name = flat_steps[idx + 1][2]["name"] if idx + 1 < total_steps else "— (จบรอบนี้)"

                    self.after(0, lambda p=pname, s=s, c=count: self.progress_label.configure(
                        text=f"รอบ {c} — Preset '{p}' — Step: {s['name']}"
                    ))
                    self.after(0, lambda n=step_no, t=total_steps: self.step_counter_label.configure(
                        text=f"{n} / {t}"
                    ))
                    self.after(0, lambda pv=prev_name, nx=next_name: self.prevnext_label.configure(
                        text=f"ก่อนหน้า: {pv}      ถัดไป: {nx}"
                    ))
                    self.after(0, lambda p=pname, s=s, c=count: self._append_record(
                        f"รอบ {c} | {p} → {s['name']} (delay {s['delay']}s)"
                    ))

                    x, y, click_source = resolve_click_position(s, timeout=2.0)
                    delay = s["delay"]
                    if natural_mode:
                        if delay_jitter_pct > 0:
                            jitter = delay * (delay_jitter_pct / 100.0)
                            delay = max(0.0, delay + random.uniform(-jitter, jitter))
                        if offset_px > 0 and click_source != "region":
                            x += random.randint(-offset_px, offset_px)
                            y += random.randint(-offset_px, offset_px)

                    # นับถอยหลังแบบ interrupt ได้ (เช็ค self.running ทุก 0.1s แทนการ sleep รวดเดียว)
                    remaining = delay
                    while remaining > 0 and self.running:
                        self.after(0, lambda r=remaining: self.countdown_label.configure(text=f"{r:.1f}s"))
                        step_sleep = min(0.1, remaining)
                        time.sleep(step_sleep)
                        remaining -= step_sleep
                    if not self.running:
                        break

                    self.after(0, lambda: self.countdown_label.configure(text="กำลังคลิก..."))
                    pyautogui.click(x, y)
                    self.after(0, lambda s=s, x=x, y=y: self._append_record(
                        f"  ↳ คลิก '{s['name']}' ที่ ({x}, {y})"
                    ))

                    if logging_enabled:
                        write_log(f"คลิก | preset='{pname}' | step='{s['name']}' | pos=({x},{y}) | "
                                  f"delay={delay:.2f}s | source={click_source}")

                if loop_count != 0 and count >= loop_count:
                    self.running = False
                    self.after(0, lambda: self.status_badge.configure(
                        text="●  ทำงานเสร็จสิ้น", text_color="#22c55e"))
                    self.after(0, lambda: self.progress_label.configure(text="เสร็จสิ้นทุกรอบแล้ว"))
                    self.after(0, lambda: self.countdown_label.configure(text="—"))
                    self.after(0, lambda c=count: self._append_record(f"✅ เสร็จสิ้นทุกรอบแล้ว (ครบ {c} รอบ)"))
                    if logging_enabled:
                        write_log(f"ทำงานเสร็จสิ้น (ครบ {count} รอบ)")
                    break

                if self.running and loop_pause > 0:
                    self.after(0, lambda lp=loop_pause: self._append_record(f"⏸ พัก {lp}s ก่อนรอบถัดไป"))
                    remaining = loop_pause
                    while remaining > 0 and self.running:
                        self.after(0, lambda r=remaining: self.progress_label.configure(
                            text=f"พัก {r:.1f}s ก่อนรอบถัดไป..."))
                        self.after(0, lambda r=remaining: self.countdown_label.configure(text=f"{r:.1f}s"))
                        step_sleep = min(0.1, remaining)
                        time.sleep(step_sleep)
                        remaining -= step_sleep

        except pyautogui.FailSafeException:
            self.running = False
            self.after(0, lambda: self.status_badge.configure(
                text="●  หยุดฉุกเฉิน (เมาส์ชนมุมจอ)", text_color="#f87171"))
            self.after(0, lambda: self.progress_label.configure(text="หยุดฉุกเฉิน: ตรวจพบเมาส์ชนมุมจอ"))
            self.after(0, lambda: self._append_record("🛟 หยุดฉุกเฉิน: ตรวจพบเมาส์ชนมุมจอ"))
            if logging_enabled:
                write_log("หยุดฉุกเฉิน: ตรวจพบเมาส์ชนมุมจอ (FailSafe)")

    # -----------------------------------------------------------------
    def _start_hotkey_listener(self):
        def resolve(key_name):
            return getattr(keyboard.Key, key_name, None)

        def on_press(key):
            # หมายเหตุสำคัญ: callback นี้ทำงานอยู่บน thread ของ pynput ไม่ใช่ main thread ของ Tkinter
            # ห้ามยุ่งกับ widget ตรงนี้โดยตรง ต้องส่งผ่าน self.after(0, ...) ให้ไปทำงานบน main thread เสมอ
            try:
                hk = self.config_data["hotkeys"]
                if key == resolve(hk["capture"]):
                    self.after(0, self._capture_current_position)
                elif key == resolve(hk["start"]):
                    self.after(0, self.start_running)
                elif key == resolve(hk["stop"]):
                    self.after(0, self.stop_running)
            except Exception as e:
                write_log(f"เกิดข้อผิดพลาดในการรับคีย์ลัด: {e}")

        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()


if __name__ == "__main__":
    app = AutoClickerApp()
    app.mainloop()
