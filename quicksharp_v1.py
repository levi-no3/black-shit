"""
QuickSharp V1 — compile your projects with simple labels + descriptions.
Compact soft-rounded UI (CustomTkinter) in the KG Perfect Penmanship font,
warm-dark palette. Saves to quicksharp_data.json.

Setup:  pip install customtkinter pillow
Run:    python quicksharp_v1.py
"""
import ctypes
import json
import os
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import PhotoImage, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from quicksharp_brain import Brain, SharpAPI, load_api_key, save_api_key
import queue

APP_NAME = "QuickSharp"
DATA_FILE = Path(__file__).parent / "quicksharp_data.json"
FONT_DIR = Path(__file__).parent / "assets" / "fonts"
BOLT_PATH = Path(__file__).parent / "assets" / "bolt_orange.png"

# ── palette (warm dark) ──
BG       = "#1f1e1c"
SIDEBAR  = "#171614"
CARD     = "#282723"
INPUT_BG = "#2e2d29"
DIVIDER  = "#383732"
BORDER   = "#4a4944"
TEXT     = "#f0ebe1"
MUTED    = "#a8a196"
FAINT    = "#736e63"
ACCENT   = "#d97757"
CREAM    = "#f0ebe1"
INK      = "#1f1e1c"

FONT_CANDIDATES = ["KG Perfect Penmanship", "Ink Free", "Segoe Print", "Segoe Script"]
MONO = "Consolas"

DEFAULT_COMMANDS = {
    "Python": ("python -m py_compile main.py", "python main.py"),
    "C#": ("dotnet build", "dotnet run"),
    "C++": ("g++ main.cpp -o main", ".\\main.exe"),
    "JavaScript": ("npm install", "npm start"),
    "TypeScript": ("npm run build", "npm start"),
    "Java": ("javac Main.java", "java Main"),
    "Go": ("go build -o app .", ".\\app.exe"),
    "Rust": ("cargo build", "cargo run"),
    "Lua": ("luac -p main.lua", "lua main.lua"),
    "HTML": ("echo No compile needed", "start index.html"),
    "Other": ("", ""),
}
LANGS = ["Python", "C#", "C++", "JavaScript", "TypeScript", "Java", "Go", "Rust", "Lua", "HTML", "Other"]


def load_font():
    """Register the bundled KG Perfect Penmanship font with Windows (session-only)."""
    for f in ("KGPerfectPenmanship.ttf", "KGPerfectPenmanship.otf"):
        p = FONT_DIR / f
        if p.exists():
            try:
                ctypes.windll.gdi32.AddFontResourceW(str(p.resolve()))
                break
            except Exception:
                continue


def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [{
        "label": "Demo API",
        "description": "Example entry to show the layout. Edit it or add your own above.",
        "language": "Python",
        "path": str(Path(__file__).parent),
        "build": "python -m py_compile quicksharp_v1.py",
        "run": "python quicksharp_v1.py",
        "last_status": "idle",
        "last_build": "",
    }]


def save_data(projects):
    try:
        DATA_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")
    except Exception as e:
        print("save failed:", e)


class QuickSharp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("QuickSharp")
        self.geometry("1060x700")
        self.minsize(880, 600)
        self.configure(fg_color=BG)
        try:
            if BOLT_PATH.exists():
                self.iconphoto(True, PhotoImage(file=str(BOLT_PATH)))
        except Exception:
            pass
        self.projects = load_data()
        self.q = ""
        self.lang = "All"
        self.selected = None
        self.hand = self._pick_hand()
        self._bolt_imgs = {}
        self.brain = Brain()
        self.api = SharpAPI()
        self.sharp_mode = "instant"
        self._gen_source = None
        self.idea_hist = []
        self._generating = False
        self._gen_queue = None
        self._build()
        self.refresh_all()
        self.set_sharp_mode("instant")
        self.log("Ready. Name a project above, or pick one from the list.")

    # ── fonts / icons ──
    def _pick_hand(self):
        try:
            fams = set(self.tk.call("font", "families"))
        except Exception:
            fams = set()
        for f in FONT_CANDIDATES:
            if f in fams:
                return f
        return "Segoe Print"

    def F(self, size, bold=False):
        return ctk.CTkFont(family=self.hand, size=size, weight="bold" if bold else "normal")

    def bolt(self, w, h):
        key = (w, h)
        if key not in self._bolt_imgs and BOLT_PATH.exists():
            self._bolt_imgs[key] = ctk.CTkImage(
                light_image=Image.open(BOLT_PATH),
                dark_image=Image.open(BOLT_PATH), size=(w, h))
        return self._bolt_imgs.get(key)

    # ── layout ──
    def _build(self):
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_side()
        ctk.CTkFrame(self, fg_color=DIVIDER, corner_radius=0, width=1).grid(
            row=0, column=1, sticky="ns")
        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=2, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        # hero
        hero = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        hero.grid(row=0, column=0, sticky="ew", padx=32, pady=(22, 0))
        row = ctk.CTkFrame(hero, fg_color=BG, corner_radius=0)
        row.pack()
        ctk.CTkLabel(row, text="", image=self.bolt(26, 35)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row, text="You're set up.", font=self.F(28), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(hero, text="Label a project, describe it briefly, then compile it.",
                     font=self.F(15), text_color=MUTED).pack(pady=(0, 12))

        # quick-add pill card
        add = ctk.CTkFrame(hero, fg_color=INPUT_BG, corner_radius=22,
                           border_width=1, border_color=BORDER)
        add.pack(fill="x", padx=70)
        add.grid_columnconfigure(0, weight=1)
        self.quick = ctk.CTkEntry(add, placeholder_text="Name a project\u2026  e.g.  Billing API \u2014 Stripe webhooks in ./api",
                                  font=self.F(15), fg_color="transparent", border_width=0,
                                  text_color=TEXT, placeholder_text_color=FAINT, height=42)
        self.quick.grid(row=0, column=0, sticky="ew", padx=(18, 6), pady=8)
        self.quick.bind("<Return>", self._quick_add)
        ctk.CTkButton(add, text="Add", font=self.F(15, True), fg_color=CREAM,
                      text_color=INK, hover_color="#ddd6c8", corner_radius=16,
                      width=68, height=30, command=lambda: self._quick_add(None)).grid(
            row=0, column=1, padx=(0, 10), pady=8)

        # filter row
        filt = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        filt.grid(row=1, column=0, sticky="ew", padx=40, pady=(12, 4))
        self.count = ctk.CTkLabel(filt, text="", font=self.F(13), text_color=FAINT)
        self.count.pack(side="left")
        self.lang_var = ctk.StringVar(value="All")
        self.lang_btn = self._lang_button(filt, self.lang_var, ["All"] + LANGS, self._apply_lang)
        self.lang_btn.configure(width=104)
        self.lang_btn.pack(side="right")

        # project cards (rounded scroll area)
        self.cards = ctk.CTkScrollableFrame(main, fg_color=BG, corner_radius=0,
                                            scrollbar_button_color=DIVIDER,
                                            scrollbar_button_hover_color=BORDER)
        self.cards.grid(row=2, column=0, sticky="nsew", padx=32, pady=(2, 6))

        # output console (rounded panel)
        out = ctk.CTkFrame(main, fg_color=SIDEBAR, corner_radius=18,
                           border_width=1, border_color=DIVIDER)
        out.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 14))
        out.grid_columnconfigure(0, weight=1)
        hd = ctk.CTkFrame(out, fg_color="transparent", corner_radius=0)
        hd.grid(row=0, column=0, sticky="ew", padx=16, pady=(8, 0))
        ctk.CTkLabel(hd, text="Output", font=self.F(15, True), text_color=TEXT).pack(side="left")
        self.out_meta = ctk.CTkLabel(hd, text="", font=self.F(12), text_color=FAINT)
        self.out_meta.pack(side="left", padx=(8, 0))
        ctk.CTkButton(hd, text="Clear", font=self.F(13), fg_color="transparent",
                      text_color=MUTED, hover_color=CARD, corner_radius=11,
                      width=60, height=26, command=self._clear_log).pack(side="right")
        self.console = ctk.CTkTextbox(out, height=76, corner_radius=13,
                                      fg_color="#131210", text_color=MUTED,
                                      font=(MONO, 11), border_width=0, wrap="word")
        self.console.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.console.configure(state="disabled")
        self._build_ideas(main)

    # ── sidebar ──
    def _build_side(self):
        side = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=228)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(4, weight=1)
        logo = ctk.CTkFrame(side, fg_color="transparent", corner_radius=0)
        logo.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 0))
        ctk.CTkLabel(logo, text="", image=self.bolt(16, 21)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(logo, text="QuickSharp", font=self.F(21, True),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(side, text="V1  \u00b7  compile fast", font=self.F(13),
                     text_color=FAINT).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))
        nav = ctk.CTkFrame(side, fg_color="transparent", corner_radius=0)
        nav.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.nav_projects = ctk.CTkButton(nav, text="Projects", font=self.F(14, True),
                                          fg_color=CARD, text_color=TEXT, hover_color=CARD,
                                          corner_radius=14, height=32, command=self.show_projects)
        self.nav_projects.pack(fill="x", pady=(0, 6))
        self.nav_ideas = ctk.CTkButton(nav, text="Ideas", font=self.F(14),
                                       fg_color="transparent", text_color=MUTED, hover_color=CARD,
                                       corner_radius=14, height=32, command=self.show_ideas)
        self.nav_ideas.pack(fill="x")
        self.search = ctk.CTkEntry(side, placeholder_text="Search", font=self.F(15),
                                   fg_color=INPUT_BG, border_color=BORDER, corner_radius=18,
                                   text_color=TEXT, placeholder_text_color=FAINT, height=36)
        self.search.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.search.bind("<KeyRelease>", lambda e: self._on_search())
        self.side_list = ctk.CTkScrollableFrame(side, fg_color="transparent", corner_radius=0,
                                                scrollbar_button_color=DIVIDER,
                                                scrollbar_button_hover_color=BORDER)
        self.side_list.grid(row=4, column=0, sticky="nsew", padx=8)
        foot = ctk.CTkFrame(side, fg_color="transparent", corner_radius=0)
        foot.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 14))
        ctk.CTkButton(foot, text="+  New project", font=self.F(15, True),
                      fg_color=INPUT_BG, text_color=TEXT, hover_color=CARD,
                      border_width=1, border_color=BORDER, corner_radius=18,
                      height=38, command=lambda: self.open_editor()).pack(fill="x")
        self.side_stats = ctk.CTkLabel(foot, text="", font=self.F(12), text_color=FAINT)
        self.side_stats.pack(pady=(8, 0))

    # ── ideas view (mini-LLM brainstorming) ──
    def _build_ideas(self, main):
        v = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        v.grid(row=0, column=0, rowspan=4, sticky="nsew")
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(2, weight=1)
        self.view_ideas = v
        head = ctk.CTkFrame(v, fg_color=BG, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew", padx=32, pady=(22, 0))
        row = ctk.CTkFrame(head, fg_color=BG, corner_radius=0)
        row.pack()
        ctk.CTkLabel(row, text="", image=self.bolt(22, 30)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row, text="Ideas", font=self.F(28), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text="Brainstorm with Sharp — instant answers, web search, or offline.",
                     font=self.F(15), text_color=MUTED).pack(pady=(0, 10))
        bar = ctk.CTkFrame(head, fg_color=INPUT_BG, corner_radius=18,
                           border_width=1, border_color=BORDER)
        bar.pack(fill="x", padx=70)
        bar.grid_columnconfigure(4, weight=1)
        self.btn_instant = ctk.CTkButton(bar, text="Instant", font=self.F(14, True),
                                         fg_color=CREAM, text_color=INK, hover_color="#ddd6c8",
                                         corner_radius=14, width=70, height=30,
                                         command=lambda: self.set_sharp_mode("instant"))
        self.btn_instant.grid(row=0, column=0, padx=(10, 4), pady=8)
        self.btn_search = ctk.CTkButton(bar, text="Search", font=self.F(14),
                                        fg_color="transparent", text_color=MUTED, hover_color=CARD,
                                        corner_radius=14, width=70, height=30,
                                        command=lambda: self.set_sharp_mode("search"))
        self.btn_search.grid(row=0, column=1, padx=(0, 4), pady=8)
        self.btn_local = ctk.CTkButton(bar, text="Local", font=self.F(14),
                                       fg_color="transparent", text_color=MUTED, hover_color=CARD,
                                       corner_radius=14, width=60, height=30,
                                       command=lambda: self.set_sharp_mode("local"))
        self.btn_local.grid(row=0, column=2, padx=(0, 4), pady=8)
        self.brain_btn = ctk.CTkButton(bar, text="Load", font=self.F(14, True), fg_color=CREAM,
                                       text_color=INK, hover_color="#ddd6c8", corner_radius=14,
                                       width=64, height=30, command=self._toggle_brain)
        self.brain_btn.grid(row=0, column=3, padx=(0, 6), pady=8)
        self.brain_status = ctk.CTkLabel(bar, text="", font=self.F(14), text_color=MUTED)
        self.brain_status.grid(row=0, column=4, sticky="w", padx=(4, 8), pady=8)
        ctk.CTkButton(bar, text="Clear", font=self.F(14), fg_color="transparent",
                      text_color=MUTED, hover_color=CARD, corner_radius=14,
                      width=60, height=30, command=self._clear_ideas).grid(
            row=0, column=5, padx=(0, 10), pady=8)
        self.key_row = ctk.CTkFrame(head, fg_color="transparent", corner_radius=0)
        self.key_row.pack(fill="x", padx=70, pady=(8, 0))
        self.key_row.grid_columnconfigure(0, weight=1)
        self.key_entry = ctk.CTkEntry(self.key_row,
                                      placeholder_text="Paste Gemini API key… (free at aistudio.google.com/apikey)",
                                      font=self.F(14), fg_color=INPUT_BG, text_color=TEXT,
                                      placeholder_text_color=FAINT, border_color=BORDER,
                                      corner_radius=14, height=36, show="•")
        self.key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.key_entry.bind("<Return>", lambda e: self._save_key())
        ctk.CTkButton(self.key_row, text="Save", font=self.F(14, True), fg_color=CREAM,
                      text_color=INK, hover_color="#ddd6c8", corner_radius=14,
                      width=70, height=36, command=self._save_key).grid(row=0, column=1)
        self.chat = ctk.CTkScrollableFrame(v, fg_color=BG, corner_radius=0,
                                           scrollbar_button_color=DIVIDER,
                                           scrollbar_button_hover_color=BORDER)
        self.chat.grid(row=2, column=0, sticky="nsew", padx=32, pady=(8, 6))
        inp = ctk.CTkFrame(v, fg_color=INPUT_BG, corner_radius=22,
                           border_width=1, border_color=BORDER)
        inp.grid(row=3, column=0, sticky="ew", padx=102, pady=(0, 14))
        inp.grid_columnconfigure(0, weight=1)
        self.idea_entry = ctk.CTkEntry(inp, placeholder_text="Ask for ideas… e.g. name ideas for a habit tracker",
                                       font=self.F(15), fg_color="transparent", border_width=0,
                                       text_color=TEXT, placeholder_text_color=FAINT, height=42,
                                       state="disabled")
        self.idea_entry.grid(row=0, column=0, sticky="ew", padx=(18, 6), pady=8)
        self.idea_entry.bind("<Return>", lambda e: self._send_idea())
        self.idea_send = ctk.CTkButton(inp, text="Send", font=self.F(15, True), fg_color=CREAM,
                                       text_color=INK, hover_color="#ddd6c8", corner_radius=16,
                                       width=72, height=30, command=self._send_idea, state="disabled")
        self.idea_send.grid(row=0, column=1, padx=(0, 10), pady=8)
        v.grid_remove()

    def show_projects(self):
        self.view_ideas.grid_remove()
        self.nav_projects.configure(fg_color=CARD, text_color=TEXT, font=self.F(14, True))
        self.nav_ideas.configure(fg_color="transparent", text_color=MUTED, font=self.F(14))

    def show_ideas(self):
        self.view_ideas.grid()
        self.nav_ideas.configure(fg_color=CARD, text_color=TEXT, font=self.F(14, True))
        self.nav_projects.configure(fg_color="transparent", text_color=MUTED, font=self.F(14))
        if self._input_ready():
            if not self.chat.winfo_children():
                self._bubble("Hey, I'm Sharp. What are we brainstorming?", mine=False)
            self.idea_entry.focus_set()

    def set_sharp_mode(self, mode):
        self.sharp_mode = mode
        on = {"fg_color": CREAM, "text_color": INK, "font": self.F(14, True)}
        off = {"fg_color": "transparent", "text_color": MUTED, "font": self.F(14)}
        self.btn_instant.configure(**(on if mode == "instant" else off))
        self.btn_search.configure(**(on if mode == "search" else off))
        self.btn_local.configure(**(on if mode == "local" else off))
        self._refresh_ideas_bar()
        self._refresh_input_state()

    def _input_ready(self):
        return ((self.sharp_mode in ("instant", "search") and bool(load_api_key())) or
                (self.sharp_mode == "local" and self.brain.ready))

    def _refresh_ideas_bar(self):
        if self.sharp_mode in ("instant", "search"):
            self.brain_btn.grid_remove()
            self.key_row.pack(fill="x", padx=70, pady=(8, 0))
            if load_api_key():
                self.key_entry.configure(
                    placeholder_text="Key saved ✓ — paste a new key here to replace it")
                if not self.brain.loading and not self._generating:
                    if self.sharp_mode == "search":
                        self.brain_status.configure(text="Sharp Search — answers with web sources.")
                    else:
                        self.brain_status.configure(text="Instant Sharp via Gemini — ask anything.")
            else:
                self.key_entry.configure(
                    placeholder_text="Paste Gemini API key… (free at aistudio.google.com/apikey)")
                self.brain_status.configure(text="Paste a free Gemini API key below to wake instant Sharp.")
        else:
            self.key_row.pack_forget()
            self.brain_btn.grid()
            if self.brain.ready:
                self.brain_status.configure(text="Local mini model ready.")
            elif not self.brain.loading:
                self.brain_status.configure(text="Mini model not loaded (~270MB one-time download).")

    def _refresh_input_state(self):
        ok = self._input_ready()
        self.idea_entry.configure(state="normal" if ok else "disabled")
        if not self._generating:
            self.idea_send.configure(state="normal" if ok else "disabled")

    def _save_key(self):
        k = self.key_entry.get().strip()
        if not k:
            return
        save_api_key(k)
        self.key_entry.delete(0, "end")
        self._refresh_ideas_bar()
        self._refresh_input_state()
        if not self.chat.winfo_children():
            self._bubble("Key saved — I'm instant now. What are we brainstorming?", mine=False)

    def _toggle_brain(self):
        if self.brain.ready:
            self.brain.unload()
            self.brain_btn.configure(text="Load")
            self.brain_status.configure(text="Mini model unloaded. Load it again any time.")
            self.idea_entry.configure(state="disabled")
            self.idea_send.configure(state="disabled")
            return
        if self.brain.loading:
            return
        self.brain_btn.configure(state="disabled", text="…")
        self.brain_status.configure(text="Downloading + loading mini model (~270MB, one-time)…")
        threading.Thread(target=self._load_brain, daemon=True).start()

    def _load_brain(self):
        try:
            self.brain.load()
        except Exception as e:
            err = str(e)[:160]
            self.after(0, lambda: self._brain_failed(err))
            return
        self.after(0, self._brain_ready)

    def _brain_ready(self):
        self.brain_btn.configure(state="normal", text="Unload")
        if self.sharp_mode == "local":
            self.brain_status.configure(text="Sharp is ready — ask anything. Tiny CPU model: replies stream in gradually.")
            if not self.chat.winfo_children():
                self._bubble("Hey, I'm Sharp. What are we brainstorming?", mine=False)
        self._refresh_input_state()
        self.idea_entry.focus_set()

    def _brain_failed(self, err):
        self.brain_btn.configure(state="normal", text="Retry")
        self.brain_status.configure(text=f"Could not load model: {err}")

    def _bubble(self, text, mine):
        wrap = ctk.CTkFrame(self.chat, fg_color="transparent", corner_radius=0)
        wrap.pack(fill="x", padx=8, pady=4)
        b = ctk.CTkFrame(wrap, fg_color=INPUT_BG if mine else CARD, corner_radius=14,
                         border_width=1, border_color=BORDER if mine else DIVIDER)
        b.pack(side="right" if mine else "left", padx=4)
        lbl = ctk.CTkLabel(b, text=text, font=self.F(14), text_color=TEXT,
                           anchor="w", justify="left", wraplength=480)
        lbl.pack(padx=12, pady=8)
        self.chat._parent_canvas.yview_moveto(1.0)
        return lbl

    def _sources_bubble(self, sources):
        wrap = ctk.CTkFrame(self.chat, fg_color="transparent", corner_radius=0)
        wrap.pack(fill="x", padx=8, pady=(0, 4))
        b = ctk.CTkFrame(wrap, fg_color=CARD, corner_radius=14,
                         border_width=1, border_color=DIVIDER)
        b.pack(side="left", padx=4)
        ctk.CTkLabel(b, text="Sources:", font=self.F(13, True),
                     text_color=FAINT).pack(anchor="w", padx=12, pady=(8, 2))
        for title, uri in sources[:6]:
            t = title or uri
            if len(t) > 64:
                t = t[:61] + "..."
            ctk.CTkButton(b, text="↗ " + t, font=self.F(13), anchor="w",
                          fg_color="transparent", text_color=ACCENT, hover_color=INPUT_BG,
                          corner_radius=8, height=26,
                          command=lambda u=uri: webbrowser.open(u)).pack(
                fill="x", padx=6, pady=1)
        ctk.CTkFrame(b, fg_color="transparent", height=6).pack()
        self.chat._parent_canvas.yview_moveto(1.0)

    def _clear_ideas(self):
        for w in self.chat.winfo_children():
            w.destroy()
        self.idea_hist = []

    def _send_idea(self):
        if self._generating:
            return
        txt = self.idea_entry.get().strip()
        if not txt:
            return
        if self.sharp_mode in ("instant", "search"):
            if not load_api_key():
                self.brain_status.configure(text="Paste a free Gemini API key below first.")
                return
            want_search = self.sharp_mode == "search"
            self._gen_source = lambda want_search=want_search: self.api.stream_reply(
                self.idea_hist, search=want_search)
        else:
            if not self.brain.ready:
                self.brain_status.configure(text="Load the mini model first (Local mode).")
                return
            self._gen_source = lambda: self.brain.stream_reply(self.idea_hist)
        self.idea_entry.delete(0, "end")
        self._bubble(txt, mine=True)
        self.idea_hist.append({"role": "user", "content": txt})
        self._generating = True
        self.idea_send.configure(state="disabled")
        self._reply_label = self._bubble("…", mine=False)
        self._reply_text = ""
        self._gen_queue = queue.Queue()
        threading.Thread(target=self._generate, daemon=True).start()
        self.after(80, self._poll_gen)

    def _generate(self):
        try:
            for chunk in self._gen_source():
                self._gen_queue.put(chunk)
        except Exception as e:
            self._gen_queue.put(f"\n[error: {e}]")
        finally:
            self._gen_queue.put(None)

    def _poll_gen(self):
        try:
            while True:
                chunk = self._gen_queue.get_nowait()
                if chunk is None:
                    reply = self._reply_text.strip()
                    self._reply_label.configure(text=reply or "(no reply)")
                    self.idea_hist.append({"role": "assistant", "content": reply})
                    if self.sharp_mode == "search":
                        srcs = self.api.get_sources()
                        if srcs:
                            self._sources_bubble(srcs)
                    self._generating = False
                    self.idea_send.configure(state="normal")
                    return
                self._reply_text += chunk
                self._reply_label.configure(text=self._reply_text)
                self.chat._parent_canvas.yview_moveto(1.0)
        except queue.Empty:
            pass
        self.after(80, self._poll_gen)

    # ── filtering ──
    def _on_search(self):
        v = self.search.get()
        self.q = "" if v == "Search" else v
        self.refresh_all()

    # ── language dropdown: custom pill + popup (single unified piece) ──
    def _lang_button(self, master, var, options, on_pick=None, anchor="center"):
        b = ctk.CTkButton(master, text=f"{var.get()}  \u25be", font=self.F(14),
                          fg_color="transparent", text_color=MUTED, hover_color=INPUT_BG,
                          border_width=1, border_color=BORDER, corner_radius=15, height=30,
                          anchor=anchor)

        def _open():
            self._lang_menu(b, var, options,
                            lambda v: (b.configure(text=f"{v}  \u25be"),
                                       on_pick(v) if on_pick else None))

        b.configure(command=_open)
        return b

    def _lang_menu(self, btn, var, options, on_pick):
        import time as _t
        now = _t.time()
        pop = getattr(self, "_lang_pop", None)
        if pop is not None and pop.winfo_exists():
            pop.destroy()
            self._lang_pop = None
            self._lang_closed_at = now
            return
        if now - getattr(self, "_lang_closed_at", 0) < 0.35:
            return
        pop = ctk.CTkToplevel(btn.winfo_toplevel())
        self._lang_pop = pop
        pop.overrideredirect(True)
        pop.configure(fg_color=CARD)
        try:
            pop.attributes("-topmost", True)
        except Exception:
            pass
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height() + 6
        w = max(btn.winfo_width(), 140)
        pop.geometry(f"{w}x{len(options) * 30 + 2}+{x}+{y}")
        box = ctk.CTkFrame(pop, fg_color=CARD, corner_radius=0,
                           border_width=1, border_color=BORDER)
        box.pack(fill="both", expand=True)
        for v in options:
            cur = (v == var.get())
            ctk.CTkButton(box, text="  " + v, font=self.F(14), anchor="w",
                          fg_color=INPUT_BG if cur else "transparent",
                          text_color=TEXT if cur else MUTED,
                          hover_color=INPUT_BG, corner_radius=0, height=30,
                          command=lambda v=v: self._pick_lang(var, on_pick, v)).pack(fill="x")
        pop.bind("<FocusOut>", lambda e: self._close_lang_menu())
        pop.bind("<Escape>", lambda e: self._close_lang_menu())
        try:
            pop.focus_force()
        except Exception:
            pass

    def _pick_lang(self, var, on_pick, value):
        var.set(value)
        self._close_lang_menu()
        on_pick(value)

    def _close_lang_menu(self):
        import time as _t
        pop = getattr(self, "_lang_pop", None)
        if pop is not None and pop.winfo_exists():
            pop.destroy()
        self._lang_pop = None
        self._lang_closed_at = _t.time()

    def _apply_lang(self, value):
        self.lang = value
        self.refresh_all()

    def visible(self):
        q = self.q.lower().strip()
        out = []
        for i, p in enumerate(self.projects):
            if self.lang != "All" and p.get("language") != self.lang:
                continue
            if q and q not in (p.get("label", "") + " " + p.get("description", "")).lower():
                continue
            out.append((i, p))
        return out

    # ── refresh ──
    def refresh_all(self):
        items = self.visible()
        ok = sum(1 for p in self.projects if p.get("last_status") == "ok")
        fail = sum(1 for p in self.projects if p.get("last_status") == "fail")
        self.count.configure(text=f"{len(items)} of {len(self.projects)} projects")
        self.side_stats.configure(text=f"{len(self.projects)} projects   \u00b7   {ok} built   \u00b7   {fail} failed")
        for w in self.side_list.winfo_children():
            w.destroy()
        for i, p in enumerate(self.projects[:60]):
            sel = (i == self.selected)
            ctk.CTkButton(self.side_list, text=(p.get("label") or "Untitled")[:26],
                          font=self.F(15), anchor="w",
                          fg_color=CARD if sel else "transparent",
                          text_color=TEXT if sel else MUTED,
                          hover_color=CARD, corner_radius=13, height=32,
                          command=lambda i=i: self._select(i)).pack(fill="x", pady=2, padx=2)
        for w in self.cards.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self.cards, text="No projects match. Name one above and press Enter.",
                         font=self.F(15), text_color=FAINT).pack(pady=32)
            return
        for idx, p in items:
            self._card(idx, p)

    def _select(self, i):
        self.selected = i
        self.refresh_all()

    # ── project card ──
    def _card(self, idx, p):
        c = ctk.CTkFrame(self.cards, fg_color=CARD, corner_radius=18,
                         border_width=1, border_color=DIVIDER)
        c.pack(fill="x", pady=6, padx=4)
        c.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(c, fg_color="transparent", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 0))
        ctk.CTkLabel(top, text=p.get("label", "Untitled"), font=self.F(19, True),
                     text_color=TEXT, anchor="w").pack(side="left")
        st = p.get("last_status", "idle")
        if st == "ok" and p.get("last_build"):
            s_txt, s_col = p["last_build"], MUTED
        elif st == "fail":
            s_txt, s_col = "Build failed", "#d98a7e"
        elif st == "busy":
            s_txt, s_col = "Working\u2026", MUTED
        else:
            s_txt, s_col = "Not built yet", FAINT
        ctk.CTkLabel(top, text=s_txt, font=self.F(12), text_color=s_col).pack(side="right")
        desc = (p.get("description") or "").strip()
        if desc:
            ctk.CTkLabel(c, text=desc, font=self.F(14), text_color=MUTED,
                         anchor="w", justify="left", wraplength=620).grid(
                row=1, column=0, sticky="ew", padx=18, pady=(2, 0))
        meta = ctk.CTkFrame(c, fg_color="transparent", corner_radius=0)
        meta.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        ctk.CTkLabel(meta, text="  " + p.get("language", "Other") + "  ",
                     font=self.F(13), fg_color=INPUT_BG, text_color=MUTED,
                     corner_radius=10).pack(side="left")
        ctk.CTkLabel(meta, text="   " + (p.get("path") or ""), font=(MONO, 10),
                     text_color=FAINT).pack(side="left")
        if p.get("build"):
            ctk.CTkLabel(meta, text="   \u00b7   " + p["build"][:64], font=(MONO, 10),
                         text_color=FAINT).pack(side="left")
        acts = ctk.CTkFrame(c, fg_color="transparent", corner_radius=0)
        acts.grid(row=3, column=0, sticky="ew", padx=18, pady=(10, 14))
        self._pill(acts, "Compile", cream=True, cmd=lambda: self.compile_project(idx))
        self._pill(acts, "Run", cmd=lambda: self.run_project(idx))
        self._pill(acts, "Open", cmd=lambda: self.open_folder(idx))
        self._pill(acts, "Edit", cmd=lambda: self.open_editor(idx))
        self._pill(acts, "Delete", cmd=lambda: self.delete_project(idx))

    def _pill(self, parent, text, cmd, cream=False):
        b = ctk.CTkButton(parent, text=text, command=cmd, font=self.F(14, cream),
                          corner_radius=15, height=30, width=76,
                          fg_color=CREAM if cream else "transparent",
                          text_color=INK if cream else MUTED,
                          hover_color="#ddd6c8" if cream else INPUT_BG,
                          border_width=0 if cream else 1, border_color=BORDER)
        b.pack(side="left", padx=(0, 8))
        return b

    # ── quick add ──
    def _quick_add(self, _e):
        raw = self.quick.get().strip()
        if not raw:
            return "break"
        label, desc, folder = raw, "", ""
        for sep in ["\u2014", "—", " - ", ": "]:
            if sep in raw:
                label, desc = [s.strip() for s in raw.split(sep, 1)]
                break
        if "@" in desc:
            desc, folder = [s.strip() for s in desc.rsplit("@", 1)]
        elif "@" in label and not desc:
            label, folder = [s.strip() for s in label.rsplit("@", 1)]
        self.open_editor(prefill={"label": label[:80], "description": desc[:300],
                                  "path": folder, "language": "Python", "build": "", "run": ""})
        self.quick.delete(0, "end")
        return "break"

    # ── editor ──
    def open_editor(self, idx=None, prefill=None):
        is_new = idx is None
        base = {"label": "", "description": "", "language": "Python",
                "path": "", "build": "", "run": ""}
        if not is_new:
            base.update(self.projects[idx])
        if prefill:
            for k, v in prefill.items():
                if v:
                    base[k] = v
            if not base.get("build"):
                b, r_ = DEFAULT_COMMANDS.get(base.get("language", "Python"), ("", ""))
                base["build"], base["run"] = b, r_
        win = ctk.CTkToplevel(self)
        win.title("New project" if is_new else "Edit project")
        win.geometry("500x600")
        win.configure(fg_color=SIDEBAR)
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="New project" if is_new else "Edit project",
                     font=self.F(23, True), text_color=TEXT).pack(pady=(20, 0), padx=26, anchor="w")
        ctk.CTkLabel(win, text="A label, a short description, and how to build it.",
                     font=self.F(14), text_color=MUTED).pack(padx=26, anchor="w", pady=(0, 6))
        frm = ctk.CTkScrollableFrame(win, fg_color="transparent", corner_radius=0)
        frm.pack(fill="both", expand=True, padx=18, pady=4)
        widgets = {}

        def field(key, title, default="", multi=False):
            ctk.CTkLabel(frm, text=title, font=self.F(14, True), text_color=FAINT).pack(
                anchor="w", padx=8, pady=(10, 4))
            if multi:
                t = ctk.CTkTextbox(frm, height=60, corner_radius=14, font=self.F(15),
                                   fg_color=INPUT_BG, text_color=TEXT, border_width=1,
                                   border_color=BORDER, wrap="word")
                t.pack(fill="x", padx=4)
                t.insert("1.0", default)
                widgets[key] = t
            else:
                e = ctk.CTkEntry(frm, font=self.F(15), fg_color=INPUT_BG, text_color=TEXT,
                                 border_color=BORDER, corner_radius=13, height=36)
                e.pack(fill="x", padx=4)
                e.insert(0, default)
                widgets[key] = e

        field("label", "Label", base.get("label", ""))
        field("description", "Description", base.get("description", ""), multi=True)
        ctk.CTkLabel(frm, text="Language", font=self.F(14, True), text_color=FAINT).pack(
            anchor="w", padx=8, pady=(10, 4))
        lv = ctk.StringVar(value=base.get("language", "Python"))
        edit_lang_btn = self._lang_button(frm, lv, LANGS, anchor="w")
        edit_lang_btn.configure(height=36, corner_radius=13)
        edit_lang_btn.pack(fill="x", padx=4)
        ctk.CTkLabel(frm, text="Folder", font=self.F(14, True), text_color=FAINT).pack(
            anchor="w", padx=8, pady=(10, 4))
        prow = ctk.CTkFrame(frm, fg_color="transparent", corner_radius=0)
        prow.pack(fill="x", padx=4)
        prow.grid_columnconfigure(0, weight=1)
        pe = ctk.CTkEntry(prow, font=self.F(15), fg_color=INPUT_BG, text_color=TEXT,
                          border_color=BORDER, corner_radius=13, height=36)
        pe.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        pe.insert(0, base.get("path", ""))
        widgets["path"] = pe
        ctk.CTkButton(prow, text="Browse", font=self.F(14), fg_color=INPUT_BG,
                      text_color=TEXT, hover_color=CARD, border_width=1,
                      border_color=BORDER, corner_radius=13, height=36, width=88,
                      command=lambda: self._browse(pe)).grid(row=0, column=1)
        field("build", "Build command", base.get("build", ""))
        field("run", "Run command", base.get("run", ""))

        def on_save():
            def val(k):
                w = widgets[k]
                return w.get("1.0", "end").strip() if isinstance(w, ctk.CTkTextbox) else w.get().strip()
            label = val("label")
            if not label:
                messagebox.showwarning("QuickSharp", "Give the project a label.")
                return
            rec = {"label": label, "description": val("description"), "language": lv.get(),
                   "path": val("path") or ".", "build": val("build"), "run": val("run"),
                   "last_status": base.get("last_status", "idle"),
                   "last_build": base.get("last_build", "")}
            if is_new:
                self.projects.append(rec)
                self.selected = len(self.projects) - 1
                self.log(f"Added '{label}'.")
            else:
                self.projects[idx] = rec
                self.log(f"Updated '{label}'.")
            save_data(self.projects)
            self.refresh_all()
            win.destroy()

        ctk.CTkButton(win, text="Save project", command=on_save, font=self.F(16, True),
                      fg_color=CREAM, text_color=INK, hover_color="#ddd6c8",
                      corner_radius=18, height=42).pack(fill="x", padx=26, pady=16)

    def _browse(self, entry):
        d = filedialog.askdirectory()
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)

    # ── actions ──
    def open_folder(self, idx):
        p = self.projects[idx].get("path", "")
        if p and os.path.isdir(p):
            try:
                os.startfile(p)
            except Exception:
                webbrowser.open(p)
        else:
            messagebox.showwarning("QuickSharp", f"Folder not found:\n{p}")

    def delete_project(self, idx):
        if messagebox.askyesno("QuickSharp", f"Delete '{self.projects[idx].get('label')}'?"):
            del self.projects[idx]
            save_data(self.projects)
            self.refresh_all()

    def compile_project(self, idx):
        cmd = (self.projects[idx].get("build") or "").strip()
        if not cmd:
            messagebox.showinfo("QuickSharp", "No build command set. Use Edit to add one.")
            return
        self._run(idx, cmd, "compile")

    def run_project(self, idx):
        cmd = (self.projects[idx].get("run") or "").strip()
        if not cmd:
            messagebox.showinfo("QuickSharp", "No run command set. Use Edit to add one.")
            return
        self._run(idx, cmd, "run")

    def _run(self, idx, cmd, kind):
        cwd = self.projects[idx].get("path") or "."
        if not os.path.isdir(cwd):
            messagebox.showwarning("QuickSharp", f"Folder not found:\n{cwd}")
            return
        self.projects[idx]["last_status"] = "busy"
        self.selected = idx
        self.refresh_all()
        self.out_meta.configure(text=f"{kind} \u00b7 {self.projects[idx]['label']}")
        self.log(f"$ {cmd}")
        threading.Thread(target=self._exec, args=(idx, cmd, cwd, kind), daemon=True).start()

    def _exec(self, idx, cmd, cwd, kind):
        t0 = time.time()
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in proc.stdout:
                self.log(line.rstrip("\n"))
            proc.wait()
            dt = time.time() - t0
            if proc.returncode == 0:
                self.projects[idx]["last_status"] = "ok"
                self.projects[idx]["last_build"] = f"Built \u00b7 {datetime.now():%b %d, %H:%M} \u00b7 {dt:.1f}s"
                self.log(f"Done in {dt:.1f}s.")
            else:
                self.projects[idx]["last_status"] = "fail"
                self.projects[idx]["last_build"] = ""
                self.log(f"Failed with exit {proc.returncode}.")
        except Exception as e:
            self.projects[idx]["last_status"] = "fail"
            self.log(f"Error: {e}")
        save_data(self.projects)
        self.after(0, self.refresh_all)

    # ── log ──
    def log(self, msg):
        def _do():
            self.console.configure(state="normal")
            self.console.insert("end", msg + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        try:
            self.after(0, _do)
        except Exception:
            pass

    def _clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.out_meta.configure(text="")


def main():
    load_font()
    QuickSharp().mainloop()


if __name__ == "__main__":
    main()
