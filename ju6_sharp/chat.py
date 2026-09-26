"""Chat with ju6 sharp. Usage: python chat.py --prompt "User: hi\nJu6:" --debate"""
import argparse
from pathlib import Path
import torch
from model import Ju6Sharp, Ju6Config
import tokenizer as tk

BASE = Path(__file__).parent

def load():
    ck = torch.load(BASE / "ju6_sharp.pt", map_location="cpu")
    cfg = Ju6Config(**ck["cfg"])
    m = Ju6Sharp(cfg)
    m.load_state_dict(ck["state"])
    m.eval()
    return m

def gen(m, prompt, max_new=120, temp=0.8, top_k=40):
    ids = torch.tensor([tk.encode_noboseos(prompt)], dtype=torch.long)
    out = m.generate(ids, max_new=max_new, temperature=temp, top_k=top_k)
    txt = tk.decode(out[0].tolist())
    return txt[len(prompt):] if txt.startswith(prompt) else txt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", type=str, default="User: Hey, let's debate.\nJu6:")
    ap.add_argument("--debate", action="store_true", help="prepend debate system style")
    ap.add_argument("--temp", type=float, default=0.8)
    args = ap.parse_args()
    m = load()
    p = args.prompt
    if args.debate:
        p = ("Debate rules: define terms, give one claim with a reason, "
             "answer the other side fairly, then close by weighing impact.\n" + p)
    print(gen(m, p, temp=args.temp))
    # interactive if no prompt override? simple loop
    if args.prompt == "User: Hey, let's debate.\nJu6:":
        print("\n[type to chat, blank to quit]")
        hist = ""
        while True:
            try:
                u = input("You: ").strip()
            except EOFError:
                break
            if not u:
                break
            hist += f"User: {u}\nJu6:"
            r = gen(m, hist[-600:], temp=args.temp)
            # cut at next User:
            if "User:" in r:
                r = r.split("User:")[0]
            print("Ju6:" + r.strip()[:600])
            hist += r.strip()[:600] + "\n"

if __name__ == "__main__":
    main()
