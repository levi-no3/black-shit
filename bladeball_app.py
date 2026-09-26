"""Blade Ball Safe Manager - stdlib only, no injection, no executor.
Manages bladeball_autoparry.lua settings + provides a basic external auto-clicker.
The clicker does NOT run Roblox Lua and does NOT inject into Roblox.
It just left-clicks at a set CPS while toggled. Macros can still violate
Blade Ball / Roblox rules - use on an alt at your own risk.
"""
import ctypes
import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LUA_PATH = os.path.join(BASE_DIR, "bladeball_autoparry.lua")

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_F6 = 0x75
WM_HOTKEY = 0x0312

NUM_FIELDS = [
    ("TimeThreshold", r"TimeThreshold\s*=\s*([0-9.]+)"),
    ("EmergencyRadius", r"EmergencyRadius\s*=\s*([0-9.]+)"),
    ("ClashDistance", r"ClashDistance\s*=\s*([0-9.]+)"),
    ("ClashCooldown", r"ClashCooldown\s*=\s*([0-9.]+)"),
    ("NormalCooldown", r"NormalCooldown\s*=\s*([0-9.]+)"),
    ("PingOffset", r"PingOffset\s*=\s*([0-9.]+)"),
]


def click_once():
    u32 = ctypes.windll.user32
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.005)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


class Clicker:
    def __init__(self, log):
        self.log = log
        self.running = False
        self.cps = 20
        self._thread = None
        self._stop = threading.Event()

    def _loop(self):
        self.log(f"[clicker] started at {self.cps} CPS. Focus Roblox to parry.")
        interval = 1.0 / max(1, self.cps)
        while not self._stop.is_set():
            click_once()
            time.sleep(interval)
        self.log("[clicker] stopped.")

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._stop.set()


class App:
    def __init__(self, root):
        self.root = root
        root.title("Blade Ball Safe Manager (no executor)")
        root.geometry("620x640")
        root.resizable(True, True)

        self.entries = {}
        self.clicker = Clicker(self.log)

        ttk.Label(root, text="Blade Ball Safe Manager", font=("Segoe UI", 14, "bold")).pack(pady=(10, 2))
        ttk.Label(
            root,
            text="Does NOT inject into Roblox. Does NOT run .lua by itself.\nIt edits your .lua settings + gives a basic external clicker.",
            justify="center",
        ).pack(pady=(0, 8))

        # Lua section
        lua_frame = ttk.LabelFrame(root, text="1) bladeball_autoparry.lua settings")
        lua_frame.pack(fill="x", padx=10, pady=5)
        for name, _pat in NUM_FIELDS:
            row = ttk.Frame(lua_frame)
            row.pack(fill="x", padx=8, pady=2)
            ttk.Label(row, text=name, width=18).pack(side="left")
            e = ttk.Entry(row, width=12)
            e.pack(side="left")
            self.entries[name] = e

        self.visuals_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(lua_frame, text="Visuals", variable=self.visuals_var).pack(anchor="w", padx=8, pady=2)

        btn_row = ttk.Frame(lua_frame)
        btn_row.pack(fill="x", padx=8, pady=6)
        ttk.Button(btn_row, text="Reload", command=self.load_lua).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Save", command=self.save_lua).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Copy for executor", command=self.copy_lua).pack(side="left", padx=2)

        self.lua_status = ttk.Label(lua_frame, text="")
        self.lua_status.pack(anchor="w", padx=8)

        # Clicker section
        c_frame = ttk.LabelFrame(root, text="2) Safe external clicker (no injection)")
        c_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(c_frame, text="Focus Roblox, toggle with F6 or the button. Left-click = Block in Blade Ball.").pack(
            anchor="w", padx=8, pady=2
        )
        cps_row = ttk.Frame(c_frame)
        cps_row.pack(fill="x", padx=8, pady=2)
        ttk.Label(cps_row, text="CPS:").pack(side="left")
        self.cps_var = tk.IntVar(value=20)
        self.cps_scale = ttk.Scale(cps_row, from_=5, to=50, variable=self.cps_var, command=lambda *_: self.on_cps())
        self.cps_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.cps_label = ttk.Label(cps_row, text="20")
        self.cps_label.pack(side="left")

        cbtn_row = ttk.Frame(c_frame)
        cbtn_row.pack(fill="x", padx=8, pady=6)
        self.toggle_btn = ttk.Button(cbtn_row, text="Start clicker (F6)", command=self.toggle_clicker)
        self.toggle_btn.pack(side="left", padx=2)
        self.click_status = ttk.Label(cbtn_row, text="Status: OFF")
        self.click_status.pack(side="left", padx=10)

        # Log
        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_box = tk.Text(log_frame, height=10, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        self.load_lua()
        self.start_hotkey_thread()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, msg):
        def _write():
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")

        try:
            self.root.after(0, _write)
        except Exception:
            pass

    def on_cps(self):
        v = int(self.cps_var.get())
        self.cps_label.config(text=str(v))
        self.clicker.cps = v

    def load_lua(self):
        if not os.path.exists(LUA_PATH):
            self.lua_status.config(text=f"Not found: {LUA_PATH}")
            self.log(f"[lua] not found: {LUA_PATH}")
            return
        with open(LUA_PATH, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        for name, pat in NUM_FIELDS:
            m = re.search(pat, text)
            self.entries[name].delete(0, "end")
            if m:
                self.entries[name].insert(0, m.group(1))
        mv = re.search(r"Visuals\s*=\s*(true|false)", text)
        if mv:
            self.visuals_var.set(mv.group(1) == "true")
        self.lua_status.config(text=f"Loaded: {os.path.basename(LUA_PATH)}")
        self.log("[lua] settings loaded.")

    def save_lua(self):
        if not os.path.exists(LUA_PATH):
            messagebox.showerror("Missing", f"Lua file not found:\n{LUA_PATH}")
            return
        with open(LUA_PATH, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        for name, pat in NUM_FIELDS:
            val = self.entries[name].get().strip()
            try:
                float(val)
            except ValueError:
                messagebox.showerror("Invalid", f"{name} must be a number, got: {val!r}")
                return
            text = re.sub(pat, f"{name} = {val}", text, count=1)
        text = re.sub(
            r"Visuals\s*=\s*(true|false)",
            f"Visuals = {'true' if self.visuals_var.get() else 'false'}",
            text,
            count=1,
        )
        with open(LUA_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        self.lua_status.config(text="Saved.")
        self.log("[lua] settings saved.")

    def copy_lua(self):
        if not os.path.exists(LUA_PATH):
            return
        with open(LUA_PATH, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log("[lua] copied to clipboard - paste into your executor.")
        messagebox.showinfo("Copied", "Lua copied. Paste it into your executor's editor.")

    def toggle_clicker(self):
        if self.clicker.running:
            self.clicker.stop()
            self.toggle_btn.config(text="Start clicker (F6)")
            self.click_status.config(text="Status: OFF")
        else:
            self.clicker.cps = int(self.cps_var.get())
            self.clicker.start()
            self.toggle_btn.config(text="Stop clicker (F6)")
            self.click_status.config(text=f"Status: ON ({self.clicker.cps} CPS)")

    def start_hotkey_thread(self):
        def _listen():
            try:
                u32 = ctypes.windll.user32
                if not u32.RegisterHotKey(None, 1, 0, VK_F6):
                    self.log("[hotkey] F6 register failed - use the button instead.")
                    return
                self.log("[hotkey] Press F6 anywhere to toggle clicker.")

                class MSG(ctypes.Structure):
                    _fields_ = [
                        ("hwnd", ctypes.c_void_p),
                        ("message", ctypes.c_uint),
                        ("wParam", ctypes.c_void_p),
                        ("lParam", ctypes.c_void_p),
                        ("time", ctypes.c_ulong),
                        ("pt_x", ctypes.c_long),
                        ("pt_y", ctypes.c_long),
                    ]

                msg = MSG()
                while True:
                    ret = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if ret == 0:  # WM_QUIT
                        break
                    if msg.message == WM_HOTKEY:
                        try:
                            self.root.after(0, self.toggle_clicker)
                        except Exception:
                            break
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
            except Exception as e:
                self.log(f"[hotkey] disabled: {e}")

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        self._hotkey_thread = t

    def on_close(self):
        try:
            self.clicker.stop()
            ctypes.windll.user32.UnregisterHotKey(None, 1)
            ctypes.windll.user32.PostQuitMessage(0)
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
