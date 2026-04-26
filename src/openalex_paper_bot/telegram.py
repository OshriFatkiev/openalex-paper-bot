"""Send digest messages through the Telegram Bot API.

This module provides the minimal HTTP client needed to deliver digest messages
reliably, including retry handling for transient Telegram API failures.
"""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://api.telegram.org"


class TelegramClient:
    """Small Telegram client with one ``send_message`` method."""

    def __init__(self, bot_token: str, chat_id: str, *, timeout: float = 20.0) -> None:
        """Initialize a Telegram client.

        Args:
            bot_token: Telegram bot token.
            chat_id: Destination chat ID.
            timeout: Request timeout in seconds.

        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def __enter__(self) -> TelegramClient:
        """Return the client for ``with`` statement usage."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the underlying HTTP client when leaving a context manager."""
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def send_message(self, text: str, *, parse_mode: str | None = None) -> None:
        """Send a Telegram message to the configured chat.

        Args:
            text: Message body to deliver.
            parse_mode: Optional Telegram parse mode such as ``Markdown``.

        Raises:
            ValueError: If the message text is empty.
            RuntimeError: If the Telegram API request fails after retries.

        """
        if not text.strip():
            raise ValueError("Telegram message text cannot be empty.")

        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.post(f"/bot{self.bot_token}/sendMessage", json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue
                response.raise_for_status()
                body = response.json()
                if not body.get("ok", False):
                    raise RuntimeError(body.get("description") or "Telegram API returned ok=false.")
                return
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue
        raise RuntimeError(f"Telegram sendMessage failed: {last_error}") from last_error
