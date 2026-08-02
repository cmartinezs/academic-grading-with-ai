"""Engine version and semver helpers.

Version comparison follows strict semver: numeric compare on
(major, minor, patch); any non-numeric patch is compared lexically after the
numeric triple.
"""

from __future__ import annotations

import re

__version__ = "0.1.0"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_version(text: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(text.strip())
    if not m:
        raise ValueError(f"Invalid semver version: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_compatible_engine(engine_min_version: str) -> bool:
    """True when the running engine satisfies the policy's minimum version."""
    return parse_version(__version__) >= parse_version(engine_min_version)
