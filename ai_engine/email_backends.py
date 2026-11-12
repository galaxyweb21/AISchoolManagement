"""HTTP email backend for Render-safe transactional email.

Render Free blocks outbound SMTP ports.  This backend sends Django EmailMessage
objects through Brevo's HTTPS API instead, while allowing the normal Django
console backend to be used for offline development.
"""

import base64
import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address

logger = logging.getLogger(__name__)


class BrevoEmailBackend(BaseEmailBackend):
    """Django email backend using Brevo's REST API over HTTPS."""

    api_url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, "BREVO_API_KEY", "")
        self.sender_email = getattr(
            settings,
            "BREVO_SENDER_EMAIL",
            getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        )
        self.sender_name = getattr(settings, "BREVO_SENDER_NAME", "EduAI School Management")
        self.timeout = max(5, int(getattr(settings, "EMAIL_API_TIMEOUT", 20)))
        self.api_url = getattr(settings, "BREVO_API_URL", self.api_url)
        self.session = None

    def _raise_or_return(self, exc):
        if self.fail_silently:
            logger.exception("Email API delivery failed: %s", exc)
            return False
        raise exc

    def open(self):
        """Verify that the HTTPS API credentials are usable."""
        if not self.api_key:
            return self._raise_or_return(
                RuntimeError("BREVO_API_KEY is not configured.")
            )

        try:
            self.session = requests.Session()
            response = self.session.get(
                "https://api.brevo.com/v3/account",
                headers={"api-key": self.api_key, "accept": "application/json"},
                timeout=self.timeout,
            )
            if not response.ok:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Brevo API authentication failed ({response.status_code}): {detail}"
                )
            return True
        except Exception as exc:
            self.session = None
            return self._raise_or_return(exc)

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    @staticmethod
    def _recipient_list(message):
        recipients = []
        for address in message.to or []:
            recipients.append({"email": sanitize_address(address, message.encoding)})
        return recipients

    @staticmethod
    def _address(address, encoding="utf-8"):
        return sanitize_address(address, encoding)

    @staticmethod
    def _attachment_data(attachment):
        if isinstance(attachment, tuple) and len(attachment) == 3:
            filename, content, mimetype = attachment
            if hasattr(content, "read"):
                content = content.read()
            if isinstance(content, str):
                content = content.encode("utf-8")
            return {
                "name": filename,
                "content": base64.b64encode(bytes(content)).decode("ascii"),
            }

        # MIMEBase / email.message.Message attachment.
        payload = attachment.get_payload(decode=True)
        filename = attachment.get_filename() or "attachment"
        if payload is None:
            raise ValueError(f"Could not read attachment {filename!r}.")
        return {
            "name": filename,
            "content": base64.b64encode(payload).decode("ascii"),
        }

    def _build_payload(self, message):
        sender = message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        sender = self._address(sender, message.encoding)
        sender_obj = {"email": sender}
        if self.sender_name:
            sender_obj["name"] = self.sender_name

        payload = {
            "sender": sender_obj,
            "to": self._recipient_list(message),
            "subject": message.subject or "",
            "textContent": message.body or "",
        }

        if getattr(message, "alternatives", None):
            for alternative in message.alternatives:
                content = getattr(alternative, "content", None)
                mimetype = getattr(alternative, "mimetype", None)
                if isinstance(alternative, tuple):
                    content, mimetype = alternative[0], alternative[1]
                if mimetype == "text/html":
                    payload.pop("textContent", None)
                    payload["htmlContent"] = content
                    break

        reply_to = getattr(message, "reply_to", None) or []
        if reply_to:
            payload["replyTo"] = {"email": self._address(reply_to[0], message.encoding)}

        if getattr(message, "cc", None):
            payload["cc"] = [
                {"email": self._address(address, message.encoding)}
                for address in message.cc
            ]
        if getattr(message, "bcc", None):
            payload["bcc"] = [
                {"email": self._address(address, message.encoding)}
                for address in message.bcc
            ]

        attachments = getattr(message, "attachments", None) or []
        if attachments:
            payload["attachment"] = [self._attachment_data(item) for item in attachments]

        return payload

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if self.session is None and not self.open():
            return 0

        sent = 0
        try:
            for message in email_messages:
                if not message.recipients():
                    continue
                payload = self._build_payload(message)
                response = self.session.post(
                    self.api_url,
                    headers={
                        "api-key": self.api_key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                if not response.ok:
                    detail = response.text[:1000]
                    raise RuntimeError(
                        f"Brevo email request failed ({response.status_code}): {detail}"
                    )
                sent += 1
            return sent
        except Exception as exc:
            return self._raise_or_return(exc) or 0
        finally:
            self.close()
