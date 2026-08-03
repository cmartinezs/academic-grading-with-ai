"""Transport contract for C3 email delivery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import Envelope, TransportConfig, TransportReceipt


class EmailTransport(ABC):
    @abstractmethod
    def preflight(self, config: TransportConfig) -> None:
        ...

    @abstractmethod
    def send(self, message, envelope: Envelope, config: TransportConfig) -> TransportReceipt:
        ...
