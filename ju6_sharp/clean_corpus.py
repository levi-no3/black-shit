"""Drop junk/dupe blocks from gpt_corpus.txt"""
from pathlib import Path
B = Path(__file__).parent
seen, out, dropped = set(), [], 0
for b in (B / "gpt_corpus.txt").read_text(encoding="utf-8").split("\n\n"):
    b = b.strip()
    if not b or "|" in b or "\t" in b or "your persona:" in b:
        dropped += 1
        continue
    if b in seen:
        dropped += 1
        continue
    seen.add(b)
    out.append(b)
(B / "gpt_corpus.txt").write_text("\n\n".join(out), encoding="utf-8")
size = (B / "gpt_corpus.txt").stat().st_size / 1e6
print(f"kept={len(out)} dropped={dropped} MB={size:.1f}")
