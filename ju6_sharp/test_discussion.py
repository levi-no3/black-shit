"""Full discussion test: neural GPT only, history-fed like the app."""
import torch
from pathlib import Path
from model import Ju6Sharp, Ju6Config
from bpe import BPE

BASE = Path(__file__).parent
bpe = BPE.load(BASE / "bpe.json")
ck = torch.load(BASE / "ju6_gpt.pt", map_location="cpu", weights_only=True)
m = Ju6Sharp(Ju6Config(**ck["cfg"]))
m.load_state_dict(ck["state"])
m.eval()
EOS = bpe.specials["<eos>"]

hist = ""

def send(u, temp=0.7):
    global hist
    hist += f"User: {u}\nJu6:"
    seq = bpe.encode(hist)[-m.cfg.max_seq:]
    with torch.no_grad():
        out = m.generate(torch.tensor([seq]), max_new=70, temperature=temp,
                         top_k=50, repetition_penalty=1.1, eos_ids=(EOS,))
    txt = bpe.decode(out[0].tolist()[len(seq):])
    if "User:" in txt:
        txt = txt.split("User:")[0]
    r = txt.strip()[:400]
    hist += f" {r}\n"
    return r

script = [
    "hey",
    "i am good, how was your day",
    "i like football",
    "lions are better than tigers",
    "why do you think that",
    "let us debate homework",
    "but homework builds discipline",
]
for u in script:
    print(f"YOU: {u}")
    print(f"JU6: {send(u)}")
    print()
