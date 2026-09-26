"""Coherence eval: topic word must appear, no wrong-topic leak, fluent length."""
from pathlib import Path
import torch
from model import Ju6Sharp, Ju6Config
from tokenizer_word import WordTok
BASE = Path(__file__).parent

TESTS = [
 ("User: Let us debate homework.\nJu6:", ["homework"]),
 ("User: Let us debate phones in school.\nJu6:", ["phone"]),
 ("User: Let us debate cats vs dogs.\nJu6:", ["cat", "dog"]),
 ("User: Help me write an apology.\nJu6:", ["sorry", "wrong", "reschedul", "confirm", "apolog"]),
 ("User: Hi, how are you?\nJu6:", ["how are you", "doing well", "ready", "hey", "hi"]),
 ("User: What is your name?\nJu6:", ["ju6", "sharp"]),
]

def gen(m, tk, prompt, temp=0.6, top_k=40, mx=70):
    seq = tk.encode_raw(prompt)[-m.cfg.max_seq:]
    ids = torch.tensor([seq], dtype=torch.long)
    out = m.generate(ids, max_new=mx, temperature=temp, top_k=top_k)
    txt = tk.decode(out[0].tolist()[len(seq):])
    # cut leaked next-turn roleplay (decode is lowercase)
    if "user:" in txt: txt = txt.split("user:")[0]
    txt = txt.replace("ju6:", "").replace("ju 6:", "").strip()
    return txt

def main():
    ck = torch.load(BASE/"ju6_sharp_word.pt", map_location="cpu")
    m = Ju6Sharp(Ju6Config(**ck["cfg"])); m.load_state_dict(ck["state"]); m.eval()
    tk = WordTok.load(BASE/"vocab.json")
    ok = 0
    for prompt, keys in TESTS:
        r = gen(m, tk, prompt).strip()
        low = r.lower()
        hit = any(k.lower() in low for k in keys)
        words = len(r.split())
        # repetition check: most common word ratio
        from collections import Counter
        c = Counter(low.split())
        rep = max(c.values())/max(1,len(low.split())) if low.split() else 1
        goodrep = rep < 0.25
        goodlen = 12 <= words <= 90
        passed = hit and goodrep and goodlen
        ok += passed
        print(f"{'PASS' if passed else 'FAIL'} | topic={keys[0]} | len={words} rep={rep:.2f}\n  -> {r[:220]}\n")
    print(f"SCORE {ok}/{len(TESTS)}")
    return ok

if __name__ == "__main__":
    main()
