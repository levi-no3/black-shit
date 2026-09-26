"""ju6 sharp desktop app v2 (word model, speaks). Run: python app.py"""
import threading
from pathlib import Path
import tkinter as tk
from tkinter import scrolledtext
import torch
from model import Ju6Sharp, Ju6Config
from tokenizer_word import WordTok
from brain import hangout
from polish import polish, cut_tails
BASE = Path(__file__).parent

class App:
    def __init__(self, root):
        root.title("ju6 sharp")
        root.geometry("640x520")
        self.hist = ""
        self.model = None
        self.tk = None
        self.info = tk.StringVar(value="loading model...")
        top = tk.Frame(root); top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="ju6 sharp", font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(top, textvariable=self.info, font=("Segoe UI", 9)).pack(side="left", padx=10)
        self.debate = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Debate mode", variable=self.debate).pack(side="right")
        self.box = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 10), state="disabled")
        self.box.pack(fill="both", expand=True, padx=8, pady=4)
        bottom = tk.Frame(root); bottom.pack(fill="x", padx=8, pady=6)
        self.entry = tk.Entry(bottom, font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self.send())
        self.send_btn = tk.Button(bottom, text="Send", command=self.send, width=10)
        self.send_btn.pack(side="right")
        ctrl = tk.Frame(root); ctrl.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(ctrl, text="Temp").pack(side="left")
        self.temp = tk.Scale(ctrl, from_=0.1, to=1.2, resolution=0.1, orient="horizontal", length=140)
        self.temp.set(0.5); self.temp.pack(side="left", padx=6)
        tk.Button(ctrl, text="Clear", command=self.clear).pack(side="right")
        threading.Thread(target=self.load_model, daemon=True).start()

    def log(self, who, msg):
        self.box.config(state="normal")
        self.box.insert("end", f"{who}: {msg}\n\n"); self.box.see("end")
        self.box.config(state="disabled")

    def load_model(self):
        try:
            # prefer v2 word model
            if (BASE/"ju6_sharp_word.pt").exists():
                ck = torch.load(BASE/"ju6_sharp_word.pt", map_location="cpu")
                cfg = Ju6Config(**ck["cfg"])
                m = Ju6Sharp(cfg); m.load_state_dict(ck["state"]); m.eval()
                tkz = WordTok.load(BASE/"vocab.json")
                self.model, self.tk = m, tkz
                self.mode = "word"
                self.info.set(f"ready v2 ({m.count_params()/1e6:.2f}M, CPU)")
                self.log("Ju6", "Hey, I'm Ju6 Sharp v2. I speak now. Talk, ask for writing help, or tick Debate mode.")
            else:
                self.info.set("no model found")
                self.log("Ju6", "Missing ju6_sharp_word.pt. Run train_word.py first.")
        except Exception as e:
            self.info.set("load failed")
            self.log("Ju6", f"Load error: {e}")

    def clear(self):
        self.hist = ""
        self.box.config(state="normal"); self.box.delete("1.0","end"); self.box.config(state="disabled")

    def _log(self, u, raw, r):
        try:
            with open(BASE / "ju6_log.txt", "a", encoding="utf-8") as f:
                f.write(f"YOU: {u}\nRAW: {raw}\nJU6: {r}\n---\n")
        except Exception:
            pass

    def send(self):
        u = self.entry.get().strip()
        if not u or self.model is None: return
        self.entry.delete(0,"end"); self.log("You", u)
        self.send_btn.config(state="disabled")
        threading.Thread(target=self.reply, args=(u,), daemon=True).start()

    def reply(self, u):
        try:
            hb = hangout(u, debate_mode=bool(self.debate.get()))
            if hb not in (None, "NEURAL", "NEURAL_DEBATE"):
                hb = polish(hb)
                self.hist += f"User: {u}\nJu6: {hb}\n"
                self.log("Ju6", hb)
                self._log(u, "(brain)", hb)
                return
            force_debate = (hb == "NEURAL_DEBATE")
            # honest fallback: mostly-unknown words -> echo, don't hallucinate
            raw_ids = self.tk.encode_raw(u)
            unk_ratio = sum(1 for i in raw_ids if i == 3) / max(1, len(raw_ids))
            if unk_ratio > 0.35:
                self.hist += f"User: {u}\nJu6:"
                r = (f"Hmm, not sure I followed that bit about {u.strip()[:60]}. "
                     f"Say a little more? I do chat, debates, and writing help.")
                self.hist += " " + r + "\n"
                self.log("Ju6", r)
                self._log(u, "(unk-fallback)", r)
                return
            # keep last 2 clean turns only, exactly like training blocks
            turns = [t for t in self.hist.split("\n") if t.startswith(("User:", "Ju6:"))][-4:]
            turns.append(f"User: {u}")
            prompt = "\n".join(turns) + "\nJu6:"
            if force_debate or bool(self.debate.get()):
                prompt = ("Debate rules: define terms, give one claim with a reason, "
                          "answer fairly, close by weighing impact.\n" + prompt)
            seq = self.tk.encode_raw(prompt)[-self.model.cfg.max_seq:]
            ids = torch.tensor([seq], dtype=torch.long)
            topics = ["homework","phone","cat","dog","uniform","social media","pizza",
                      "book","movie","college","apolog","sorry","thank","name","how are you"]
            want = next((t for t in topics if t in u.lower()), None)
            r = "..."
            raw_out = ""
            with torch.no_grad():
                for attempt in (float(self.temp.get()), 0.5, 0.3):
                    out = self.model.generate(ids, max_new=80, temperature=attempt, top_k=30,
                                              suppress_ids=(0, 1, 3),
                                              repetition_penalty=1.15)
                    cand = self.tk.decode(out[0].tolist()[len(seq):])
                    if not raw_out:
                        raw_out = cand[:200]
                    if "user:" in cand: cand = cand.split("user:")[0]
                    cand = cand.replace("ju6:", "").replace("ju 6:", "").strip()
                    cand = cand[:600].strip()
                    if not cand:
                        continue
                    if want and want not in cand.lower() and attempt != 0.3:
                        continue
                    r = cand
                    break
            self.hist += f"User: {u}\nJu6: {r}\n"
            if not force_debate:
                import re as _re
                _stop = {"about", "there", "think", "would", "could", "please", "hello",
                         "just", "want", "like", "have", "what", "when", "your", "with",
                         "that", "this", "them", "then", "than", "from", "talk", "chat"}
                words = [w for w in _re.findall(r"[a-z']{4,}", u.lower()) if w not in _stop]
                key = max(words, key=len) if words else None
                if r.strip(" .") in ("...", "") or (key and key not in r.lower()):
                    r = (f"{key.capitalize() if key else 'That'}, huh? Say more about "
                         f"{key if key else 'that'} — what is your take, and what got you into it?")
                    self.hist += f"(echo-fix) {r}\n"
            r = polish(r)
            if not force_debate and not bool(self.debate.get()):
                r = polish(cut_tails(r))
            self.log("Ju6", r)
            self._log(u, raw_out, r)
        except Exception as e:
            self.log("Ju6", f"error: {e}")
        finally:
            self.send_btn.config(state="normal")

if __name__ == "__main__":
    r = tk.Tk(); App(r); r.mainloop()
