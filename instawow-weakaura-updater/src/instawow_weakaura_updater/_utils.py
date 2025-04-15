from __future__ import annotations


def get_checksum(*values: object) -> str:
    "Base-16-encode a string using SHA-256, truncated to 32 characters."
    from hashlib import sha256

    return sha256(''.join(str(v) for v in values if v).encode()).hexdigest()[:32]
