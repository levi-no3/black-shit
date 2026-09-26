"""Byte-level BPE from scratch, GPT-style. No libs, no UNK ever, keeps case."""
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
N_MERGES = 4000
WORD_RE = re.compile(r"\S+|\s+")


def words_of(text):
    return WORD_RE.findall(text)


class BPE:
    def __init__(self, merges, specials):
        self.merges = merges  # list[(bytes,bytes)]
        self.rank = {p: i for i, p in enumerate(merges)}
        self.tok = {bytes([i]): i for i in range(256)}
        for i, (a, b) in enumerate(merges):
            self.tok[a + b] = 256 + i
        self.specials = specials  # {name: id}
        base = 256 + len(merges)
        self.vocab_size = base + len(specials)

    def _encode_word(self, wbytes, cache):
        if wbytes in cache:
            return cache[wbytes]
        parts = [bytes([b]) for b in wbytes]
        while len(parts) > 1:
            best, bi = None, None
            for i in range(len(parts) - 1):
                r = self.rank.get((parts[i], parts[i + 1]), 1 << 30)
                if best is None or r < best:
                    best, bi = r, i
            if best == 1 << 30:
                break
            parts = parts[:bi] + [parts[bi] + parts[bi + 1]] + parts[bi + 2:]
        ids = []
        for p in parts:
            if p in self.tok:
                ids.append(self.tok[p])
            else:  # unseen combo: fall back to raw bytes (never UNK)
                ids.extend(p)
        cache[wbytes] = ids
        return ids

    def _tok_id(self, p):
        try:
            return self.tok[p]
        except KeyError:
            # unseen combo (shouldn't happen): fall back to bytes
            return -1

    def encode(self, text, cache=None):
        cache = {} if cache is None else cache
        ids = []
        for w in words_of(text):
            b = w.encode("utf-8", errors="ignore")
            if not b:
                continue
            ids.extend(self._encode_word(b, cache))
        return ids

    def decode(self, ids):
        inv = {v: k for k, v in self.specials.items()}
        out = bytearray()
        for i in ids:
            if i in inv:
                continue
            if i < 256:
                out += bytes([i])
            else:
                a, b = self.merges[i - 256]
                out += a + b
        return out.decode("utf-8", errors="replace")

    def save(self, path):
        path = Path(path)
        path.write_text(json.dumps({
            "merges": [[a.decode("latin1"), b.decode("latin1")] for a, b in self.merges],
            "specials": self.specials,
        }))

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text())
        merges = [(a.encode("latin1"), b.encode("latin1")) for a, b in d["merges"]]
        return cls(merges, d["specials"])


def train_bpe(text, n_merges=N_MERGES):
    freq = Counter()
    for w in words_of(text):
        b = w.encode("utf-8", errors="ignore")
        if b and not w.isspace():
            freq[tuple(bytes([x]) for x in b)] += 1
    print(f"[bpe] unique words={len(freq)}")
    vocab_words = {w: list(w) for w in freq}
    merges = []
    for m in range(n_merges):
        pairs = Counter()
        for w, c in freq.items():
            parts = vocab_words[w]
            for i in range(len(parts) - 1):
                pairs[(parts[i], parts[i + 1])] += c
        if not pairs:
            break
        best = max(pairs, key=pairs.get)
        merges.append(best)
        a, b = best
        for w in list(freq):
            parts = vocab_words[w]
            new, i = [], 0
            while i < len(parts):
                if i < len(parts) - 1 and parts[i] == a and parts[i + 1] == b:
                    new.append(a + b)
                    i += 2
                else:
                    new.append(parts[i])
                    i += 1
            vocab_words[w] = new
        if (m + 1) % 1000 == 0:
            print(f"[bpe] merge {m+1}/{n_merges}", flush=True)
    base = 256 + len(merges)
    specials = {"<pad>": base, "<bos>": base + 1, "<eos>": base + 2}
    return BPE(merges, specials)


if __name__ == "__main__":
    import sys
    corpus = (BASE / "gpt_corpus.txt").read_text(encoding="utf-8")
    sample = corpus[:3_000_000]
    print(f"[bpe] training on {len(sample)/1e6:.1f}MB sample")
    bpe = train_bpe(sample)
    bpe.save(BASE / "bpe.json")
    print(f"[bpe] vocab={bpe.vocab_size} saved")
    # quick check
    t = "User: Hey, how are you?\nJu6: I'm Ju6 Sharp!"
    ids = bpe.encode(t)
    print(ids[:20], "->", repr(bpe.decode(ids)))
