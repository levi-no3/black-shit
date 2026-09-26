"""
AI Browser Mirror - Desktop Viewer
----------------------------------
A desktop window where you can WATCH what the AI does in the browser live.

How it works:
- Click "Start Browser" -> opens a real Chromium window (headed) controlled by this app.
- The left panel mirrors that browser live (screenshot every ~0.6s).
- The right panel logs every action with timestamp + actor (YOU / AI).
- AI drives the SAME browser via ai_command.json bridge (see ai_drive.py),
  so you see AI navigation/clicks/typing live in this window.

Files used (same folder):
- ai_command.json   : AI writes a command, app executes it
- ai_result.json    : app writes result of last AI command
- ai_status.json    : app writes current url/title for AI to read
- browser_history.jsonl : append-only log of all actions
- mirror_latest.jpg : latest screenshot, for external viewing

Run:  python browser_mirror_app.py
Requires: pip install playwright pillow  +  python -m playwright install chromium
"""
import io
import json
import os
import time
import datetime
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CMD_FILE = os.path.join(BASE_DIR, "ai_command.json")
RESULT_FILE = os.path.join(BASE_DIR, "ai_result.json")
STATUS_FILE = os.path.join(BASE_DIR, "ai_status.json")
HISTORY_FILE = os.path.join(BASE_DIR, "browser_history.jsonl")
MIRROR_FILE = os.path.join(BASE_DIR, "mirror_latest.jpg")

VIEW_W = 760
VIEW_H = 520


def ts_now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def log_to_file(actor, action, detail=""):
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "actor": actor,
                "action": action,
                "detail": detail,
            }) + "\n")
    except Exception:
        pass


class MirrorApp:
    def __init__(self, root):
        self.root = root
        root.title("AI Browser Mirror - Watch AI Live")
        root.geometry("1120x720")
        root.minsize(950, 600)

        # Playwright handles (all used ONLY in Tk main thread)
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.pages = []
        self.lock = threading.Lock()  # guards file polling vs UI, playwright stays in main thread
        self.running = False
        self.photo = None
        self.last_cmd_mtime = 0
        self.demo_running = False
        self.turbo_var = None  # created in _build_ui
        self.front_var = None
        self.live_var = None
        self.last_frame_t = 0
        self.fps = 0.0
        self.img_w = VIEW_W
        self.img_h = VIEW_H
        self.page_w = 1280
        self.page_h = 800

        self._build_ui()
        self.log("APP", "Ready. Click 'Start Browser', then 'Demo AI run' to see a live demo.")
        self.log("TIP", "LIVE mode streams the real browser ~6fps. Click the mirror to click the page.")
        # start loops
        self.root.after(500, self.update_mirror)
        self.root.after(800, self.poll_ai_command)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(top, text="◀", width=3, command=lambda: self.user_nav("back")).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="▶", width=3, command=lambda: self.user_nav("forward")).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="⟳", width=3, command=lambda: self.user_nav("reload")).pack(side=tk.LEFT, padx=2)

        self.url_var = tk.StringVar(value="https://example.com")
        url_entry = ttk.Entry(top, textvariable=self.url_var, width=60)
        url_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        url_entry.bind("<Return>", lambda e: self.user_go())

        ttk.Button(top, text="Go", command=self.user_go).pack(side=tk.LEFT, padx=2)

        self.headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="headless", variable=self.headless_var).pack(side=tk.LEFT, padx=6)

        ttk.Button(top, text="Start Browser", command=self.start_browser).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Stop", command=self.stop_browser).pack(side=tk.LEFT, padx=2)

        tabbar = ttk.Frame(self.root, padding=(6, 0))
        tabbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(tabbar, text="+ New Tab", command=lambda: self.user_new_tab()).pack(side=tk.LEFT, padx=2)
        ttk.Label(tabbar, text="Tab:").pack(side=tk.LEFT, padx=(8, 2))
        self.tab_var = tk.StringVar(value="no tabs")
        self.tab_combo = ttk.Combobox(tabbar, textvariable=self.tab_var, width=80, state="readonly")
        self.tab_combo.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        self.tab_combo.bind("<<ComboboxSelected>>", self.user_switch_tab)

        hint = ttk.Label(
            self.root,
            text="1. Start Browser  →  2. Demo AI run (or let AI use ai_drive.py)  →  3. Watch the live mirror below",
            foreground="#444",
        )
        hint.pack(side=tk.TOP, fill=tk.X, padx=8)

        main = ttk.Frame(self.root, padding=6)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(main, text="LIVE MIRROR (what AI sees / does)", padding=6)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        livebar = ttk.Frame(left)
        livebar.pack(side=tk.TOP, fill=tk.X)
        self.live_var = tk.StringVar(value="● LIVE")
        ttk.Label(livebar, textvariable=self.live_var, foreground="#c00", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.fps_var = tk.StringVar(value="-- fps")
        ttk.Label(livebar, textvariable=self.fps_var, foreground="#555").pack(side=tk.LEFT, padx=8)
        self.turbo_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(livebar, text="Turbo live (~2fps)", variable=self.turbo_var).pack(side=tk.LEFT, padx=8)
        self.front_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(livebar, text="Pop real browser to front on AI action", variable=self.front_var).pack(side=tk.LEFT, padx=8)
        ttk.Button(livebar, text="Focus real browser", command=self.focus_real).pack(side=tk.RIGHT, padx=2)
        ttk.Label(livebar, text="click mirror = click page").pack(side=tk.RIGHT, padx=8)

        self.img_label = ttk.Label(left, text="Browser stopped.\nClick 'Start Browser'.", anchor="center", justify="center")
        self.img_label.pack(fill=tk.BOTH, expand=True)
        self.img_label.bind("<Button-1>", self.mirror_click)

        right = ttk.Frame(main, width=340)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        right.pack_propagate(False)

        ttk.Label(right, text="Action log (YOU + AI):").pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(right, width=42, height=28, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(right, text="AI status:").pack(anchor="w", pady=(6, 0))
        self.ai_status_var = tk.StringVar(value="AI idle - no command")
        ttk.Label(right, textvariable=self.ai_status_var, foreground="#0a6", wraplength=320).pack(anchor="w")

        bottom = ttk.Frame(self.root, padding=6)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Button(bottom, text="▶ Demo AI run (watch me browse)", command=self.run_demo).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Clear log", command=self.clear_log).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Open history file", command=self.open_history).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#555").pack(side=tk.RIGHT, padx=8)

    # ---------- logging ----------
    def log(self, actor, msg):
        line = f"[{ts_now()}] [{actor}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        log_to_file(actor, msg)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state="disabled")

    def open_history(self):
        self.log("APP", f"History file: {HISTORY_FILE}")
        try:
            os.startfile(HISTORY_FILE)  # Windows
        except Exception as e:
            messagebox.showinfo("History", f"{HISTORY_FILE}\n\n{e}")

    # ---------- browser lifecycle ----------
    def start_browser(self):
        if self.browser:
            self.log("APP", "Browser already running.")
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            messagebox.showerror("Missing dep", "Run: pip install playwright pillow")
            return
        try:
            self.status_var.set("Starting browser...")
            self.log("APP", "Launching shared Chromium workspace (CDP :9222)...")
            self.pw = sync_playwright().start()
            # Persistent context + remote debugging port = ONE shared browser.
            # The agent attaches to it via CDP, so everything the agent does
            # happens in THIS visible window (your "workspace"), not a hidden one.
            profile = os.path.join(BASE_DIR, ".browser_profile")
            os.makedirs(profile, exist_ok=True)
            self.browser = self.pw.chromium.launch_persistent_context(
                user_data_dir=profile,
                headless=self.headless_var.get(),
                viewport={"width": 1280, "height": 800},
                args=["--remote-debugging-port=9222"],
            )
            self.context = self.browser  # persistent context IS the context
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = self.context.new_page()
            self.pages = [p for p in self.context.pages if not p.is_closed()]
            self.page.goto("https://example.com", wait_until="domcontentloaded", timeout=30000)
            self.url_var.set(self.page.url)
            self.status_var.set("Running - mirror live")
            self.log("YOU", f"Browser started -> {self.page.url}")
            self.running = True
            self.refresh_tabs_ui()
        except Exception as e:
            self.log("ERROR", f"Start failed: {e}")
            self.status_var.set("Start failed")
            self.safe_close()

    def safe_close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            # with persistent context, browser IS the context - don't double close
            if self.browser and self.browser is not self.context:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        self.browser = None
        self.context = None
        self.page = None
        self.pages = []
        self.pw = None
        self.running = False

    def stop_browser(self):
        if not self.browser:
            return
        self.log("YOU", "Browser stopped.")
        self.safe_close()
        self.status_var.set("Stopped")
        self.img_label.configure(image="", text="Browser stopped.\nClick 'Start Browser'.")

    def on_close(self):
        self.safe_close()
        # clean bridge files so next run is fresh (keep history)
        for f in (CMD_FILE, RESULT_FILE):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        self.root.destroy()

    # ---------- user actions ----------
    def need_page(self):
        if not self.page:
            messagebox.showinfo("No browser", "Click 'Start Browser' first.")
            return False
        return True

    def user_go(self):
        if not self.need_page():
            return
        url = self.url_var.get().strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        try:
            self.log("YOU", f"Navigate -> {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self.url_var.set(self.page.url)
            self.log("YOU", f"Loaded: {self.page.title()} | {self.page.url}")
        except Exception as e:
            self.log("ERROR", f"Navigate failed: {e}")

    def user_nav(self, kind):
        if not self.need_page():
            return
        try:
            if kind == "back":
                self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                self.log("YOU", "Back")
            elif kind == "forward":
                self.page.go_forward(wait_until="domcontentloaded", timeout=15000)
                self.log("YOU", "Forward")
            elif kind == "reload":
                self.page.reload(wait_until="domcontentloaded", timeout=15000)
                self.log("YOU", "Reload")
            self.url_var.set(self.page.url)
        except Exception as e:
            self.log("ERROR", f"{kind} failed: {e}")

    # ---------- tabs ----------
    def refresh_tabs_ui(self):
        try:
            if not self.context:
                return
            # drop closed pages
            alive = [p for p in self.context.pages if not p.is_closed()]
            self.pages = alive
            if self.page and self.page.is_closed():
                self.page = alive[-1] if alive else None
            labels = []
            for i, p in enumerate(self.pages):
                try:
                    t = p.title() or "New Tab"
                except Exception:
                    t = "Tab"
                try:
                    u = p.url
                except Exception:
                    u = ""
                labels.append(f"[{i}] {t[:40]} | {u[:60]}")
            self.tab_combo["values"] = labels
            if self.page and self.page in self.pages:
                idx = self.pages.index(self.page)
                if idx < len(labels):
                    self.tab_var.set(labels[idx])
            self.status_var.set(f"Running - {len(self.pages)} tab(s) - mirror live")
        except Exception:
            pass

    def user_new_tab(self, url=None):
        if not self.context:
            messagebox.showinfo("No browser", "Click 'Start Browser' first.")
            return None
        try:
            p = self.context.new_page()
            target = url or "https://www.youtube.com"
            self.log("YOU", f"New tab -> {target}")
            p.goto(target, wait_until="domcontentloaded", timeout=30000)
            self.page = p
            self.pages = [x for x in self.context.pages if not x.is_closed()]
            self.url_var.set(self.page.url)
            self.log("YOU", f"Tab loaded: {self.page.title()} | {self.page.url}")
            self.refresh_tabs_ui()
            try:
                p.bring_to_front()
            except Exception:
                pass
            return p
        except Exception as e:
            self.log("ERROR", f"New tab failed: {e}")
            return None

    def user_switch_tab(self, event=None):
        try:
            val = self.tab_var.get()
            # format "[i] ..."
            idx = int(val.split("]")[0].strip(" ["))
            if 0 <= idx < len(self.pages):
                self.page = self.pages[idx]
                self.url_var.set(self.page.url)
                try:
                    self.page.bring_to_front()
                except Exception:
                    pass
                self.log("YOU", f"Switched to tab {idx}: {self.page.url}")
        except Exception as e:
            self.log("ERROR", f"Switch tab failed: {e}")

    # ---------- live mirror ----------
    def update_mirror(self):
        try:
            if self.page and self.browser:
                # if current tab was closed, fall back to a live one
                try:
                    if self.page.is_closed():
                        alive = [p for p in self.context.pages if not p.is_closed()]
                        if alive:
                            self.page = alive[-1]
                            self.pages = alive
                        else:
                            self.root.after(600, self.update_mirror)
                            return
                except Exception:
                    pass
                t0 = time.time()
                data = self.page.screenshot(type="jpeg", quality=25, timeout=8000)
                shot_ms = (time.time() - t0) * 1000
                # auto-degrade: heavy pages (ads/video) make screenshots slow and
                # freeze the UI. Drop to calm mode instead of hanging.
                try:
                    hist = getattr(self, "_shot_hist", [])
                    hist.append(shot_ms)
                    self._shot_hist = hist[-4:]
                    if (len(self._shot_hist) == 4 and all(x > 700 for x in self._shot_hist)
                            and self.turbo_var and self.turbo_var.get()):
                        self.turbo_var.set(False)
                        self.log("APP", "AUTO calm mode: page too heavy for Turbo (screenshots slow). "
                                        "UI stays responsive; real browser window is still 100% live.")
                except Exception:
                    pass
                # save for external viewing
                try:
                    with open(MIRROR_FILE, "wb") as f:
                        f.write(data)
                except Exception:
                    pass
                from PIL import Image, ImageTk
                img = Image.open(io.BytesIO(data))
                self.page_w, self.page_h = img.size
                img.thumbnail((VIEW_W, VIEW_H))
                self.img_w, self.img_h = img.size
                self.photo = ImageTk.PhotoImage(img)
                self.img_label.configure(image=self.photo, text="")
                # fps meter
                try:
                    now = time.time()
                    if self.last_frame_t:
                        dt = now - self.last_frame_t
                        inst = 1.0 / dt if dt > 0 else 0
                        self.fps = self.fps * 0.8 + inst * 0.2 if self.fps else inst
                        self.fps_var.set(f"{self.fps:.1f} fps")
                    self.last_frame_t = now
                    self.live_var.set("● LIVE")
                except Exception:
                    pass
                # update status file for AI (throttled: every ~1.5s, not every frame)
                try:
                    self._mirror_ticks = getattr(self, "_mirror_ticks", 0) + 1
                    if self._mirror_ticks % 3 == 0:
                        tabs = []
                        try:
                            for i, p in enumerate(self.context.pages):
                                if not p.is_closed():
                                    tabs.append({"index": i, "url": p.url, "title": p.title()})
                        except Exception:
                            pass
                        status = {
                            "url": self.page.url,
                            "title": self.page.title(),
                            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                            "mirror": MIRROR_FILE,
                            "tabs": tabs,
                            "active_tab": self.pages.index(self.page) if self.page in self.pages else 0,
                        }
                        tmp = STATUS_FILE + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(status, f, indent=2)
                        os.replace(tmp, STATUS_FILE)
                        self.refresh_tabs_ui()
                except Exception:
                    pass
                # keep url bar in sync (only if user isn't typing: check focus)
                try:
                    if self.root.focus_get() is None or str(self.root.focus_get()).find("entry") == -1:
                        self.url_var.set(self.page.url)
                except Exception:
                    pass
        except Exception as e:
            # don't spam log every frame; update status occasionally
            self.status_var.set(f"Mirror error: {e}")
            try:
                self.live_var.set("○ PAUSED")
            except Exception:
                pass
        finally:
            try:
                turbo = self.turbo_var.get() if self.turbo_var else True
            except Exception:
                turbo = True
            # Turbo 500ms (safe for UI thread); calm 1200ms. Never 150ms:
            # screenshots block the Tk thread and hang the app on heavy pages.
            self.root.after(500 if turbo else 1200, self.update_mirror)

    def focus_real(self):
        """Bring the real (100% live) Chromium window to the front."""
        try:
            if self.page:
                self.page.bring_to_front()
                self.log("YOU", "Focused real browser (100% live view).")
        except Exception as e:
            self.log("ERROR", f"Focus failed: {e}")

    def mirror_click(self, event):
        """Click-through: clicking the mirror clicks the real page. Makes it feel live."""
        if not self.page:
            return
        try:
            lx, ly = event.x, event.y
            lw = self.img_label.winfo_width()
            lh = self.img_label.winfo_height()
            # image is centered in label; compute offset
            ox = (lw - self.img_w) / 2 + (lw - self.img_w) % 2 * 0
            oy = (lh - self.img_h) / 2
            ix, iy = lx - ox, ly - oy
            if 0 <= ix <= self.img_w and 0 <= iy <= self.img_h:
                sx = self.page_w / self.img_w
                sy = self.page_h / self.img_h
                self.page.mouse.click(int(ix * sx), int(iy * sy))
                self.log("YOU", f"Mirror click -> ({int(ix*sx)}, {int(iy*sy)})")
        except Exception as e:
            self.log("ERROR", f"Mirror click failed: {e}")

    # ---------- AI bridge ----------
    def poll_ai_command(self):
        try:
            if os.path.exists(CMD_FILE):
                mtime = os.path.getmtime(CMD_FILE)
                if mtime != self.last_cmd_mtime:
                    self.last_cmd_mtime = mtime
                    self.execute_ai_command_file()
        except Exception as e:
            self.ai_status_var.set(f"bridge error: {e}")
        finally:
            self.root.after(800, self.poll_ai_command)

    def execute_ai_command_file(self):
        try:
            with open(CMD_FILE, "r", encoding="utf-8") as f:
                cmd = json.load(f)
        except Exception as e:
            self.write_result({"ok": False, "error": f"bad command file: {e}"})
            return
        result = self.execute_ai_command(cmd)
        self.write_result(result)
        # remove command so it runs once
        try:
            os.remove(CMD_FILE)
        except Exception:
            pass

    def write_result(self, result):
        try:
            result["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
            tmp = RESULT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            os.replace(tmp, RESULT_FILE)
        except Exception:
            pass

    def execute_ai_command(self, cmd):
        """Runs in Tk main thread so playwright stays thread-safe."""
        action = str(cmd.get("action", "")).lower()
        self.ai_status_var.set(f"AI: {action} {cmd.get('url','') or cmd.get('selector','') or ''}")
        if not self.page:
            msg = "Browser not started - click Start Browser first"
            self.log("AI", f"{action} IGNORED ({msg})")
            return {"ok": False, "error": msg}
        try:
            if action == "navigate":
                url = cmd.get("url", "")
                if "://" not in url:
                    url = "https://" + url
                self.log("AI", f"Navigate -> {url}")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.url_var.set(self.page.url)
                out = {"ok": True, "url": self.page.url, "title": self.page.title()}
                self.log("AI", f"Loaded: {out['title']} | {out['url']}")
                return out
            elif action == "click":
                sel = cmd.get("selector", "")
                self.log("AI", f"Click -> {sel}")
                self.page.click(sel, timeout=15000)
                return {"ok": True, "url": self.page.url, "title": self.page.title()}
            elif action == "type":
                sel = cmd.get("selector", "")
                text = cmd.get("text", "")
                enter = bool(cmd.get("enter", False))
                self.log("AI", f"Type -> {sel} : {text!r}")
                self.page.fill(sel, text, timeout=15000)
                if enter:
                    self.page.press(sel, "Enter")
                return {"ok": True, "url": self.page.url}
            elif action == "press":
                sel = cmd.get("selector", "body")
                key = cmd.get("key", "Enter")
                self.log("AI", f"Press {key} on {sel}")
                self.page.press(sel, key, timeout=10000)
                return {"ok": True}
            elif action == "scroll":
                y = int(cmd.get("y", 500))
                self.log("AI", f"Scroll down {y}px")
                self.page.mouse.wheel(0, y)
                return {"ok": True}
            elif action == "back":
                self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                self.log("AI", "Back")
                return {"ok": True, "url": self.page.url}
            elif action == "forward":
                self.page.go_forward(wait_until="domcontentloaded", timeout=15000)
                self.log("AI", "Forward")
                return {"ok": True, "url": self.page.url}
            elif action == "get_text":
                sel = cmd.get("selector", "body")
                t = self.page.inner_text(sel, timeout=10000)[:4000]
                self.log("AI", f"Read text from {sel} ({len(t)} chars)")
                return {"ok": True, "text": t, "url": self.page.url}
            elif action == "screenshot":
                self.log("AI", f"Screenshot saved -> {MIRROR_FILE}")
                return {"ok": True, "mirror": MIRROR_FILE, "url": self.page.url}
            elif action == "new_tab":
                url = cmd.get("url", "https://www.youtube.com")
                if "://" not in url:
                    url = "https://" + url
                self.log("AI", f"New tab -> {url}")
                p = self.context.new_page()
                p.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.page = p
                self.pages = [x for x in self.context.pages if not x.is_closed()]
                self.url_var.set(self.page.url)
                try:
                    p.bring_to_front()
                except Exception:
                    pass
                self.refresh_tabs_ui()
                out = {"ok": True, "url": self.page.url, "title": self.page.title(),
                       "tabs": len(self.pages)}
                self.log("AI", f"Tab opened: {out['title']} | {out['url']}")
                return out
            elif action == "tabs":
                tabs = [{"index": i, "url": p.url, "title": p.title()}
                        for i, p in enumerate(self.pages) if not p.is_closed()]
                return {"ok": True, "tabs": tabs}
            elif action == "switch_tab":
                idx = int(cmd.get("index", 0))
                alive = [p for p in self.context.pages if not p.is_closed()]
                self.pages = alive
                if 0 <= idx < len(alive):
                    self.page = alive[idx]
                    self.url_var.set(self.page.url)
                    try:
                        self.page.bring_to_front()
                    except Exception:
                        pass
                    self.refresh_tabs_ui()
                    self.log("AI", f"Switched to tab {idx}: {self.page.url}")
                    return {"ok": True, "url": self.page.url, "title": self.page.title()}
                return {"ok": False, "error": f"tab {idx} out of range"}
            else:
                return {"ok": False, "error": f"unknown action: {action}"}
        except Exception as e:
            self.log("AI-ERROR", f"{action} failed: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            try:
                self.url_var.set(self.page.url)
            except Exception:
                pass
            # pop the REAL browser to front so user watches 100% live motion
            try:
                if self.front_var and self.front_var.get() and self.page:
                    self.page.bring_to_front()
            except Exception:
                pass

    # ---------- demo ----------
    def run_demo(self):
        if not self.need_page():
            return
        if self.demo_running:
            self.log("APP", "Demo already running...")
            return
        self.demo_running = True
        self.log("AI", "Demo run started - watch the mirror!")
        steps = [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "navigate", "url": "https://en.wikipedia.org/wiki/Web_browser"},
            {"action": "scroll", "y": 800},
            {"action": "navigate", "url": "https://news.ycombinator.com"},
        ]
        self._demo_step(steps, 0)

    def _demo_step(self, steps, i):
        if i >= len(steps) or not self.page:
            self.demo_running = False
            self.log("AI", "Demo finished.")
            self.ai_status_var.set("AI idle - demo done")
            return
        res = self.execute_ai_command(steps[i])
        # next step after 2.5s so user can SEE each page in the mirror
        self.root.after(2500, lambda: self._demo_step(steps, i + 1))


def main():
    root = tk.Tk()
    # nicer theme if available
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    MirrorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
