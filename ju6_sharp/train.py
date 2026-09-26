"""Train ju6 sharp tiny on CPU. Usage: python train.py --steps 800"""
import argparse, json, random
from pathlib import Path
import torch
import torch.nn as nn
from model import Ju6Sharp, Ju6Config
import tokenizer as tk

BASE = Path(__file__).parent

def load_text(extra_path=None):
    t = (BASE / "seed_corpus.txt").read_text(encoding="utf-8")
    if extra_path and Path(extra_path).exists():
        t += "\n" + Path(extra_path).read_text(encoding="utf-8", errors="ignore")
        print(f"[data] added extra {extra_path}")
    # also allow discord_export.txt drop-in
    d = BASE / "discord_export.txt"
    if d.exists():
        t += "\n" + d.read_text(encoding="utf-8", errors="ignore")
        print("[data] included discord_export.txt")
    return t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--seq", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d_model", type=int, default=256)
    ap.add_argument("--layers", type=int, default=6)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--extra", type=str, default=None)
    args = ap.parse_args()

    torch.manual_seed(7)
    random.seed(7)

    text = load_text(args.extra)
    ids = tk.encode_noboseos(text)
    print(f"[data] chars={len(text)} bytes={len(ids)}")
    data = torch.tensor(ids, dtype=torch.long)
    n = int(len(data) * 0.95)
    train_d, val_d = data[:n], data[n:]

    cfg = Ju6Config(vocab_size=tk.VOCAB_SIZE, d_model=args.d_model,
                    n_layers=args.layers, n_heads=args.heads,
                    d_ff=args.d_model*4, max_seq=args.seq)
    m = Ju6Sharp(cfg)
    print(f"[model] params={m.count_params()/1e6:.2f}M d={args.d_model} L={args.layers} H={args.heads} seq={args.seq}")
    opt = torch.optim.AdamW(m.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps)

    def batch(split):
        d = train_d if split == "train" else val_d
        ix = torch.randint(0, max(1, len(d)-args.seq-1), (args.batch,))
        x = torch.stack([d[i:i+args.seq] for i in ix])
        y = torch.stack([d[i+1:i+args.seq+1] for i in ix])
        return x, y

    m.train()
    best = 1e9
    for step in range(1, args.steps+1):
        x, y = batch("train")
        _, loss = m(x, y)
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step(); sched.step()
        if step % 100 == 0 or step == 1:
            m.eval()
            with torch.no_grad():
                xv, yv = batch("val")
                _, vl = m(xv, yv)
            print(f"step {step}/{args.steps} train={loss.item():.3f} val={vl.item():.3f} lr={sched.get_last_lr()[0]:.2e}", flush=True)
            m.train()
            if vl.item() < best:
                best = vl.item()
    # save
    ck = BASE / "ju6_sharp.pt"
    torch.save({"state": m.state_dict(), "cfg": cfg.__dict__}, ck)
    (BASE / "config.json").write_text(json.dumps(cfg.__dict__, indent=2))
    print(f"[save] {ck} best_val={best:.3f}")

    # demo samples
    m.eval()
    for prompt in ["User: Let's debate pizza.\nJu6:", "User: Help me write an apology.\nJu6:"]:
        ids_p = torch.tensor([tk.encode_noboseos(prompt)], dtype=torch.long)
        out = m.generate(ids_p, max_new=80, temperature=0.8, top_k=40)
        print("---\n" + tk.decode(out[0].tolist())[-400:])

if __name__ == "__main__":
    main()
