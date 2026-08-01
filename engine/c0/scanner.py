"""PII and secret scanner (C0.5).

Detects secrets by assignment pattern, private key blocks, common tokens, real
``.env`` files, emails outside reserved example domains, Chilean RUTs in versionable
zones, and private-artifact path patterns (submissions, results, roster, operational
state, email previews/logs, capabilities).

An explicit, versioned allow-list covers approved synthetic fixtures and examples.
Sensitive values are masked, never printed in full.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from c0.util import mask_path, mask_value

ALLOWLIST_PATH = Path(__file__).resolve().parent / "allowlist.json"

SEVERITY_BLOCK = "BLOCK"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_INFO = "INFO"

MAX_CONTENT_SCAN_BYTES = 2 * 1024 * 1024  # content larger than this is not scanned
BINARY_SNIFF_BYTES = 8000  # first N bytes probed for a NUL byte

# High-confidence rules that can never be suppressed by the allow-list: private keys
# and real service tokens must always fail.
NON_ALLOWLISTABLE_RULES = frozenset(
    {
        "private-key-block",
        "private-key-file",
        "env-file",
        "aws-access-key",
        "github-token",
        "stripe-key",
        "slack-token",
        "google-api-key",
    }
)

RESERVED_EXAMPLE_DOMAINS = {
    "example.test",
    "example.com",
    "example.org",
    "example.net",
    "example.invalid",
    "invalid",
    "test",
    "localhost",
    "local",
}

PATTERN_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|"
    r"auth[_-]?token|refresh[_-]?token|session[_-]?secret|secret[_-]?key)\b\s*[:=]\s*"
    r"[\"']?([^\s\"'=;,]+)"
)
PATTERN_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
PATTERN_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
PATTERN_GITHUB_TOKEN = re.compile(r"\bghp_[0-9A-Za-z]{36,}\b|\bgithub_pat_[0-9A-Za-z_]{20,}\b")
PATTERN_STRIPE_KEY = re.compile(r"\bsk_(live|test)_[0-9a-zA-Z]{20,}\b")
PATTERN_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")
PATTERN_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
PATTERN_CHILEAN_RUT = re.compile(r"\b(?:\d{1,2}\.\d{3}\.\d{2,3}|\d{6,8})-[\dKk]\b")
PATTERN_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

RE_ENV_FILE = re.compile(r"(^|/)\.env($|\.)")
RE_PRIVATE_KEY_FILE = re.compile(r"\.(pem|key|p12|pfx)$")
RE_SUBMISSIONS_DIR = re.compile(r"(^|/)(submissions|entregas)(/|$)")
RE_RESULTS_DIR = re.compile(r"(^|/)(results|resultados)/")
RE_ROSTER_FILE = re.compile(r"(^|/)(students\.json|grades\.json|roster\.json)$")
RE_OPERATIONAL_STATE = re.compile(r"(^|/)(email-ledger|ledger|receipts|capabilities|locks|secrets|state-root)(/|$)")
RE_PREVIEW_LOG = re.compile(r"(^|/)(preview|email-preview|email-log)(/|$)")


def is_reserved_domain(domain: str) -> bool:
    domain = domain.lower().strip()
    return domain in RESERVED_EXAMPLE_DOMAINS or domain.endswith(".test") or domain.endswith(".invalid")


@dataclass
class ScanFinding:
    severity: str
    path: str
    rule: str
    message: str
    masked: Optional[str] = None

    def display_path(self) -> str:
        return mask_path(self.path)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "path": self.display_path(),
            "rule": self.rule,
            "message": self.message,
            "masked": self.masked,
        }


def glob_match(pattern: str, path: str) -> bool:
    """Match a glob supporting ``**``, ``*`` and ``?`` against a '/' separated path."""
    pattern_parts = pattern.split("/")
    path_parts = path.split("/")

    def match(pat: list[str], segments: list[str]) -> bool:
        if not pat:
            return not segments
        if pat[0] == "**":
            for skip in range(len(segments) + 1):
                if match(pat[1:], segments[skip:]):
                    return True
            return False
        if not segments:
            return False
        part = pat[0]
        if part == "*":
            if "/" in segments[0]:
                return False
        elif part == "?":
            if len(segments[0]) != 1:
                return False
        elif "*" in part or "?" in part:
            regex = re.escape(part).replace(r"\*", ".*").replace(r"\?", ".")
            if not re.fullmatch(regex, segments[0]):
                return False
        elif part != segments[0]:
            return False
        return match(pat[1:], segments[1:])

    return match(pattern_parts, path_parts)


class InvalidAllowlistError(Exception):
    """The allow-list violates the rules (wildcard rules or high-confidence rules)."""


class Scanner:
    def __init__(self, allowlist: Optional[list[dict]] = None):
        self.allowlist = allowlist if allowlist is not None else load_allowlist()

    def _allowed(self, rel_path: str, rule: str) -> Optional[dict]:
        if rule in NON_ALLOWLISTABLE_RULES:
            return None
        for entry in self.allowlist:
            allowed_rules = entry.get("rules") or []
            if "*" in allowed_rules:
                continue
            if glob_match(entry["path"], rel_path) and rule in allowed_rules:
                return entry
        return None

    def _finding(self, severity: str, rel_path: str, rule: str, message: str, masked: Optional[str] = None) -> Optional[ScanFinding]:
        if self._allowed(rel_path, rule):
            return None
        return ScanFinding(severity, rel_path, rule, message, masked)

    def scan_bytes(self, rel_path: str, content: bytes) -> list[ScanFinding]:
        return self._content_findings(rel_path, content)

    def _content_findings(self, rel_path: str, content: bytes) -> list[ScanFinding]:
        if len(content) > MAX_CONTENT_SCAN_BYTES:
            return []
        if b"\x00" in content[:BINARY_SNIFF_BYTES]:
            return []
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        findings: list[ScanFinding] = []
        for line in text.splitlines():
            for match in PATTERN_SECRET_ASSIGNMENT.finditer(line):
                finding = self._finding(
                    SEVERITY_BLOCK,
                    rel_path,
                    "secret-assignment",
                    f"Possible secret assigned to {match.group(1)!r}.",
                    mask_value(match.group(2)),
                )
                if finding:
                    findings.append(finding)
            for match in PATTERN_PRIVATE_KEY.finditer(line):
                finding = self._finding(SEVERITY_BLOCK, rel_path, "private-key-block", "Private key block detected.")
                if finding:
                    findings.append(finding)
            for pattern, rule, message in (
                (PATTERN_AWS_ACCESS_KEY, "aws-access-key", "Possible AWS access key."),
                (PATTERN_GITHUB_TOKEN, "github-token", "Possible GitHub token."),
                (PATTERN_STRIPE_KEY, "stripe-key", "Possible Stripe key."),
                (PATTERN_SLACK_TOKEN, "slack-token", "Possible Slack token."),
                (PATTERN_GOOGLE_API_KEY, "google-api-key", "Possible Google API key."),
            ):
                for match in pattern.finditer(line):
                    finding = self._finding(SEVERITY_BLOCK, rel_path, rule, message, mask_value(match.group(0)))
                    if finding:
                        findings.append(finding)
            for match in PATTERN_CHILEAN_RUT.finditer(line):
                finding = self._finding(
                    SEVERITY_BLOCK,
                    rel_path,
                    "chilean-rut",
                    "Possible Chilean RUT in a versionable zone.",
                    mask_value(match.group(0)),
                )
                if finding:
                    findings.append(finding)
            for match in PATTERN_EMAIL.finditer(line):
                domain = match.group(0).split("@")[-1].lower()
                if is_reserved_domain(domain):
                    continue
                finding = self._finding(
                    SEVERITY_BLOCK,
                    rel_path,
                    "email",
                    "Email address detected.",
                    mask_value(match.group(0)),
                )
                if finding:
                    findings.append(finding)
        return findings

    def scan_path(self, rel_path: str, path: Path) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        name = path.name
        if RE_ENV_FILE.search(rel_path) and not name.endswith(".env.example"):
            finding = self._finding(SEVERITY_BLOCK, rel_path, "env-file", "Real .env file detected.")
            if finding:
                findings.append(finding)
        if RE_PRIVATE_KEY_FILE.search(name):
            finding = self._finding(SEVERITY_BLOCK, rel_path, "private-key-file", "Private key / keystore file detected.")
            if finding:
                findings.append(finding)
        for regex, rule, message in (
            (RE_SUBMISSIONS_DIR, "submissions-dir", "Submissions directory detected."),
            (RE_RESULTS_DIR, "results-dir", "Individual results directory detected."),
            (RE_ROSTER_FILE, "roster-file", "Roster or grades file detected."),
            (RE_OPERATIONAL_STATE, "operational-state", "Operational state directory detected."),
            (RE_PREVIEW_LOG, "email-preview-log", "Email preview/log detected."),
        ):
            if regex.search(rel_path):
                finding = self._finding(SEVERITY_BLOCK, rel_path, rule, message)
                if finding:
                    findings.append(finding)
        return findings

    def scan_file(self, rel_path: str, path: Path) -> list[ScanFinding]:
        findings = self.scan_path(rel_path, path)
        try:
            content = path.read_bytes()
        except OSError:
            return findings
        findings.extend(self._content_findings(rel_path, content))
        return findings

    def scan_blob(self, rel_path: str, content: bytes) -> list[ScanFinding]:
        findings = self.scan_path(rel_path, Path(rel_path))
        findings.extend(self._content_findings(rel_path, content))
        return findings

    def scan_files(self, files: Iterable[tuple[str, Path]]) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        for rel_path, path in files:
            findings.extend(self.scan_file(rel_path, path))
        return findings

    def scan_blobs(self, files: Iterable[tuple[str, bytes]]) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        for rel_path, content in files:
            findings.extend(self.scan_blob(rel_path, content))
        return findings


def load_allowlist(path: Optional[Path] = None) -> list[dict]:
    allowlist_path = Path(path) if path is not None else ALLOWLIST_PATH
    if not allowlist_path.exists():
        return []
    payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    for entry in entries:
        rules = entry.get("rules") or []
        if not isinstance(rules, list) or not rules:
            raise InvalidAllowlistError(f"Allow-list entry must declare explicit rules: {entry.get('path')}")
        if "*" in rules:
            raise InvalidAllowlistError(f"Wildcard rule '*' is not allowed in the allow-list: {entry.get('path')}")
        for rule in rules:
            if rule in NON_ALLOWLISTABLE_RULES:
                raise InvalidAllowlistError(
                    f"Rule '{rule}' is high-confidence and cannot be allow-listed: {entry.get('path')}"
                )
    return entries
