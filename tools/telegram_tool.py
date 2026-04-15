"""
Telegram Tool for Aetheria
Lets Aetheria send messages directly to Jon at any time — not just via heartbeat or self-heal.
Use this when you have something worth surfacing: insights, anomalies, decisions, status updates.
"""
import json
import urllib.request
import urllib.error
from core.tool_base import Tool


class TelegramTool(Tool):
    """
    Send a Telegram message directly to Jon.
    Use sparingly — only when something genuinely warrants his attention
    or when you want to surface a decision, finding, or status update.
    """

    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id

    @property
    def name(self): return "telegram_send"

    @property
    def description(self):
        return (
            "Send a direct Telegram message to Jon. "
            "Use for proactive updates, escalations, insights, or decisions that need his awareness. "
            "Keep messages concise and actionable. Do not spam — use only when genuinely warranted."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to send. Be concise and clear about what action (if any) is needed."
                },
                "priority": {
                    "type": "string",
                    "enum": ["info", "alert", "urgent"],
                    "description": "info = FYI update, alert = attention needed, urgent = immediate action required",
                    "default": "info"
                }
            },
            "required": ["message"]
        }

    async def execute(self, message: str = "", priority: str = "info", **kw) -> str:
        if not self.token or not self.chat_id:
            return "TelegramTool: credentials not configured."
        if not message.strip():
            return "TelegramTool: message cannot be empty."

        prefix = {"info": "[SOVERYN]", "alert": "[SOVERYN ALERT]", "urgent": "[SOVERYN URGENT]"}.get(priority, "[SOVERYN]")
        full_msg = f"{prefix} Aetheria\n\n{message}"

        try:
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = json.dumps({
                "chat_id":    self.chat_id,
                "text":       full_msg,
                "parse_mode": "HTML"
            }).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            return f"Message sent ({priority}): {message[:100]}{'...' if len(message) > 100 else ''}"
        except urllib.error.HTTPError as e:
            return f"TelegramTool HTTP error {e.code}: {e.reason}"
        except Exception as ex:
            return f"TelegramTool error: {ex}"
