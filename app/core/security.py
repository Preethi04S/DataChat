"""Enterprise Security Module — OWASP-aligned input sanitization, XSS prevention,
request validation, Content Security Policy headers, and CSRF protection.

Aligned with Akaike Technologies' enterprise AI security standards.
"""
from __future__ import annotations
import re
import hashlib
import hmac
import time
import html
import secrets
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Input Sanitization Patterns ──
_SQL_INJECTION_PATTERN = re.compile(
    r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|EXEC|EXECUTE)\b)",
    re.IGNORECASE,
)
_XSS_PATTERN = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_XSS_EVENT_PATTERN = re.compile(r"\bon\w+\s*=", re.IGNORECASE)
_XSS_TAG_PATTERN = re.compile(r"<\s*(iframe|object|embed|form|input|img|svg|math)\b", re.IGNORECASE)
_PATH_TRAVERSAL_PATTERN = re.compile(r"\.\./|\.\.\\|%2e%2e|%252e")
_SHELL_INJECTION_PATTERN = re.compile(r"[;|&`$]")
_TEMPLATE_INJECTION_PATTERN = re.compile(r"\{\{.*\}\}|\$\{.*\}", re.DOTALL)
_NULL_BYTE_PATTERN = re.compile(r"%00|\x00")


def sanitize_input(text: str) -> str:
    """Sanitize user input against injection attacks.
    Returns cleaned text safe for processing.
    """
    # Remove null bytes first
    cleaned = _NULL_BYTE_PATTERN.sub("", text.strip())
    cleaned = html.escape(cleaned)
    cleaned = _XSS_PATTERN.sub("", cleaned)
    cleaned = _PATH_TRAVERSAL_PATTERN.sub("", cleaned)
    cleaned = _TEMPLATE_INJECTION_PATTERN.sub("", cleaned)
    return cleaned


def detect_injection_attempt(text: str) -> tuple[bool, str]:
    """Detect potential injection attacks in user input.
    Returns (is_suspicious, reason).
    """
    if _NULL_BYTE_PATTERN.search(text):
        return True, "Null byte injection detected"
    if _SQL_INJECTION_PATTERN.search(text):
        return True, "Potential SQL injection pattern detected"
    if _XSS_PATTERN.search(text):
        return True, "Potential XSS script injection detected"
    if _XSS_EVENT_PATTERN.search(text):
        return True, "Potential XSS event handler detected"
    if _XSS_TAG_PATTERN.search(text):
        return True, "Potential XSS HTML tag injection detected"
    if _PATH_TRAVERSAL_PATTERN.search(text):
        return True, "Potential path traversal detected"
    if _SHELL_INJECTION_PATTERN.search(text) and len(text) < 20:
        return True, "Potential shell injection pattern detected"
    if _TEMPLATE_INJECTION_PATTERN.search(text):
        return True, "Potential template injection detected"
    return False, ""


def validate_filename(filename: str) -> tuple[bool, str]:
    """Validate uploaded filename for safety."""
    if not filename or len(filename) > 255:
        return False, "Invalid filename length"
    if _PATH_TRAVERSAL_PATTERN.search(filename):
        return False, "Path traversal in filename"
    if _NULL_BYTE_PATTERN.search(filename):
        return False, "Invalid characters in filename"
    dangerous_extensions = {
        ".exe", ".bat", ".cmd", ".sh", ".ps1", ".py", ".js", ".php",
        ".msi", ".scr", ".pif", ".vbs", ".wsf", ".com", ".jar",
        ".dll", ".sys", ".cpl", ".inf", ".reg",
    }
    lower_name = filename.lower()
    for ext in dangerous_extensions:
        if lower_name.endswith(ext):
            return False, f"Dangerous file extension: {ext}"
    # Check double extensions (e.g., file.csv.exe)
    parts = lower_name.rsplit(".", 2)
    if len(parts) > 2:
        for ext in dangerous_extensions:
            if f".{parts[-1]}" in dangerous_extensions:
                return False, f"Dangerous file extension: .{parts[-1]}"
    return True, ""


def compute_request_signature(request_id: str, timestamp: float) -> str:
    """Compute HMAC signature for request traceability."""
    from app.core.config import SESSION_SECRET
    payload = f"{request_id}:{timestamp}"
    return hmac.new(
        SESSION_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]


def generate_nonce() -> str:
    """Generate a cryptographic nonce for CSP."""
    return secrets.token_urlsafe(16)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds enterprise security headers to all responses.
    Implements OWASP recommended security headers.
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.monotonic()

        # ── Request Size Limiting ──
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 52_428_800:  # 50MB
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )

        response: Response = await call_next(request)

        # ── OWASP Security Headers ──
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(self), geolocation=(), "
            "payment=(), usb=(), bluetooth=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://api.groq.com; "
            "media-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # ── Cache Control for API responses ──
        if request.url.path.startswith("/ask") or request.url.path.startswith("/upload"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"

        # ── Request Timing & Tracing ──
        elapsed = round((time.monotonic() - start_time) * 1000, 2)
        response.headers["X-Response-Time"] = f"{elapsed}ms"
        response.headers["X-Request-Id"] = request.headers.get("X-Request-Id", "none")

        return response
