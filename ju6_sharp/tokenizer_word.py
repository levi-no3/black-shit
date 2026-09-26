"""Word-level tokenizer, custom built. No HF, no Llama."""
import json, re
from pathlib import Path
PAD, BOS, EOS, UNK = 0, 1, 2, 3

def tok_words(s):
    return re.findall(r"[a-z']+|[0-9]+|[^\sa-z0-9]", s.lower())

class WordTok:
    def __init__(self, stoi, itos):
        self.stoi, self.itos = stoi, itos
    @classmethod
    def build(cls, text, cap=8000, min_freq=2):
        from collections import Counter
        c = Counter(tok_words(text))
        vocab = ["<pad>","<bos>","<eos>","<unk>"] + [w for w,_ in c.most_common(cap-4) if c[w] >= min_freq]
        stoi = {w:i for i,w in enumerate(vocab)}
        return cls(stoi, vocab)
    def encode(self, s):
        return [BOS] + [self.stoi.get(w, UNK) for w in tok_words(s)] + [EOS]
    def encode_raw(self, s):
        return [self.stoi.get(w, UNK) for w in tok_words(s)]
    def decode(self, ids):
        ws = [self.itos[i] if 0 <= i < len(self.itos) else "<unk>" for i in ids if i not in (PAD,BOS,EOS)]
        t = " ".join(ws)
        import re as _re
        t = _re.sub(r"\s+([.,!?;:'\)\]])", r"\1", t)
        t = _re.sub(r"([(\[])\s+", r"\1", t)
        return t
    def __len__(self): return len(self.itos)
    def save(self, p):
        Path(p).write_text(json.dumps({"itos": self.itos}, ensure_ascii=False))
    @classmethod
    def load(cls, p):
        itos = json.loads(Path(p).read_text())["itos"]
        return cls({w:i for i,w in enumerate(itos)}, itos)
