"""Consent-bound contact records and a deliberately narrow SMTP email sender."""
from __future__ import annotations

import re
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Callable

from backend.app.core.config import Settings, get_settings
from backend.app.database import database_connection


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_NAME = 100
MAX_SUBJECT = 160
MAX_BODY = 5000


class ContactMessagingService:
    def __init__(self, settings: Settings, smtp_factory: Callable[..., Any] | None = None):
        self.settings = settings
        self.smtp_factory = smtp_factory or smtplib.SMTP

    def _connection(self):
        return database_connection(self.settings.database_path, self.settings.database_url)

    def initialize(self):
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    consent_source TEXT NOT NULL, consent_subject TEXT NOT NULL,
                    consented_at TEXT NOT NULL, consent_expires_at TEXT,
                    consent_state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contact_messages (
                    id TEXT PRIMARY KEY, contact_id TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, body_characters INTEGER NOT NULL, state TEXT NOT NULL,
                    provider TEXT NOT NULL, created_at TEXT NOT NULL, delivered_at TEXT,
                    error TEXT, FOREIGN KEY(contact_id) REFERENCES contacts(id)
                );
            """)
            if connection.dialect == "sqlite":
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(contact_messages)").fetchall()}
                if "body" not in columns:
                    connection.execute("ALTER TABLE contact_messages ADD COLUMN body TEXT NOT NULL DEFAULT ''")
            else:
                connection.execute("ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _required(value: str, label: str, maximum: int) -> str:
        value = value.strip()
        if not value or len(value) > maximum:
            raise ValueError(f"{label} must be 1-{maximum} characters")
        return value

    @staticmethod
    def _timestamp(value: str | None, label: str) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError(f"{label} must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat()

    def create_contact(self, name: str, email: str, consent_source: str, consent_subject: str, consented_at: str, consent_expires_at: str | None = None) -> dict:
        name = self._required(name, "Contact name", MAX_NAME)
        email = email.strip().lower()
        if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            raise ValueError("Contact email must be a valid address")
        source = self._required(consent_source, "Consent source", 200)
        subject = self._required(consent_subject, "Consent subject", 300)
        consented = self._timestamp(consented_at, "Consent timestamp")
        expires = self._timestamp(consent_expires_at, "Consent expiry")
        if expires and expires <= consented:
            raise ValueError("Consent expiry must be after the consent timestamp")
        now = datetime.now(timezone.utc).isoformat()
        contact_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute("""INSERT INTO contacts
                (id, name, email, consent_source, consent_subject, consented_at, consent_expires_at, consent_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'opted_in', ?, ?)""", (contact_id, name, email, source, subject, consented, expires, now, now))
        return self.get_contact(contact_id) or {}

    def list_contacts(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE, created_at DESC").fetchall()
        return [self._decode(row) for row in rows]

    def get_contact(self, contact_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return self._decode(row) if row else None

    def opt_out(self, contact_id: str) -> dict:
        contact = self.get_contact(contact_id)
        if not contact:
            raise ValueError("Contact not found")
        with self._connection() as connection:
            connection.execute("UPDATE contacts SET consent_state = 'opted_out', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), contact_id))
        return self.get_contact(contact_id) or {}

    def preview(self, contact_id: str, subject: str, body: str) -> dict:
        contact = self._sendable_contact(contact_id)
        subject = self._required(subject, "Email subject", MAX_SUBJECT)
        body = self._required(body, "Email body", MAX_BODY)
        if "\x00" in subject or "\x00" in body or "\r" in subject or "\n" in subject:
            raise ValueError("Email content contains unsupported control characters")
        return {"state": "confirmation_required", "contact": {"id": contact["id"], "name": contact["name"], "email": contact["email"]}, "provider": "smtp", "subject": subject, "body_characters": len(body), "consent": {"source": contact["consent_source"], "subject": contact["consent_subject"], "consented_at": contact["consented_at"], "expires_at": contact["consent_expires_at"]}}

    def stage(self, contact_id: str, subject: str, body: str) -> dict:
        preview = self.preview(contact_id, subject, body)
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("INSERT INTO contact_messages (id, contact_id, subject, body, body_characters, state, provider, created_at) VALUES (?, ?, ?, ?, ?, 'awaiting_approval', 'smtp', ?)", (message_id, contact_id, subject, body, len(body), now))
        return {"id": message_id, **preview}

    def send(self, message_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM contact_messages WHERE id = ?", (message_id,)).fetchone()
        if not row or row["state"] != "awaiting_approval":
            raise ValueError("Message is unavailable for delivery")
        contact_id, subject, body = row["contact_id"], row["subject"], row["body"]
        preview = self.preview(contact_id, subject, body)
        if not self.settings.smtp_host or not self.settings.smtp_from_address:
            raise RuntimeError("SMTP is not configured")
        with self._connection() as connection:
            connection.execute("UPDATE contact_messages SET state = 'sending' WHERE id = ?", (message_id,))
        email = EmailMessage()
        email["From"] = self.settings.smtp_from_address
        email["To"] = preview["contact"]["email"]
        email["Subject"] = subject
        email.set_content(body)
        try:
            with self.smtp_factory(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
                client.ehlo()
                if self.settings.smtp_starttls:
                    client.starttls()
                    client.ehlo()
                if self.settings.smtp_username:
                    client.login(self.settings.smtp_username, self.settings.smtp_password or "")
                client.send_message(email)
        except (OSError, smtplib.SMTPException) as error:
            with self._connection() as connection:
                connection.execute("UPDATE contact_messages SET state = 'failed', error = ? WHERE id = ?", (str(error)[:500], message_id))
            raise RuntimeError("SMTP delivery failed") from error
        delivered = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("UPDATE contact_messages SET state = 'delivered', delivered_at = ? WHERE id = ?", (delivered, message_id))
        return {"id": message_id, "state": "delivered", "provider": "smtp", "contact_id": contact_id, "delivered_at": delivered}

    def list_messages(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, contact_id, subject, body_characters, state, provider, created_at, delivered_at, error FROM contact_messages ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [self._decode(row) for row in rows]

    def _sendable_contact(self, contact_id: str) -> dict:
        contact = self.get_contact(contact_id)
        if not contact:
            raise ValueError("Contact not found")
        if contact["consent_state"] != "opted_in":
            raise ValueError("Contact has opted out")
        expiry = contact["consent_expires_at"]
        if expiry and expiry <= datetime.now(timezone.utc).isoformat():
            raise ValueError("Contact consent has expired")
        return contact

    @staticmethod
    def _decode(row) -> dict:
        return dict(row)


contact_messaging_service = ContactMessagingService(get_settings())


def send_confirmed_email(message_id: str) -> dict:
    return contact_messaging_service.send(message_id)
