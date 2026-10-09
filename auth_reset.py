import secrets
import hashlib
from datetime import datetime, timedelta
from database import get_db

def generate_secure_reset_token():
    return secrets.token_urlsafe(32)

def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def create_reset_request(user_id, admin_id):
    raw_token = generate_secure_reset_token()
    token_hashed = hash_token(raw_token)
    expires_at = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    
    db = get_db()
    try:
        db.execute(
            """INSERT INTO password_resets (user_id, token_hash, expires_at, created_by_admin_id)
               VALUES (?, ?, ?, ?)""",
            (user_id, token_hashed, expires_at, admin_id)
        )
        db.execute(
            "INSERT INTO audit_logs (actor_id, target_id, action, status) VALUES (?, ?, ?, ?)",
            (admin_id, user_id, 'ADMIN_PASSWORD_RESET_REQUESTED', 'SUCCESS')
        )
        db.commit()
        return raw_token
    except Exception as e:
        db.execute(
            "INSERT INTO audit_logs (actor_id, target_id, action, status) VALUES (?, ?, ?, ?)",
            (admin_id, user_id, 'ADMIN_PASSWORD_RESET_REQUESTED', 'FAILURE')
        )
        db.commit()
        raise e

def validate_reset_token(raw_token):
    token_hashed = hash_token(raw_token)
    db = get_db()
    record = db.execute("SELECT * FROM password_resets WHERE token_hash = ?", (token_hashed,)).fetchone()
    
    if not record or record['used_at'] is not None:
        return None
    if datetime.utcnow() > datetime.fromisoformat(record['expires_at']):
        return None
    return record
