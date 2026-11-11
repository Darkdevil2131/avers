"""Accounts: scrypt password hashing + HMAC-signed expiring tokens (stdlib only)."""
import base64
import hashlib
import hmac
import json
import os
import time

N, R, P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=R, p=P, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(user_id: int, role: str, secret: str, ttl_s: int, now: float | None = None) -> str:
    body = _b64(json.dumps({"uid": user_id, "role": role, "exp": int((now or time.time()) + ttl_s)}).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_token(token: str, secret: str, now: float | None = None):
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["exp"] < (now or time.time()):
            return None
        return {"id": data["uid"], "role": data["role"]}
    except Exception:
        return None
