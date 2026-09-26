"""Display polish for ju6 sharp: model trains lowercase, so restore
capitals, fix splits, cut stutters. Display-only, no retrain needed."""
import re

_CONNECTORS = {"and", "or", "but", "because", "since", "the", "a",
               "an", "to", "of", "with", "for", "that", "then"}

def _dedup_words(t):
    # the the -> the ; word word -> word
    return re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", t, flags=re.IGNORECASE)

def _dedup_phrases(t):
    # immediate repeated 2-4 word phrases -> one
    for n in (4, 3, 2):
        pat = r"((?:\b[\w']+\b[\s,]+){" + str(n) + r"})\1"
        t = re.sub(pat, r"\1", t, flags=re.IGNORECASE)
    return t

def _dedup_sentences(t):
    parts = re.split(r"(?<=[.!?])\s+", t)
    seen, out = set(), []
    for p in parts:
        k = p.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(p.strip())
    return " ".join(out)

def cut_tails(t):
    """Remove debate-pattern bleed for non-debate replies."""
    low = t.lower()
    for marker in ("how do you answer", "your turn on", "staying on",
                   "my claim is", "my reply on", "answer that point",
                   "your best point on", "too many unresolved",
                   "your point on", "tell me a name", "give me a setting"):
        i = low.find(marker)
        if i > 20:
            t = t[:i].rstrip(" ,;:")
            low = t.lower()
    return t


def polish(t):
    if not t:
        return t
    t = t.replace("ju 6 sharp", "Ju6 Sharp").replace("ju 6", "Ju6").replace("ju6", "Ju6")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    t = _dedup_words(t)
    t = _dedup_phrases(t)
    t = _dedup_sentences(t)
    # drop trailing fragment (1-2 word tail with no content)
    parts = re.split(r"(?<=[.!?])\s+", t)
    if len(parts) > 1 and len(re.findall(r"\w+", parts[-1])) <= 2:
        parts.pop()
        t = " ".join(parts)
    # cut dangling connector at the end
    toks = t.split(" ")
    while len(toks) > 4 and toks[-1].strip(".,!?").lower() in _CONNECTORS:
        toks.pop()
    t = " ".join(toks)
    # sentence case
    def _cap(m):
        return m.group(1) + m.group(2).upper()
    t = re.sub(r"(^|[.!?]\s+)([a-z])", _cap, t)
    # standalone i -> I
    t = re.sub(r"\bi\b", "I", t)
    t = re.sub(r"\bi'(m|ve|ll|d)\b",
               lambda m: "I'" + {"m": "m", "ve": "ve", "ll": "ll", "d": "d"}[m.group(1)],
               t)
    t = t[0].upper() + t[1:] if t else t
    if t and t[-1] not in ".!?":
        t += "."
    return t
