"""Train word-level ju6 sharp. Fresh: python train_word.py. Continue: --resume (constant LR, no spikes)."""
import argparse
from pathlib import Path
import torch, torch.nn as nn
from model import Ju6Sharp, Ju6Config
from tokenizer_word import WordTok
BASE = Path(__file__).parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=350)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--seq", type=int, default=64)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    torch.manual_seed(7)
    seed = (BASE/"seed_corpus.txt").read_text(encoding="utf-8")
    big = (BASE/"big_corpus.txt").read_text(encoding="utf-8") if (BASE/"big_corpus.txt").exists() else ""
    dex = BASE/"discord_export.txt"
    if dex.exists():
        big += "\n" + dex.read_text(encoding="utf-8", errors="ignore")
    text = seed + "\n" + big
    print(f"[data] chars={len(text)/1e6:.2f}MB")
    if args.resume and (BASE/"vocab.json").exists():
        tk = WordTok.load(BASE/"vocab.json")
        print(f"[vocab] reused {len(tk)}")
    else:
        tk = WordTok.build(text)
        tk.save(BASE/"vocab.json")
        print(f"[vocab] new {len(tk)}")
    ids = []
    for blk in text.split("\n\n"):
        blk = blk.strip()
        if blk:
            ids.extend(tk.encode(blk))
    print(f"[tokens] {len(ids)/1e3:.0f}k")
    data = torch.tensor(ids, dtype=torch.long)
    n = int(len(data) * 0.97)
    tr, va = data[:n], data[n:]
    cfg = Ju6Config(vocab_size=len(tk), d_model=256, n_layers=6, n_heads=8,
                    d_ff=1024, max_seq=args.seq)
    m = Ju6Sharp(cfg)
    print(f"[model] {m.count_params()/1e6:.2f}M")
    opt = torch.optim.AdamW(m.parameters(), lr=args.lr)
    resumed = False
    if args.resume and (BASE/"ju6_sharp_word.pt").exists():
        try:
            ck = torch.load(BASE/"ju6_sharp_word.pt", map_location="cpu")
            if ck["cfg"]["vocab_size"] == len(tk) and ck["cfg"]["max_seq"] == args.seq:
                m.load_state_dict(ck["state"])
                resumed = True
                print("[resume] weights loaded, constant LR (no cosine restart)")
            else:
                print("[resume] shape mismatch, fresh start")
        except Exception as e:
            print(f"[resume] failed: {e}")
    sch = None
    if not resumed:
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps)

    def batch(d):
        ix = torch.randint(0, max(1, len(d)-args.seq-1), (args.batch,))
        return (torch.stack([d[i:i+args.seq] for i in ix]),
                torch.stack([d[i+1:i+args.seq+1] for i in ix]))
    best, best_state = 1e9, None
    m.train()
    for s in range(1, args.steps+1):
        x, y = batch(tr)
        _, lo = m(x, y)
        opt.zero_grad(); lo.backward()
        nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        if sch is not None:
            sch.step()
        if s % 150 == 0 or s == 1:
            m.eval()
            with torch.no_grad():
                xv, yv = batch(va)
                _, vl = m(xv, yv)
            print(f"step {s}/{args.steps} train={lo.item():.3f} val={vl.item():.3f}", flush=True)
            m.train()
            if vl.item() < best:
                best = vl.item()
                best_state = {k: v.cpu().clone() for k, v in m.state_dict().items()}
    if best_state is not None:
        torch.save({"state": best_state, "cfg": cfg.__dict__}, BASE/"ju6_sharp_word.pt")
        torch.save({"state": best_state, "cfg": cfg.__dict__}, BASE/"ju6_sharp_word_best.pt")
        print(f"[save] best val={best:.3f} -> pt + best.pt")
    else:
        print("[save] skipped, no improvement")
    m.eval()
    for p in ["User: hi, how are you?\nJu6:", "User: let us debate homework.\nJu6:",
              "User: help me write an apology.\nJu6:"]:
        enc = torch.tensor([tk.encode_raw(p)], dtype=torch.long)[:, -args.seq:]
        out = m.generate(enc, max_new=60, temperature=0.6, top_k=40)
        txt = tk.decode(out[0].tolist()[len(enc[0]):])
        if "user:" in txt:
            txt = txt.split("user:")[0]
        print("---\n" + txt[:350])

if __name__ == "__main__":
    main()
