"""Custom byte-level tokenizer for ju6 sharp. Vocab 0-255 bytes + specials."""
PAD, BOS, EOS = 256, 257, 258
VOCAB_SIZE = 260

def encode(text: str):
    b = text.encode("utf-8", errors="ignore")
    return [BOS] + list(b) + [EOS]

def encode_noboseos(text: str):
    return list(text.encode("utf-8", errors="ignore"))

def decode(ids):
    # strip specials
    bs = bytes([i for i in ids if 0 <= i < 256])
    return bs.decode("utf-8", errors="ignore")
