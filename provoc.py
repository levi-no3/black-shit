"""
Tiny provocative/toxicity detector.
Tries AssistantsLab/Tiny-Toxic-Detector (2M params, ~10MB RAM, CPU fast).
Falls back to keyword heuristics if torch/transformers not installed.
"""
import re

MODEL_ID = "gravitee-io/bert-tiny-toxicity"

_model = None
_tokenizer = None
_device = None
_load_error = None

# fallback provocative patterns (used if LLM unavailable, and combined with LLM)
FALLBACK_PATTERNS = [
    r"inclined to agree",
    r"\bkys\b", r"\bkill yourself\b",
    r"\bretard\b", r"\bfaggot\b", r"\bnigger\b", r"\bnigga\b", r"\bnigg+[aeiou]+\b", r"\bnygg+[aeiou]+\b",
    r"\bkike\b", r"\bgas the jews\b",
    r"\bwhore\b", r"\bslut\b",
    r"discord\.gg\/\S+",  # invite spam often provocative in this context
]

def _folded(text: str) -> str:
    try:
        import tos as _tos
        f = _tos.fold(text)
        return f if f else (text or "")
    except Exception:
        return text or ""

def _try_load_llm():
    global _model, _tokenizer, _device, _load_error
    if _model is not None or _load_error is not None:
        return
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        _device = torch.device("cpu")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        _model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_ID, trust_remote_code=True
        ).to(_device)
        _model.eval()
        print(f"[provoc] LLM loaded: {MODEL_ID}", flush=True)
    except Exception as e:
        _load_error = str(e)
        print(f"[provoc] LLM unavailable, using fallback: {e}", flush=True)

def llm_available() -> bool:
    _try_load_llm()
    return _model is not None

def load_status() -> str:
    _try_load_llm()
    if _model is not None:
        return f"LLM active: {MODEL_ID}"
    return f"LLM fallback (keywords only). Reason: {_load_error}"

def fallback_score(text: str) -> float:
    if not text:
        return 0.0
    low = text.lower()
    # strong hits
    for pat in FALLBACK_PATTERNS:
        try:
            if re.search(pat, low):
                return 0.95
        except Exception:
            continue
    # heuristic: excessive caps + insults
    caps_ratio = sum(1 for c in text if c.isupper()) / max(1, len(text))
    if caps_ratio > 0.7 and len(text) > 10:
        return 0.6
    return 0.0

def _candidates(text: str) -> list:
    """Raw + folded variants; best score wins (catches fancy-font/Cyrillic/leet evasions)."""
    t = text or ""
    try:
        f = _folded(t)
    except Exception:
        f = t
    return [t] if f == t else [t, f]

def _model_probs(rows: list) -> list:
    """Single forward pass over rows. Returns toxic probs in order (may raise)."""
    import torch
    inputs = _tokenizer(rows, return_tensors="pt", truncation=True, max_length=128, padding=True)
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = _model(**inputs).logits
        if logits.shape[-1] == 1:
            probs = torch.sigmoid(logits).flatten().tolist()
        else:
            probs = torch.softmax(logits, dim=-1)[:, 1].tolist()
    return probs if isinstance(probs, list) else [probs]

def score_text(text: str) -> tuple[float, str]:
    """
    Returns (score 0-1, source 'llm'|'fallback').
    LLM score = toxicity probability. Fallback = heuristic.
    """
    if not text or len(text.strip()) == 0:
        return 0.0, "none"
    _try_load_llm()
    if _model is not None:
        try:
            cands = _candidates(text)
            probs = _model_probs(cands)
            best = 0.0
            for t, p in zip(cands, probs):
                try:
                    fb = fallback_score(t)
                    best = max(best, float(p), fb)
                except Exception:
                    continue
            return best, "llm"
        except Exception as e:
            print(f"[provoc] inference failed, fallback: {e}", flush=True)
    return fallback_score(text), "fallback"

def score_batch(texts: list, batch_size: int = 32) -> list:
    """
    Score many texts with one forward pass per mini-batch (~5-10x faster than
    score_text in a loop). Returns list of (score, src) matching input order.
    Falls back to per-text scoring if the model is unavailable.
    """
    if not texts:
        return []
    _try_load_llm()
    if _model is None:
        return [(fallback_score(t or ""), "fallback") for t in texts]
    try:
        out: list = [None] * len(texts)
        # expand each text to raw+folded variants, score all in mini-batches, take best per text
        flat, owner = [], []
        for k, t in enumerate(texts):
            for v in _candidates(t or ""):
                flat.append(v)
                owner.append(k)
        probs_all: list = []
        for i in range(0, len(flat), batch_size):
            try:
                probs_all.extend(_model_probs(flat[i : i + batch_size]))
            except Exception as e:
                print(f"[provoc] batch inference failed, fallback: {e}", flush=True)
                probs_all.extend([None] * len(flat[i : i + batch_size]))
        for k in range(len(texts)):
            try:
                best, fb_best = 0.0, fallback_score(texts[k] or "")
                for j, o in enumerate(owner):
                    if o == k and probs_all[j] is not None:
                        best = max(best, float(probs_all[j]))
                out[k] = (max(best, fb_best), "llm")
            except Exception:
                out[k] = (fallback_score(texts[k] or ""), "fallback")
        return out
    except Exception:
        return [(fallback_score(t or ""), "fallback") for t in texts]

def is_provocative(text: str, threshold: float = 0.75) -> tuple[bool, float, str]:
    score, src = score_text(text)
    return score >= threshold, score, src
