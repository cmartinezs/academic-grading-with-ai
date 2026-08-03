"""Email normalization and validation for C3 email delivery."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .errors import InvalidEmailError


_LOCAL_PART_RE = re.compile(r'^[^\s@]+$')
_DOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$')
_DISPLAY_NAME_RE = re.compile(r'["\']')
_LIST_INDICATORS = re.compile(r'[;,]')


def normalize_email(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise InvalidEmailError("Email address is empty.")
    for ch in raw:
        if ord(ch) < 32 or ch in ('\r', '\n'):
            raise InvalidEmailError(f"Control character in email address.")
    if _DISPLAY_NAME_RE.search(raw):
        raise InvalidEmailError("Embedded display-name in email address.")
    if _LIST_INDICATORS.search(raw):
        raise InvalidEmailError("List separator in email address (CC/BCC prohibited).")
    if raw.startswith('<') or raw.endswith('>'):
        raise InvalidEmailError("Angle-bracket email syntax not supported.")
    if '@' not in raw:
        raise InvalidEmailError("Missing @ in email address.")
    parts = raw.rsplit('@', 1)
    local_part = parts[0]
    domain = parts[1]
    if not local_part:
        raise InvalidEmailError("Empty local-part.")
    if not domain:
        raise InvalidEmailError("Empty domain.")
    if not _LOCAL_PART_RE.match(local_part):
        raise InvalidEmailError(f"Invalid local-part: {local_part!r}")
    try:
        domain = domain.lower()
        if any(ord(c) > 127 for c in domain):
            domain = domain.encode('idna').decode('ascii')
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise InvalidEmailError(f"IDNA encoding failed for domain: {exc}") from exc
    if not _DOMAIN_RE.match(domain):
        raise InvalidEmailError(f"Invalid domain: {domain!r}")
    normalized = f"{local_part}@{domain}"
    return normalized


def mask_email(email: str) -> str:
    if '@' not in email:
        return "***"
    local, domain = email.rsplit('@', 1)
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    return f"{masked_local}@{domain}"


def is_valid_email(raw: str) -> bool:
    try:
        normalize_email(raw)
        return True
    except InvalidEmailError:
        return False


def normalize_unicode_nfc(text: str) -> str:
    return unicodedata.normalize('NFC', text)


def normalize_line_endings(text: str) -> str:
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '\n')
    return text


def check_crlf_injection(text: str) -> None:
    if '\r' in text or '\n' in text:
        from .errors import CRLFInjectionError
        raise CRLFInjectionError("CR or LF detected in subject or header value.")
