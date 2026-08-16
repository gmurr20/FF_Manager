"""Email delivery backends implementing the EmailClient interface."""

import logging
import os
from typing import List, Optional, Union

import resend
import resend.exceptions

from ff_manager.interfaces import EmailClient

logger = logging.getLogger(__name__)


class ResendEmailClient(EmailClient):
    """Email delivery backend using the official Resend Python SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_from: Optional[str] = None,
    ):
        """
        Initialize the Resend email client.

        Args:
            api_key: Resend API key (e.g. 're_123456789'). If omitted, loaded from RESEND_API_KEY env var.
            default_from: Default sender email address. If omitted, loaded from NOTIFICATION_EMAIL_FROM
                          or RESEND_FROM_EMAIL (defaults to 'onboarding@resend.dev').
        """
        self.api_key = api_key or os.environ.get("RESEND_API_KEY")
        self.default_from = (
            default_from
            or os.environ.get("NOTIFICATION_EMAIL_FROM")
            or os.environ.get("RESEND_FROM_EMAIL")
            or "onboarding@resend.dev"
        )
        if self.api_key:
            resend.api_key = self.api_key

    @property
    def is_configured(self) -> bool:
        """Check if Resend API key is present."""
        return bool(self.api_key)

    def send_email(
        self,
        to: Union[str, List[str]],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """
        Send an email via the Resend API using resend.Emails.send().

        Args:
            to: Recipient email address or list of addresses.
            subject: Email subject line.
            html_content: Rendered HTML body.
            text_content: Optional plain-text body fallback.
            from_email: Optional sender address override.

        Returns:
            True if email was dispatched successfully, False otherwise.
        """
        if not self.is_configured:
            logger.warning("RESEND_API_KEY is not configured. Email delivery skipped.")
            return False

        # Ensure API key is set on the resend module
        resend.api_key = self.api_key

        sender = from_email or self.default_from
        recipients = [to] if isinstance(to, str) else list(to)

        params: resend.Emails.SendParams = {
            "from": sender,
            "to": recipients,
            "subject": subject,
            "html": html_content,
        }
        if text_content:
            params["text"] = text_content

        try:
            logger.info(f"Sending email via Resend API to {recipients} (From: {sender})...")
            response = resend.Emails.send(params)
            email_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", str(response))
            logger.info(f"✅ Email successfully dispatched via Resend (ID: {email_id}).")
            return True
        except resend.exceptions.ResendError as e:
            logger.error(f"Resend API error sending email to {recipients}: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error during Resend email delivery: {e}", exc_info=True)
            return False
