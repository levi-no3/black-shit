"""Train ju6-GPT: custom transformer, custom BPE, next-token on real dialogue.
Fresh: python train_gpt.py --steps 200. Continue: --resume (constant LR)."""
import argparse
from pathlib import Path
import torch
import torch.nn as nn
from model import Ju6Sharp, Ju6Config
from bpe import BPE
BASE = Path(__file__).parent

CFG = dict(d_model=320, n_layers=6, n_heads=8, d_ff=1280, max_seq=96)

def sample(m, bpe, prompt, temp=0.6, mx=70):
    m.eval()
    seq = bpe.encode(prompt)[-m.cfg.max_seq:]
    ids = torch.tensor([seq], dtype=torch.long)
    eos = bpe.specials["<eos>"]
    with torch.no_grad():
        out = m.generate(ids, max_new=mx, temperature=temp, top_k=50,
                         repetition_penalty=1.1, eos_ids=(eos,))
    return bpe.decode(out[0].tolist()[len(seq):])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    import time as _t
    import os as _os
    torch.manual_seed((int(_t.time()) % 100000) + _os.getpid())
    print(f"[seed] {_t.time():.0f}", flush=True)
    bpe = BPE.load(BASE / "bpe.json")
    d = torch.load(BASE / "gpt_data.pt", map_location="cpu", weights_only=True)
    tr, va = d["train"].long(), d["val"].long()
    S = CFG["max_seq"]
    cfg = Ju6Config(vocab_size=bpe.vocab_size, d_model=CFG["d_model"],
                    n_layers=CFG["n_layers"], n_heads=CFG["n_heads"],
                    d_ff=CFG["d_ff"], max_seq=S)
    m = Ju6Sharp(cfg)
    print(f"[model] {m.count_params()/1e6:.2f}M vocab={bpe.vocab_size} train_tok={len(tr)/1e6:.2f}M")
    opt = torch.optim.AdamW(m.parameters(), lr=args.lr)
    resumed = False
    if args.resume and (BASE / "ju6_gpt.pt").exists():
        try:
            ck = torch.load(BASE / "ju6_gpt.pt", map_location="cpu", weights_only=True)
            if ck["cfg"]["vocab_size"] == bpe.vocab_size:
                m.load_state_dict(ck["state"])
                resumed = True
                print("[resume] constant LR")
        except Exception as e:
            print(f"[resume] failed: {e}")
    sch = None if resumed else torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps)

    def batch(split):
        dd = tr if split == "train" else va
        ix = torch.randint(0, len(dd) - S - 1, (args.batch,))
        x = torch.stack([dd[i:i + S] for i in ix])
        return x, torch.stack([dd[i + 1:i + S + 1] for i in ix])

    best, best_state = 1e9, None
    best_file = BASE / "ju6_gpt_bestval.txt"
    try:
        global_best = float(best_file.read_text().strip())
    except Exception:
        global_best = 1e9
    print(f"[best] global={global_best:.3f}")
    m.train()
    for s in range(1, args.steps + 1):
        x, y = batch("train")
        _, lo = m(x, y)
        opt.zero_grad()
        lo.backward()
        nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        if sch is not None:
            sch.step()
        if s % 50 == 0 or s == 1:
            m.eval()
            with torch.no_grad():
                xv, yv = batch("val")
                _, vl = m(xv, yv)
            print(f"step {s}/{args.steps} train={lo.item():.3f} val={vl.item():.3f}", flush=True)
            try:
                import datetime as _dt
                with open(BASE / "ju6_gpt_log.txt", "a") as _lf:
                    _lf.write(f"{_dt.datetime.now():%m-%d %H:%M:%S} step={s}/{args.steps} train={lo.item():.3f} val={vl.item():.3f}\n")
            except Exception:
                pass
            m.train()
            if vl.item() < best:
                best = vl.item()
                best_state = {k: v.cpu().clone() for k, v in m.state_dict().items()}
    if best_state is not None and best < global_best:
        torch.save({"state": best_state, "cfg": cfg.__dict__}, BASE / "ju6_gpt.pt")
        best_file.write_text(f"{best:.4f}")
        print(f"[save] new global best val={best:.3f}")
    else:
        print(f"[save] skipped (chunk best={best:.3f} vs global={global_best:.3f})")
    for p in ["User: hey\nJu6:", "User: I am bored\nJu6:",
              "User: I like football\nJu6:", "User: let us debate homework\nJu6:"]:
        print("---", repr(p), "\n" + sample(m, bpe, p)[:300])

if __name__ == "__main__":
    main()
