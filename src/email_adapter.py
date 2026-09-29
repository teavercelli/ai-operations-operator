"""Provider-neutral email adapters with safe simulation and live modes.

The workflow depends only on ``EmailAdapter``.  SMTP is the first live
implementation because it is provider-neutral and uses Python's standard
library; credentials are read only from environment variables.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Protocol
from uuid import uuid4


EMAIL_MODES = frozenset({"simulation", "dry-run", "live"})
EMAIL_RECIPIENT_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default).lower()).strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class EmailActionConfig:
    """Runtime email configuration; never serializes the SMTP password."""

    mode: str = "simulation"
    external_actions_enabled: bool = False
    recipient: str | None = None
    sender: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        normalized = self.mode.strip().lower().replace("_", "-")
        if normalized not in EMAIL_MODES:
            raise ValueError(f"Unsupported email mode: {self.mode}")
        object.__setattr__(self, "mode", normalized)
        if self.smtp_port < 1 or self.smtp_port > 65535:
            raise ValueError("smtp_port must be between 1 and 65535")

    @classmethod
    def from_env(cls) -> "EmailActionConfig":
        return cls(
            mode=os.getenv("AI_OPERATOR_EMAIL_MODE", "simulation"),
            external_actions_enabled=_env_bool("AI_OPERATOR_EXTERNAL_ACTIONS_ENABLED", False),
            recipient=os.getenv("AI_OPERATOR_EMAIL_RECIPIENT") or None,
            sender=os.getenv("AI_OPERATOR_EMAIL_FROM") or None,
            smtp_host=os.getenv("SMTP_HOST") or None,
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME") or None,
            smtp_password=os.getenv("SMTP_PASSWORD") or None,
            smtp_starttls=_env_bool("SMTP_STARTTLS", True),
            smtp_timeout_seconds=float(os.getenv("SMTP_TIMEOUT_SECONDS", "20")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "external_actions_enabled": self.external_actions_enabled,
            "recipient_configured": bool(self.recipient),
            "sender_configured": bool(self.sender),
            "smtp_host_configured": bool(self.smtp_host),
            "smtp_port": self.smtp_port,
            "smtp_username_configured": bool(self.smtp_username),
            "smtp_starttls": self.smtp_starttls,
        }


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    simulated: bool
    provider: str
    timestamp: str
    message_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "simulated": self.simulated,
            "provider": self.provider,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "error": self.error,
        }


class EmailAdapter(Protocol):
    provider: str
    default_recipient: str | None

    def send(self, *, recipient: str, subject: str, body: str) -> EmailSendResult:
        """Send one message and return a safe, non-secret result."""


def validate_customer_message(message: object) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("customer_message is required for contact_customer")
    if len(message) > 10_000:
        raise ValueError("customer_message exceeds the 10000 character limit")
    return message.strip()


def validate_email_recipient(recipient: object) -> str:
    if not isinstance(recipient, str) or not EMAIL_RECIPIENT_PATTERN.fullmatch(recipient.strip()):
        raise ValueError(
            "A valid recipient email is required; the Olist dataset has no customer email field"
        )
    return recipient.strip()


class DryRunEmailAdapter:
    provider = "dry_run"

    def __init__(self, default_recipient: str | None = None):
        self.default_recipient = default_recipient

    def send(self, *, recipient: str, subject: str, body: str) -> EmailSendResult:
        return EmailSendResult(
            success=True,
            simulated=True,
            provider=self.provider,
            timestamp=_now(),
            message_id=f"dry-run-{uuid4().hex[:12]}",
        )


class BlockedEmailAdapter:
    provider = "blocked"

    def __init__(self, reason: str, default_recipient: str | None = None):
        self.reason = reason
        self.default_recipient = default_recipient

    def send(self, *, recipient: str, subject: str, body: str) -> EmailSendResult:
        return EmailSendResult(
            success=False,
            simulated=True,
            provider=self.provider,
            timestamp=_now(),
            error=self.reason,
        )


class SMTPEmailAdapter:
    provider = "smtp"

    def __init__(self, config: EmailActionConfig):
        self.default_recipient = config.recipient
        self._config = config
        missing = [
            name
            for name, value in {
                "SMTP_HOST": config.smtp_host,
                "AI_OPERATOR_EMAIL_FROM": config.sender,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Live SMTP email requires configuration: {', '.join(missing)}")
        if config.smtp_username and not config.smtp_password:
            raise ValueError("SMTP_PASSWORD is required when SMTP_USERNAME is configured")

    def send(self, *, recipient: str, subject: str, body: str) -> EmailSendResult:
        timestamp = _now()
        message = EmailMessage()
        message["From"] = self._config.sender  # type: ignore[index]
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(
                self._config.smtp_host,  # type: ignore[arg-type]
                self._config.smtp_port,
                timeout=self._config.smtp_timeout_seconds,
            ) as connection:
                if self._config.smtp_starttls:
                    connection.starttls(context=ssl.create_default_context())
                if self._config.smtp_username:
                    connection.login(self._config.smtp_username, self._config.smtp_password or "")
                connection.send_message(message)
        except Exception as error:
            return EmailSendResult(
                success=False,
                simulated=False,
                provider=self.provider,
                timestamp=timestamp,
                error=f"{type(error).__name__}: {error}",
            )
        return EmailSendResult(
            success=True,
            simulated=False,
            provider=self.provider,
            timestamp=timestamp,
            message_id=message.get("Message-ID"),
        )


def build_email_adapter(config: EmailActionConfig | None = None) -> EmailAdapter:
    config = config or EmailActionConfig.from_env()
    if config.mode in {"simulation", "dry-run"}:
        return DryRunEmailAdapter(default_recipient=config.recipient)
    if not config.external_actions_enabled:
        return BlockedEmailAdapter(
            "Real external actions are disabled by AI_OPERATOR_EXTERNAL_ACTIONS_ENABLED",
            default_recipient=config.recipient,
        )
    return SMTPEmailAdapter(config)
