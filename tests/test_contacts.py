import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.integrations.contacts import ContactMessagingService


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, username, password):
        self.login_values = (username, password)

    def send_message(self, message):
        self.sent.append(message)


class ContactMessagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        settings = Settings(database_path=Path(self.directory.name) / "contacts.db", smtp_host="smtp.example", smtp_from_address="nexus@example.com")
        self.service = ContactMessagingService(settings, FakeSMTP)
        self.service.initialize()
        FakeSMTP.sent.clear()

    def tearDown(self):
        self.directory.cleanup()

    def _contact(self):
        return self.service.create_contact("Ada Lovelace", "ada@example.com", "signed form", "project updates", "2026-08-28T10:00:00+00:00")

    def test_send_requires_opted_in_contact_and_records_delivery_without_body(self):
        contact = self._contact()
        preview = self.service.preview(contact["id"], "Project update", "A bounded plain-text update.")
        staged = self.service.stage(contact["id"], "Project update", "A bounded plain-text update.")
        result = self.service.send(staged["id"])

        self.assertEqual(preview["state"], "confirmation_required")
        self.assertEqual(result["state"], "delivered")
        self.assertEqual(FakeSMTP.sent[0]["To"], "ada@example.com")
        record = self.service.list_messages()[0]
        self.assertEqual(record["body_characters"], 28)
        self.assertNotIn("body", record)

    def test_opt_out_and_expired_consent_block_delivery(self):
        contact = self._contact()
        self.service.opt_out(contact["id"])
        with self.assertRaisesRegex(ValueError, "opted out"):
            self.service.preview(contact["id"], "Subject", "Message")
        expired = self.service.create_contact("Grace Hopper", "grace@example.com", "verbal", "alerts", "2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.service.preview(expired["id"], "Subject", "Message")

    def test_contact_requires_documented_consent_and_valid_email(self):
        with self.assertRaisesRegex(ValueError, "email"):
            self.service.create_contact("Ada", "not-an-email", "form", "updates", "2026-08-28T10:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "Consent source"):
            self.service.create_contact("Ada", "ada2@example.com", "", "updates", "2026-08-28T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
