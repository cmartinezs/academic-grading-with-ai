"""Fake transport for C3 email delivery testing.

Completely offline. Configurable for success, auth failure, invalid recipient,
transient failure, and ambiguous outcomes. Records only hashes/opaque IDs.
No network in CI.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from ..errors import (
    BatchTransportError,
    RecipientTransportError,
)
from ..models import Envelope, TransportConfig, TransportReceipt
from .base import EmailTransport


class FakeBehavior(Enum):
    SUCCESS = "success"
    AUTH_FAILURE = "auth-failure"
    INVALID_RECIPIENT = "invalid-recipient"
    TRANSIENT_FAILURE = "transient-failure"
    AMBIGUOUS = "ambiguous"


class FakeTransport(EmailTransport):
    def __init__(
        self,
        behavior: FakeBehavior = FakeBehavior.SUCCESS,
        fail_after: Optional[int] = None,
    ):
        self.behavior = behavior
        self.fail_after = fail_after
        self.sent_count = 0
        self.sent_envelopes: list[Envelope] = []
        self.sent_client_ids: list[str] = []

    def preflight(self, config: TransportConfig) -> None:
        if self.behavior == FakeBehavior.AUTH_FAILURE:
            raise BatchTransportError(
                "Fake auth failure",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="fake-auth-failure",
            )

    def send(self, message, envelope: Envelope, config: TransportConfig) -> TransportReceipt:
        if self.behavior == FakeBehavior.AUTH_FAILURE:
            raise BatchTransportError(
                "Fake auth failure",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="fake-auth-failure",
            )

        if self.fail_after is not None and self.sent_count >= self.fail_after:
            raise RecipientTransportError(
                "Fake transient failure after limit",
                scope="recipient",
                retryability="transient",
                delivery_certainty="notSent",
                code="fake-transient-limit",
            )

        client_message_id = ""
        if hasattr(message, 'get'):
            client_message_id = message.get("Message-ID", f"<{uuid.uuid4()}@fake>")

        if self.behavior == FakeBehavior.INVALID_RECIPIENT:
            raise RecipientTransportError(
                "Fake invalid recipient",
                scope="recipient",
                retryability="permanent",
                delivery_certainty="notSent",
                code="fake-invalid-recipient",
            )

        if self.behavior == FakeBehavior.TRANSIENT_FAILURE:
            raise RecipientTransportError(
                "Fake transient failure",
                scope="recipient",
                retryability="transient",
                delivery_certainty="notSent",
                code="fake-transient-failure",
            )

        if self.behavior == FakeBehavior.AMBIGUOUS:
            raise RecipientTransportError(
                "Fake ambiguous delivery",
                scope="recipient",
                retryability="transient",
                delivery_certainty="unknown",
                code="fake-ambiguous",
            )

        self.sent_count += 1
        self.sent_envelopes.append(envelope)
        self.sent_client_id = client_message_id
        self.sent_client_ids.append(client_message_id)

        return TransportReceipt(
            accepted=True,
            provider_message_id=f"fake-{self.sent_count}",
            client_message_id=client_message_id,
            response_code=250,
            response_class="accepted",
        )

    def reset(self) -> None:
        self.sent_count = 0
        self.sent_envelopes.clear()
        self.sent_client_ids.clear()
