"""
Discord TOS / Community Guidelines reference (summarized, not verbatim).
Official source: https://discord.com/guidelines
Bot uses these categories to label WHY something was deleted.
This is approximate enforcement aid, not legal advice. Discord's decision is final.
"""
import re

CATEGORIES = [
    {
        "id": "harassment",
        "label": "Harassment / Bullying",
        "summary": "Targeted insults, threats to a person, encouraging self-harm, dogpiling.",
        "patterns": [r"\bkys\b", r"kill yourself", r"\bretard\b", r"\bbitchtard\b", r"\bfucktard\b", r"\bidiot\b.*\bdead\b", r"shut up.*loser",
                     r"fuck(ed|ing)? your (mother|mom|mum|mama|dad|father|sister|brother)",
                     r"your (mother|mom|mum|mama).{0,20}(bitch|whore|slut|hoe)"],
    },
    {
        "id": "hate",
        "label": "Hate speech",
        "summary": "Slurs or dehumanizing language toward protected group (race, gender, orientation, religion, disability).",
        "patterns": [r"\bnigger\b", r"\bnigga\b", r"\bnigg+[aeiou]+\b", r"\bnygg+[aeiou]+\b", r"\bfaggot\b", r"\btranny\b", r"\bkike\b", r"\bgas the jews\b", r"\bjews control\b", r"\bgo back to africa\b"],
    },
    {
        "id": "threats",
        "label": "Threats / Violence",
        "summary": "Threats of violence, doxxing, encouraging violent extremism.",
        "patterns": [r"\bi will kill you\b", r"\bdox\b", r"\bddos\b", r"\bswat\b", r"\bgotta die\b", r"\bshould die\b", r"\bneed to die\b", r"\bdeserve to die\b"],
    },
    {
        "id": "sexual",
        "label": "Sexual / NSFW",
        "summary": "Explicit sexual content, grooming, non-consensual content. Keep SFW unless age-gated channel.",
        "patterns": [r"\brape\b", r"\braped\b", r"\brapist\b", r"\bgrapist\b", r"\braping\b"],
    },
    {
        "id": "spam",
        "label": "Spam / Scams",
        "summary": "Mass invites, phishing links, nitro scams, malware.",
        "patterns": [r"discord\.gg\/\S+", r"free nitro", r"steamcommunity.*login", r"@everyone.*giveaway"],
    },
    {
        "id": "provocative",
        "label": "Provocative / Trolling",
        "summary": "Baiting, brigading phrases meant to provoke reports/fights.",
        "patterns": [r"inclined to agree"],
    },
]

def classify_tos(text: str | None, toxicity_score: float = 0.0) -> tuple[str | None, str]:
    """
    Returns (category_id|None, reason).
    Keyword patterns first (precise), then toxicity score maps to harassment if high.
    """
    if not text:
        return None, ""
    low = text.lower()
    norm = _normalize(text)
    for cat in CATEGORIES:
        for pat in cat["patterns"]:
            try:
                if re.search(pat, low) or re.search(pat, norm):
                    return cat["id"], f"{cat['label']}: matched '{pat}'"
            except Exception:
                continue
    # high toxicity with no keyword -> generic harassment/provocative
    if toxicity_score >= 0.85:
        return "harassment", f"Harassment / Bullying: toxicity {toxicity_score:.2f}"
    return None, ""

def tos_list_text() -> str:
    lines = ["Discord Guidelines reference (summarized, see https://discord.com/guidelines):"]
    for c in CATEGORIES:
        lines.append(f"- {c['label']}: {c['summary']}")
    return "\n".join(lines)

# Mild swears allowed in friendly/undirected context. Severe stuff always deleted.
MILD_SWEARS = [r"\bshit\b", r"\bfuck\b", r"\bfucking\b", r"\bdamn\b", r"\bhell\b", r"\bcrap\b"]

# Full swear list for strict batch mode - every match deletes, no context pass.
SWEAR_PATTERNS = [
    r"\bshit\b", r"\bfuck\b", r"\bfucking\b", r"\bfucker\b", r"\bfuckers\b",
    r"\bdamn\b", r"\bhell\b", r"\bcrap\b", r"\bpiss\b",
    r"\bbitch\b", r"\bbitches\b", r"\bbitchtard\b", r"\bfucktard\b", r"\bslut\b", r"\bwhore\b",
    r"\bdick\b", r"\bpussy\b", r"\bcock\b", r"\btits\b",
    r"\bretard\b", r"\bretarded\b",
    r"\bbastard\b", r"\basshole\b", r"\bdouche\b",
]

def contains_swear(text: str | None) -> bool:
    if not text:
        return False
    import re as _re
    try:
        single = _re.sub(r"(.)\1+", r"\1", text.lower())
    except Exception:
        single = ""
    lows = [text.lower(), _normalize(text), single]
    for pat in SWEAR_PATTERNS:
        try:
            if any(_re.search(pat, t) for t in lows):
                return True
        except Exception:
            continue
    return False

DIRECTED_PATTERNS = [
    r"<@!?\d+>",  # user mention
    r"@everyone", r"@here",
    r"\byou('re|r| are)?\b.{0,20}(idiot|stupid|dumb|moron|shut|kys|retard|ugly|worthless|loser)",
    r"\byour (mother|mom|mum|mama|dad|father|sister|brother|family)\b",
    r"\bstfu\b", r"kill yourself", r"\bkys\b",
    r"\bi will kill you\b", r"\bdox\b",
]

# Explicit mild allowlist for smart/violations: never deleted (mode all still deletes everything).
BENIGN_MILD_TOKENS = {
    "tf", "wtf", "lol", "lmao", "lmfao", "rofl", "omg", "omfg",
    "idk", "tbh", "ngl", "shit", "damn", "hell", "crap",
}

def is_benign_mild(text: str | None) -> bool:
    """True if message is only mild tokens (tf/wtf/lol/shit...). Always allowed in smart/violations."""
    if not text:
        return False
    import re as _re
    t = text.lower().strip()
    if len(t) > 40:
        return False
    toks = [x for x in _re.split(r"[^a-z0-9']+", t) if x]
    if not toks or len(toks) > 6:
        return False
    return all(x in BENIGN_MILD_TOKENS for x in toks)

def _normalize(text: str) -> str:
    """Fold evasions to ASCII: NFKC (fancy fonts), confusable lookalikes (Cyrillic/Greek),
    leetspeak, then collapse 3+ repeats to 2 (niggger -> nigger, faggot stays)."""
    import re as _re
    import unicodedata as _ud
    if not text:
        return ""
    try:
        t = _ud.normalize("NFKC", text).lower()
    except Exception:
        t = text.lower()
    # Cyrillic / Greek lookalikes -> latin
    try:
        t = t.translate(_CONFUSABLES)
    except Exception:
        pass
    # leet
    t = (t.replace("0", "o").replace("1", "i").replace("3", "e").replace("4", "a")
          .replace("5", "s").replace("@", "a").replace("$", "s").replace("9", "g")
          .replace("6", "b").replace("7", "t").replace("2", "z").replace("8", "b"))
    # collapse 3+ repeats to 2 (niggger -> nigger, faggot stays)
    t = _re.sub(r"(.)\1{2,}", r"\1\1", t)
    return t

_CONFUSABLES = str.maketrans({
    # Cyrillic
    "а": "a", "е": "e", "ё": "e", "і": "i", "ї": "i", "ј": "j", "о": "o",
    "р": "p", "с": "c", "х": "x", "у": "y", "к": "k", "м": "m", "н": "h",
    "т": "t", "в": "b", "з": "z", "б": "b", "д": "d", "л": "n", "п": "n",
    "ф": "o", "ч": "y", "ш": "w", "г": "r",
    # Greek
    "α": "a", "ε": "e", "ι": "i", "ο": "o", "ρ": "p", "κ": "k", "ν": "v",
    "τ": "t", "χ": "x", "υ": "u", "ζ": "z", "η": "n",
    # misc symbols often abused
    "ı": "i", "ł": "l", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss",
})

def fold(text: str | None) -> str:
    """Public folding helper: what the text 'really says' for matching + LLM scoring."""
    try:
        return _normalize(text or "")
    except Exception:
        return (text or "").lower()

def contains_severe(text: str | None) -> bool:
    """Slurs, threats, scams, kys, hard slurs - always delete, no context exception."""
    if not text:
        return False
    low = text.lower()
    norm = _normalize(text)
    for cat in CATEGORIES:
        if cat["id"] in ("hate", "threats", "spam"):
            for pat in cat["patterns"]:
                try:
                    if re.search(pat, low) or re.search(pat, norm):
                        return True
                except Exception:
                    continue
    # hard blocks even outside categories (check raw + normalized to catch niggger, n1gger, etc.)
    _texts = [low, _normalize(text)]
    for pat in [r"\bnigger\b", r"\bnigga\b", r"\bnigg+[aeiou]+\b", r"\bnygg+[aeiou]+\b", r"\bnig[aeiou]+\b", r"\bfaggot\b", r"\bkike\b", r"\bgas the jews\b", r"\bkys\b", r"kill yourself",
                r"\bbitchtard\b", r"\bfucktard\b",
                r"fuck(ed|ing)? your (mother|mom|mum|mama|dad|father|sister|brother)",
                r"\brape\b", r"\braped\b", r"\brapist\b", r"\bgrapist\b", r"\braping\b"]:
        try:
            if any(re.search(pat, t) for t in _texts):
                return True
        except Exception:
            continue
    # also catch spaced-out evasions like "n i g g e r" (letters with spaces, up to 40 chars total).
    # "snigger" (to snicker) contains the slur as a substring - exclude that word family first.
    try:
        nospace = re.sub(r"[^a-z]", "", low).replace("snigger", "")
        for w in ["nigger", "nigga", "nygga", "niga", "faggot", "kike"]:
            if w in nospace:
                return True
    except Exception:
        pass
    return False

def is_directed(text: str | None, has_mention: bool = False) -> bool:
    if has_mention:
        return True
    if not text:
        return False
    low = text.lower()
    for pat in DIRECTED_PATTERNS:
        try:
            if re.search(pat, low):
                return True
        except Exception:
            continue
    return False

# Horrible directed content: always deleted even when playful-looking.
# Mild directed insults (idiot/stupid/dumb without slur/threat) are allowed per server preference.
HORRIBLE_PATTERNS = [
    r"\bkys\b", r"kill yourself", r"\bstfu\b",
    r"\bdox\b", r"\bddos\b", r"\bswat\b",
    r"\bgotta die\b", r"\bshould die\b", r"\bneed to die\b", r"\bdeserve to die\b",
    r"\bi will kill you\b",
    r"\bbitchtard\b", r"\bfucktard\b",
    r"fuck(ed|ing)? your (mother|mom|mum|mama|dad|father|sister|brother)",
    r"your (mother|mom|mum|mama).{0,20}(bitch|whore|slut|hoe)",
    r"\brape\b", r"\braped\b", r"\brapist\b", r"\bgrapist\b", r"\braping\b",
]

# Mentioning these deletes INSTANTLY (no delay), even though strikes never do.
INSTANT_PATTERNS = [r"\brape\b", r"\braped\b", r"\brapist\b", r"\bgrapist\b", r"\braping\b"]

def is_instant(text: str | None) -> bool:
    if not text:
        return False
    for t in _variants(text):
        for pat in INSTANT_PATTERNS:
            try:
                if re.search(pat, t):
                    return True
            except Exception:
                continue
    return False

PLAYFUL_MARKERS = [r"\bbro\b", r"\bbruh\b", r"\blol\b", r"\blmao\b", r"\bhaha\b", r"\bjk\b", r"/j\b", r"joking"]

def is_horrible_directed(text: str | None, has_mention: bool = False, slurs: bool = True) -> bool:
    """True only for horrible directed stuff (slur/threat/kys/stfu/dox). Playful mild insults return False."""
    if not text and not has_mention:
        return False
    t = text or ""
    # severe slurs/threats/scam = horrible no matter what
    try:
        if live_severe(t, delete_slurs=slurs):
            return True
    except Exception:
        pass
    low = t.lower()
    for pat in HORRIBLE_PATTERNS:
        try:
            if re.search(pat, low):
                return True
        except Exception:
            continue
    return False

def has_playful_marker(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    for pat in PLAYFUL_MARKERS:
        try:
            if re.search(pat, low):
                return True
        except Exception:
            continue
    return False

# Slur set (purge-only when live_slur_delete=False). Threats/scams/kys ALWAYS live-delete.
SLUR_WORDS = [r"\bnigger\b", r"\bnigga\b", r"\bfaggot\b", r"\btranny\b", r"\bkike\b",
               r"\bnigg+[aeiou]+\b", r"\bnygg+[aeiou]+\b", r"\bnig[aeiou]+\b"]
SLUR_PHRASES = [r"\bgas the jews\b", r"\bjews control\b", r"\bgo back to africa\b"]
NON_SLUR_SEVERE = [
    r"\bkys\b", r"kill yourself", r"\bstfu\b",
    r"\bdox\b", r"\bddos\b", r"\bswat\b",
    r"\bgotta die\b", r"\bshould die\b", r"\bneed to die\b", r"\bdeserve to die\b",
    r"\bi will kill you\b",
    r"discord\.gg\/\S+", r"free nitro", r"steamcommunity.*login", r"@everyone.*giveaway",
    r"\brape\b", r"\braped\b", r"\brapist\b", r"\bgrapist\b", r"\braping\b",
]

def _variants(text: str | None) -> list:
    if not text:
        return []
    low = text.lower()
    out = [low, _normalize(text)]
    try:
        out.append(re.sub(r"(.)\1+", r"\1", low))
    except Exception:
        pass
    try:
        out.append(re.sub(r"[^a-z]", "", low))
    except Exception:
        pass
    return out

def is_slur(text: str | None) -> bool:
    """True if text contains a slur (any evasion spelling). Threats/scams alone don't count."""
    if not text:
        return False
    for t in _variants(text):
        for pat in SLUR_WORDS + SLUR_PHRASES:
            try:
                if re.search(pat, t):
                    return True
            except Exception:
                continue
        try:
            if "nigger" in t or "nigga" in t or "faggot" in t or "kike" in t:
                return True
        except Exception:
            pass
    return False

def contains_non_slur_severe(text: str | None) -> bool:
    """Threats, scams, kys, stfu, dox - always live-delete, even when slurs are purge-only."""
    if not text:
        return False
    for t in _variants(text):
        for pat in NON_SLUR_SEVERE:
            try:
                if re.search(pat, t):
                    return True
            except Exception:
                continue
    return False

def live_severe(text: str | None, delete_slurs: bool = True) -> bool:
    """Severe check honoring the live-slur toggle. Purge paths always pass delete_slurs=True."""
    if not text:
        return False
    if contains_non_slur_severe(text):
        return True
    if delete_slurs and contains_severe(text):
        return True
    return False

def should_allow_mild(text: str | None, has_mention: bool = False) -> bool:
    """
    True = allow even if toxicity model scores high.
    Allows mild swears (shit/fuck/damn) when undirected: no mention, no severe slur/threat,
    no second-person attack. Targeted stuff still deleted.
    """
    if not text:
        return False
    if contains_severe(text):
        return False
    low = text.lower()
    has_mild = any(re.search(p, low) for p in MILD_SWEARS)
    if not has_mild:
        return False
    if is_directed(text, has_mention):
        return False
    return True

def conversation_heated(parent_text: str | None, recent_texts: list | None) -> bool:
    """True if parent/recent chat shows severe slur/threat or directed insult (ongoing fight)."""
    texts = []
    if parent_text:
        texts.append(parent_text)
    for t in recent_texts or []:
        if t:
            texts.append(t)
    for t in texts:
        try:
            if contains_severe(t):
                return True
            if is_directed(t, False):
                return True
        except Exception:
            continue
    return False

def context_verdict(
    text: str | None,
    parent_text: str | None = None,
    recent_texts: list | None = None,
    has_mention: bool = False,
    toxicity_score: float = 0.0,
    threshold: float = 0.8,
) -> tuple[bool, str]:
    """
    Full-context decision for mild swears.
    - Severe slur/threat/scam -> always delete.
    - Directed insult + toxic -> delete.
    - Mild swear undirected in calm chat -> allow.
    - Mild swear in heated thread (parent/recent fight) + you-pronoun/mention -> delete.
    Returns (delete: bool, reason: str).
    """
    t = text or ""
    if contains_severe(t):
        cat, reason = classify_tos(t, toxicity_score)
        return True, reason or "severe match"
    directed = is_directed(t, has_mention)
    if directed and toxicity_score >= min(threshold, 0.65):
        return True, f"directed + toxicity {toxicity_score:.2f}"
    # mild undirected: check conversation heat
    try:
        if should_allow_mild(t, has_mention):
            heated = conversation_heated(parent_text, recent_texts)
            if heated and ("you" in t.lower() or has_mention):
                return True, "mild swear in heated thread directed at someone"
            return False, "mild undirected swear in calm context - allowed"
    except Exception:
        pass
    if toxicity_score >= threshold:
        # last guard: high toxicity but no direction and no severe -> allow mild, else delete
        # if it is mild-only text, allow (model overflags profanity)
        try:
            low = t.lower()
            import re as _re
            if any(_re.search(p, low) for p in MILD_SWEARS) and not directed:
                return False, "high toxicity but undirected mild profanity - allowed"
        except Exception:
            pass
        return True, f"toxicity {toxicity_score:.2f} >= {threshold}"
    return False, "clean in context"
