"""Build GPT-style corpus: real dialogue (PersonaChat + EmpatheticDialogues) + our debates."""
import csv
import random
from pathlib import Path
random.seed(5)
BASE = Path(__file__).parent
DATA = BASE / "data"

def clean(t):
    t = t.replace("_comma_", ",").replace("  ", " ").strip()
    return t

def personachat(path, max_chars=14_000_000):
    blocks, cur, chars = [], [], 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or " " not in line:
                continue
            num, _, rest = line.partition(" ")
            if not num.isdigit():
                continue
            if num == "1":
                if len(cur) >= 4:
                    blocks.append("\n".join(cur))
                    chars += sum(len(x) for x in cur)
                cur = []
                continue
            if "your persona:" in rest:
                continue
            fields = rest.split("\t")
            if len(fields) < 2:
                continue
            a, b = clean(fields[0]), clean(fields[1])
            if not a or not b or len(a) > 400 or len(b) > 400:
                continue
            who = "User" if len(cur) % 2 == 0 else "Ju6"
            cur.append(f"{who}: {a}")
            cur.append(f"{'Ju6' if who == 'User' else 'User'}: {b}")
            if chars > max_chars:
                break
    return blocks

def empathetic(path, max_chars=10_000_000):
    convos, chars = {}, 0
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            try:
                convos.setdefault(row["conv_id"], []).append(
                    (int(row["utterance_idx"]), clean(row["utterance"])))
            except (KeyError, ValueError):
                continue
    blocks = []
    for cid, turns in convos.items():
        turns.sort()
        lines = []
        for i, (_, u) in enumerate(turns):
            if not u or len(u) > 400:
                continue
            lines.append(f"{'User' if i % 2 == 0 else 'Ju6'}: {u}")
        if len(lines) >= 4:
            blocks.append("\n".join(lines))
            chars += sum(len(x) for x in lines)
        if chars > max_chars:
            break
    return blocks

def main():
    blocks = []
    p = DATA / "personachat" / "train_self_original.txt"
    if p.exists():
        b = personachat(p)
        print(f"personachat blocks={len(b)}")
        blocks += b
    e = DATA / "empatheticdialogues" / "train.csv"
    if e.exists():
        b = empathetic(e)
        print(f"empathetic blocks={len(b)}")
        blocks += b
    # our debate/personality blocks (keep Dashbattles style + identity)
    ours = (BASE / "big_corpus.txt").read_text(encoding="utf-8").split("\n\n")
    ours = [x.strip() for x in ours if x.strip()]
    blocks += ours * 3  # upweight style/identity ~10%
    random.shuffle(blocks)
    out = "\n\n".join(blocks)
    (BASE / "gpt_corpus.txt").write_text(out, encoding="utf-8")
    print(f"total blocks={len(blocks)} MB={len(out)/1e6:.1f}")

if __name__ == "__main__":
    main()
