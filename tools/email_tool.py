"""
email_tool.py
Scout's outreach tool — sends emails via Gmail SMTP.
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.tool_base import Tool
from typing import Any, Dict


def _load_credentials():
    # Load from .env if python-dotenv available, else fall back to os.environ
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    except ImportError:
        pass
    email = os.environ.get('SCOUT_EMAIL', '')
    password = os.environ.get('SCOUT_EMAIL_PASSWORD', '')
    return email, password


class EmailTool(Tool):
    """Send an email from Scout's recruiting account."""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return (
            "Send a recruiting or marketing email. "
            "Use for outreach to potential Graceland portable building dealers. "
            "Always verify the recipient email is real before sending."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text)"
                },
                "recipient_name": {
                    "type": "string",
                    "description": "Recipient name for logging (optional)"
                }
            },
            "required": ["to", "subject", "body"]
        }

    async def execute(self, to: str, subject: str, body: str,
                      recipient_name: str = "", **kwargs) -> str:
        sender, password = _load_credentials()
        if not sender or not password:
            return "ERROR: Scout email credentials not configured."

        try:
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = to
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(sender, password)
                server.sendmail(sender, to, msg.as_string())

            log_name = recipient_name or to
            print(f"[Scout] Email sent to {log_name} <{to}>")
            return f"Email sent successfully to {log_name} <{to}>."

        except smtplib.SMTPAuthenticationError:
            return "ERROR: Gmail authentication failed. Check app password."
        except smtplib.SMTPRecipientsRefused:
            return f"ERROR: Recipient address rejected: {to}"
        except Exception as e:
            return f"ERROR sending email: {e}"
