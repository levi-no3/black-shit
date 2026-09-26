"""ju6 sharp - fully custom decoder-only transformer. No Llama, no HF."""
import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class Ju6Config:
    def __init__(self, vocab_size=260, d_model=256, n_layers=6, n_heads=8,
                 d_ff=1024, max_seq=128, dropout=0.0):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.max_seq = max_seq
        self.dropout = dropout


class CausalAttention(nn.Module):
    def __init__(self, cfg: Ju6Config):
        super().__init__()
        assert cfg.d_model % cfg.n_heads == 0
        self.n_heads = cfg.n_heads
        self.head_dim = cfg.d_model // cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model)
        self.out = nn.Linear(cfg.d_model, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv(x)  # B,T,3C
        q, k, v = qkv.chunk(3, dim=-1)
        # split heads
        q = q.view(B, T, self.n_heads, self.head_dim).transpose(1, 2)  # B,H,T,D
        k = k.view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        v = v.view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        att = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)  # B,H,T,T
        mask = torch.tril(torch.ones(T, T, device=x.device)).view(1, 1, T, T)
        att = att.masked_fill(mask == 0, float("-inf"))
        att = F.softmax(att, dim=-1)
        att = self.drop(att)
        y = att @ v  # B,H,T,D
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.out(y)


class MLP(nn.Module):
    def __init__(self, cfg: Ju6Config):
        super().__init__()
        self.fc1 = nn.Linear(cfg.d_model, cfg.d_ff)
        self.fc2 = nn.Linear(cfg.d_ff, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x):
        return self.drop(self.fc2(F.gelu(self.fc1(x))))


class Block(nn.Module):
    def __init__(self, cfg: Ju6Config):
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.d_model)
        self.attn = CausalAttention(cfg)
        self.ln2 = nn.LayerNorm(cfg.d_model)
        self.mlp = MLP(cfg)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class Ju6Sharp(nn.Module):
    """Custom GPT-style LM, byte-level vocab."""
    def __init__(self, cfg: Ju6Config):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos_emb = nn.Embedding(cfg.max_seq, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layers)])
        self.ln_f = nn.LayerNorm(cfg.d_model)
        self.head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.apply(self._init)

    def _init(self, m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, std=0.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.zeros_(m.bias)

    def forward(self, idx, targets=None):
        B, T = idx.shape
        assert T <= self.cfg.max_seq, f"seq {T} > max {self.cfg.max_seq}"
        pos = torch.arange(T, device=idx.device).unsqueeze(0)
        x = self.tok_emb(idx) + self.pos_emb(pos)
        x = self.drop(x)
        for b in self.blocks:
            x = b(x)
        x = self.ln_f(x)
        logits = self.head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    def count_params(self):
        return sum(p.numel() for p in self.parameters())

    @torch.no_grad()
    def generate(self, idx, max_new=80, temperature=0.8, top_k=40,
                 suppress_ids=(), repetition_penalty=1.0, eos_ids=(2, 258)):
        self.eval()
        for _ in range(max_new):
            cond = idx[:, -self.cfg.max_seq:]
            logits, _ = self(cond)
            logits = logits[:, -1, :] / max(temperature, 1e-5)
            if suppress_ids:
                logits[:, list(suppress_ids)] = float("-inf")
            if repetition_penalty != 1.0:
                seen = torch.unique(idx[0]).tolist()
                logits[:, seen] = logits[:, seen] / repetition_penalty
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float("-inf")
            probs = F.softmax(logits, dim=-1)
            nxt = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, nxt], dim=1)
            # stop on EOS (word EOS=2, byte EOS=258, BPE EOS passed in)
            if int(nxt[0, 0]) in eos_ids:
                break
        return idx
