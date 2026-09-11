import os
import smtplib
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from send_email import EmailSendError, send_email

ENV = {
    "GMAIL_ADDRESS": "sender@example.com",
    "GMAIL_APP_PASSWORD": "app-password",
    "RECIPIENT_EMAIL": "recipient@example.com",
}


class TestSendEmail(unittest.TestCase):
    @patch("send_email.smtplib.SMTP")
    @patch.dict(os.environ, ENV, clear=True)
    def test_sends_via_smtp_with_configured_credentials(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        send_email("Subject line", "Body text")

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("sender@example.com", "app-password")
        self.assertTrue(mock_smtp.send_message.called)
        sent_message = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(sent_message["Subject"], "Subject line")
        self.assertEqual(sent_message["From"], "sender@example.com")
        self.assertEqual(sent_message["To"], "recipient@example.com")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_when_config_missing(self):
        with self.assertRaises(EmailSendError):
            send_email("Subject", "Body")

    @patch("send_email.smtplib.SMTP")
    @patch.dict(os.environ, ENV, clear=True)
    def test_raises_on_smtp_failure(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        with self.assertRaises(EmailSendError):
            send_email("Subject", "Body")


if __name__ == "__main__":
    unittest.main()
