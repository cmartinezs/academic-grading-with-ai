"""Injectable clock supporting SOURCE_DATE_EPOCH (C1)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping, Optional

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Clock:
    """Deterministic UTC clock.

    - ``now`` fixed value when injected;
    - otherwise ``SOURCE_DATE_EPOCH`` (integer seconds, UTC) when set;
    - otherwise current UTC time truncated to seconds.
    """

    def __init__(self, now: Optional[datetime] = None, env: Optional[Mapping[str, str]] = None):
        env = dict(os.environ) if env is None else dict(env)
        self._fixed: Optional[datetime] = None
        if now is not None:
            self._fixed = now.astimezone(timezone.utc)
        else:
            source = (env.get("SOURCE_DATE_EPOCH") or "").strip()
            if source:
                self._fixed = datetime.fromtimestamp(int(source), tz=timezone.utc)

    def utc_now(self) -> datetime:
        if self._fixed is not None:
            return self._fixed.replace(microsecond=0, tzinfo=timezone.utc)
        return datetime.now(timezone.utc).replace(microsecond=0)

    def iso(self) -> str:
        return self.utc_now().strftime(ISO_FORMAT)
