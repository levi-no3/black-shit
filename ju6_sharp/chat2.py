"""Chat with ju6 sharp v2 (word model). Usage: python chat2.py --prompt "User: hi" """
import argparse
from pathlib import Path
import torch
from model import Ju6Sharp, Ju6Config
from tokenizer_word import WordTok
BASE = Path(__file__).parent

def load():
    ck = torch.load(BASE / "ju6_sharp_word.pt", map_location="cpu")
    cfg = Ju6Config(**ck["cfg"])
    m = Ju6Sharp(cfg)
    m.load_state_dict(ck["state"]); m.eval()
    tk = WordTok.load(BASE / "vocab.json")
    return m, tk

def gen(m, tk, prompt, max_new=80, temp=0.7, top_k=50):
    seq = tk.encode_raw(prompt)[-m.cfg.max_seq:]
    ids = torch.tensor([seq], dtype=torch.long)
    out = m.generate(ids, max_new=max_new, temperature=temp, top_k=30,
                       suppress_ids=(0, 1, 3), repetition_penalty=1.15)
    txt = tk.decode(out[0].tolist()[len(seq):])
    if "user:" in txt: txt = txt.split("user:")[0]
    txt = txt.replace("ju6:", "").replace("ju 6:", "").strip()
    try:
        from polish import polish, cut_tails
        return polish(cut_tails(txt))
    except Exception:
        return txt

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", type=str, default="User: Hi, how are you?\nJu6:")
    ap.add_argument("--temp", type=float, default=0.7)
    a = ap.parse_args()
    m, tk = load()
    print(gen(m, tk, a.prompt, temp=a.temp))
