"""Email masking utilities for C3 email delivery."""

from __future__ import annotations


def mask_email(email: str) -> str:
    if '@' not in email:
        return "***"
    local, domain = email.rsplit('@', 1)
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    return f"{masked_local}@{domain}"


def mask_name(name: str) -> str:
    if not name:
        return ""
    parts = name.split()
    if len(parts) <= 1:
        return parts[0][0] + "***" if parts else ""
    return parts[0][0] + "*** " + parts[-1][0] + "***"


def mask_subject(subject: str) -> str:
    if len(subject) <= 10:
        return subject[:3] + "***"
    return subject[:7] + "***"


def sanitize_log_value(value: str) -> str:
    if '@' in value:
        return mask_email(value)
    return value
