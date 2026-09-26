"""Encode gpt_corpus.txt with custom BPE -> train.pt / val.pt"""
import torch
from pathlib import Path
from bpe import BPE
BASE = Path(__file__).parent

bpe = BPE.load(BASE / "bpe.json")
EOS = bpe.specials["<eos>"]
text = (BASE / "gpt_corpus.txt").read_text(encoding="utf-8")
blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
print(f"blocks={len(blocks)}")
cache, ids, n = {}, [], 0
for b in blocks:
    ids.extend(bpe.encode(b, cache))
    ids.append(EOS)
    n += 1
    if n % 10000 == 0:
        print(f"  {n}/{len(blocks)} cache={len(cache)}", flush=True)
data = torch.tensor(ids, dtype=torch.int32)
print(f"tokens={len(data)/1e6:.2f}M")
cut = int(len(data) * 0.98)
torch.save({"train": data[:cut], "val": data[cut:]}, BASE / "gpt_data.pt")
print("saved gpt_data.pt")
