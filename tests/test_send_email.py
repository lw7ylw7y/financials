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

    @patch("send_email.smtplib.SMTP")
    @patch.dict(os.environ, ENV, clear=True)
    def test_sends_multipart_alternative_when_html_body_given(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        send_email("Subject line", "Plain text body", html_body="<p>Styled body</p>")

        sent_message = mock_smtp.send_message.call_args[0][0]
        self.assertTrue(sent_message.is_multipart())
        plain_part = sent_message.get_body(preferencelist=("plain",))
        html_part = sent_message.get_body(preferencelist=("html",))
        self.assertIn("Plain text body", plain_part.get_content())
        self.assertIn("<p>Styled body</p>", html_part.get_content())

    @patch("send_email.smtplib.SMTP")
    @patch.dict(os.environ, ENV, clear=True)
    def test_embeds_images_with_matching_content_id(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        fake_png = b"\x89PNG\r\n\x1a\n" + b"0" * 20

        send_email(
            "Subject line",
            "Plain text body",
            html_body='<img src="cid:spark-cpi">',
            images={"spark-cpi": fake_png},
        )

        sent_message = mock_smtp.send_message.call_args[0][0]
        image_parts = [p for p in sent_message.walk() if p.get_content_type() == "image/png"]
        self.assertEqual(len(image_parts), 1)
        self.assertEqual(image_parts[0]["Content-ID"], "<spark-cpi>")
        self.assertEqual(image_parts[0].get_payload(decode=True), fake_png)

    @patch("send_email.smtplib.SMTP")
    @patch.dict(os.environ, ENV, clear=True)
    def test_images_without_html_body_are_ignored(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        send_email("Subject", "Plain text only", images={"spark-cpi": b"ignored"})

        sent_message = mock_smtp.send_message.call_args[0][0]
        self.assertFalse(sent_message.is_multipart())

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
