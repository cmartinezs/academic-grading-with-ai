"""SMTP transport for C3 email delivery.

Uses smtplib standard library. TLS required. One recipient per message.
Password from TransportConfig or environment variable ACADGRAD_SMTP_PASSWORD.
TransportConfig is the single authority; no re-reading from env during send.
"""

from __future__ import annotations

import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from typing import Optional

from ..errors import (
    BatchTransportError,
    CRLFInjectionError,
    RecipientTransportError,
    TransportError,
)
from ..models import Envelope, TlsMode, TransportConfig, TransportReceipt
from .base import EmailTransport

SMTP_PASSWORD_ENV = "ACADGRAD_SMTP_PASSWORD"


class SMTPTransport(EmailTransport):
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def preflight(self, config: TransportConfig) -> None:
        if not config.host:
            raise BatchTransportError(
                "SMTP host not configured",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="smtp-host-missing",
            )
        if not config.port:
            raise BatchTransportError(
                "SMTP port not configured",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="smtp-port-missing",
            )
        if not config.username:
            raise BatchTransportError(
                "SMTP username not configured",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="smtp-username-missing",
            )
        password = config.password or os.environ.get(SMTP_PASSWORD_ENV)
        if not password:
            raise BatchTransportError(
                "SMTP password not set",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="smtp-auth-missing",
            )

    def send(self, message: EmailMessage, envelope: Envelope, config: Optional[TransportConfig] = None) -> TransportReceipt:
        client_message_id = message.get("Message-ID", f"<{uuid.uuid4()}@localhost>")

        try:
            if envelope.from_address and ('\r' in envelope.from_address or '\n' in envelope.from_address):
                raise CRLFInjectionError("CRLF in from address")
            if envelope.to_address and ('\r' in envelope.to_address or '\n' in envelope.to_address):
                raise CRLFInjectionError("CRLF in to address")

            if config is None:
                config = TransportConfig(
                    host=os.environ.get("ACADGRAD_SMTP_HOST", "localhost"),
                    port=int(os.environ.get("ACADGRAD_SMTP_PORT", "587")),
                    username=os.environ.get("ACADGRAD_SMTP_USERNAME", ""),
                    password=os.environ.get(SMTP_PASSWORD_ENV, ""),
                    tls_mode=TlsMode(os.environ.get("ACADGRAD_SMTP_TLS_MODE", "starttls")) if os.environ.get("ACADGRAD_SMTP_TLS_MODE") in ("starttls", "implicitTls") else TlsMode.STARTTLS,
                )

            host = config.host
            port = config.port
            username = config.username
            password = config.password or os.environ.get(SMTP_PASSWORD_ENV, "")
            tls_mode = config.tls_mode

            if tls_mode == TlsMode.IMPLICIT_TLS:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=self.timeout) as smtp:
                    smtp.login(username, password)
                    refused = smtp.send_message(message, from_addr=envelope.from_address, to_addrs=[envelope.to_address])
                    if refused:
                        recipient, code = next(iter(refused.items()))
                        raise RecipientTransportError(
                            f"Recipient refused: {code}",
                            scope="recipient",
                            retryability="permanent" if 500 <= code[0] < 600 else "transient",
                            delivery_certainty="notSent",
                            code=f"smtp-{code[0]}",
                        )
            else:
                with smtplib.SMTP(host, port, timeout=self.timeout) as smtp:
                    smtp.ehlo()
                    if not smtp.has_extn("starttls"):
                        raise BatchTransportError(
                            "Server does not support STARTTLS — refusing to send in plaintext",
                            scope="batch",
                            retryability="permanent",
                            delivery_certainty="notSent",
                            code="smtp-starttls-unavailable",
                        )
                    ctx = ssl.create_default_context()
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                    smtp.login(username, password)
                    refused = smtp.send_message(message, from_addr=envelope.from_address, to_addrs=[envelope.to_address])
                    if refused:
                        recipient, code = next(iter(refused.items()))
                        raise RecipientTransportError(
                            f"Recipient refused: {code}",
                            scope="recipient",
                            retryability="permanent" if 500 <= code[0] < 600 else "transient",
                            delivery_certainty="notSent",
                            code=f"smtp-{code[0]}",
                        )

            return TransportReceipt(
                accepted=True,
                provider_message_id=None,
                client_message_id=client_message_id,
                response_code=250,
                response_class="accepted",
            )

        except BatchTransportError:
            raise
        except RecipientTransportError:
            raise
        except smtplib.SMTPAuthenticationError as exc:
            raise BatchTransportError(
                "SMTP authentication failed",
                scope="batch",
                retryability="permanent",
                delivery_certainty="notSent",
                code="smtp-auth-failed",
            ) from exc
        except smtplib.SMTPConnectError as exc:
            raise BatchTransportError(
                "SMTP connection failed",
                scope="batch",
                retryability="transient",
                delivery_certainty="notSent",
                code="smtp-connect-failed",
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            recipients = exc.recipients
            for addr, (code, msg) in recipients.items():
                retryability = "permanent" if 500 <= code < 600 else "transient"
                raise RecipientTransportError(
                    f"Recipient refused: {code}",
                    scope="recipient",
                    retryability=retryability,
                    delivery_certainty="notSent",
                    code=f"smtp-{code}",
                ) from exc
        except smtplib.SMTPResponseException as exc:
            retryability = "permanent" if 500 <= exc.smtp_code < 600 else "transient"
            scope = "batch" if retryability == "permanent" else "batch"
            raise BatchTransportError(
                f"SMTP error: {exc.smtp_code}",
                scope=scope,
                retryability=retryability,
                delivery_certainty="notSent",
                code=f"smtp-{exc.smtp_code}",
            ) from exc
        except smtplib.SMTPServerDisconnected as exc:
            raise RecipientTransportError(
                "SMTP server disconnected",
                scope="recipient",
                retryability="transient",
                delivery_certainty="unknown",
                code="smtp-disconnected",
            ) from exc
        except TimeoutError as exc:
            raise RecipientTransportError(
                "SMTP timeout",
                scope="recipient",
                retryability="transient",
                delivery_certainty="unknown",
                code="smtp-timeout",
            ) from exc
        except OSError as exc:
            raise BatchTransportError(
                "SMTP connection error",
                scope="batch",
                retryability="transient",
                delivery_certainty="notSent",
                code="smtp-os-error",
            ) from exc


def build_email_message(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
    client_message_id: Optional[str] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    if reply_to:
        msg["Reply-To"] = reply_to
    if client_message_id:
        msg["Message-ID"] = client_message_id
    return msg
