"""In-memory, one-time password reset token helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta

from store import store


def generate_secure_reset_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_request(user_id, admin_id):
    raw_token = generate_secure_reset_token()
    store.add("password_resets", {
        "user_id": user_id,
        "token_hash": hash_token(raw_token),
        "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
        "created_by_admin_id": admin_id,
        "used_at": None,
    })
    store.add("audit_logs", {
        "actor_id": admin_id,
        "target_id": user_id,
        "action": "ADMIN_PASSWORD_RESET_REQUESTED",
        "status": "SUCCESS",
    })
    return raw_token


def validate_reset_token(raw_token):
    token_hash = hash_token(raw_token)
    record = next((row for row in store.all("password_resets")
                   if row["token_hash"] == token_hash), None)
    if record is None or record["used_at"] is not None:
        return None
    if datetime.utcnow() > datetime.fromisoformat(record["expires_at"]):
        return None
    return record
