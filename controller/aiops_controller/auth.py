"""Authentication, rate limiting (40 req/s), and lockout security (5 failed attempts -> 2 min lock)."""
import os
import time
import secrets
import hashlib
from collections import defaultdict, deque
from typing import Optional, Dict, Tuple
from pydantic import BaseModel
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

# Configuration
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "admin123")
AUTH_OPERATOR_USER = os.getenv("AUTH_OPERATOR_USER", "operator")
AUTH_OPERATOR_PASS = os.getenv("AUTH_OPERATOR_PASS", "operator123")

RATE_LIMIT_RPS = int(os.getenv("RATE_LIMIT_RPS", "40"))  # 40 req/second
LOCKOUT_MAX_ATTEMPTS = int(os.getenv("LOCKOUT_MAX_ATTEMPTS", "5"))
LOCKOUT_DURATION_S = float(os.getenv("LOCKOUT_DURATION_S", "120.0"))  # 2 minutes

# Valid credential repository (username -> {password_hash, role, display_name})
def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

CREDENTIALS = {
    AUTH_USERNAME.lower(): {
        "password_hash": _hash_pw(AUTH_PASSWORD),
        "role": "admin",
        "display_name": "Administrator",
    },
    AUTH_OPERATOR_USER.lower(): {
        "password_hash": _hash_pw(AUTH_OPERATOR_PASS),
        "role": "operator",
        "display_name": "Site Reliability Operator",
    },
}

# In-memory storage with optional Redis sync
# Active sessions: token -> {username, role, expires_at, created_at}
_active_sessions: Dict[str, dict] = {}

# Lockout tracker: identifier (username or IP) -> {failed_count, locked_until, history}
_lockout_tracker: Dict[str, dict] = defaultdict(lambda: {"failed_count": 0, "locked_until": 0.0, "last_attempt": 0.0})

# Rate limiter: ip -> deque of timestamps within last 1 second
_rate_limit_tracker: Dict[str, deque] = defaultdict(deque)


class LoginRequest(BaseModel):
    username: str
    password: str


def get_client_ip(request: Request) -> str:
    """Extract client IP handling proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_rate_limit(ip: str) -> Tuple[bool, int, int]:
    """
    Check if IP has exceeded RATE_LIMIT_RPS within the last 1.0 second.
    Returns: (is_allowed, remaining_capacity, retry_after)
    """
    now = time.time()
    window_start = now - 1.0
    q = _rate_limit_tracker[ip]

    # Evict timestamps older than 1 second
    while q and q[0] < window_start:
        q.popleft()

    count = len(q)
    if count >= RATE_LIMIT_RPS:
        return False, 0, 1

    # Record current timestamp
    q.append(now)
    remaining = max(0, RATE_LIMIT_RPS - (count + 1))
    return True, remaining, 0


def get_lockout_status(identifier: str) -> dict:
    """Return current lockout status for an identifier (username or IP)."""
    now = time.time()
    record = _lockout_tracker[identifier]
    locked_until = record["locked_until"]

    if locked_until > now:
        remaining_s = int(locked_until - now) + 1
        return {
            "locked": True,
            "remaining_seconds": remaining_s,
            "failed_attempts": record["failed_count"],
            "remaining_attempts": 0,
        }
    else:
        # If lock expired, reset counter
        if record["locked_until"] > 0:
            record["failed_count"] = 0
            record["locked_until"] = 0.0
        remaining_attempts = max(0, LOCKOUT_MAX_ATTEMPTS - record["failed_count"])
        return {
            "locked": False,
            "remaining_seconds": 0,
            "failed_attempts": record["failed_count"],
            "remaining_attempts": remaining_attempts,
        }


def record_failed_login(identifier: str) -> dict:
    """
    Record a failed login attempt for an identifier.
    If 5 failed attempts reached, locks for 120s (2 minutes).
    """
    now = time.time()
    record = _lockout_tracker[identifier]

    # If previous lock expired, reset
    if record["locked_until"] > 0 and record["locked_until"] <= now:
        record["failed_count"] = 0
        record["locked_until"] = 0.0

    record["failed_count"] += 1
    record["last_attempt"] = now

    if record["failed_count"] >= LOCKOUT_MAX_ATTEMPTS:
        record["locked_until"] = now + LOCKOUT_DURATION_S
        return {
            "locked": True,
            "remaining_seconds": int(LOCKOUT_DURATION_S),
            "failed_attempts": record["failed_count"],
            "remaining_attempts": 0,
        }
    else:
        return {
            "locked": False,
            "remaining_seconds": 0,
            "failed_attempts": record["failed_count"],
            "remaining_attempts": LOCKOUT_MAX_ATTEMPTS - record["failed_count"],
        }


def reset_lockout(identifier: str):
    """Reset failed attempts on successful login."""
    if identifier in _lockout_tracker:
        _lockout_tracker[identifier]["failed_count"] = 0
        _lockout_tracker[identifier]["locked_until"] = 0.0


def create_session(username: str, role: str) -> str:
    """Generate and store an authentication session token."""
    token = secrets.token_hex(32)
    _active_sessions[token] = {
        "username": username,
        "role": role,
        "created_at": time.time(),
        "expires_at": time.time() + 86400,  # 24 hours
    }
    return token


def verify_session(token: Optional[str]) -> Optional[dict]:
    """Validate a session token."""
    if not token:
        return None
    session = _active_sessions.get(token)
    if not session:
        return None
    if time.time() > session["expires_at"]:
        del _active_sessions[token]
        return None
    return session


def revoke_session(token: str) -> bool:
    """Revoke a session token on logout."""
    if token in _active_sessions:
        del _active_sessions[token]
        return True
    return False


def verify_credentials(username: str, password: str) -> Optional[dict]:
    """Verify username and password against credentials."""
    user_entry = CREDENTIALS.get(username.strip().lower())
    if not user_entry:
        return None
    pw_hash = _hash_pw(password)
    if secrets.compare_digest(user_entry["password_hash"], pw_hash):
        return {
            "username": username.strip(),
            "role": user_entry["role"],
            "display_name": user_entry["display_name"],
        }
    return None
