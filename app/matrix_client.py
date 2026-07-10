from __future__ import annotations

import html

from loguru import logger
from nio import AsyncClient, RoomSendError, RoomSendResponse

from app.config import Settings


class MatrixNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncClient(settings.matrix_homeserver)
        self._client.access_token = settings.matrix_access_token

    async def close(self) -> None:
        logger.info("Closing Matrix client")
        await self._client.close()

    async def send_problem(self, subject: str, body: str) -> str:
        logger.info("Sending problem notification to Matrix room {}", self._settings.matrix_room_id)
        response = await self._send_message(subject, body)
        logger.info("Problem notification sent: event_id={}", response.event_id)
        return response.event_id

    async def send_solution(self, subject: str, body: str, thread_root_event_id: str) -> str:
        logger.info(
            "Sending solution notification to Matrix room {} in thread {}",
            self._settings.matrix_room_id,
            thread_root_event_id,
        )
        response = await self._send_message(subject, body, thread_root_event_id=thread_root_event_id)
        logger.info("Solution notification sent: event_id={}", response.event_id)
        return response.event_id

    async def _send_message(
        self,
        subject: str,
        body: str,
        thread_root_event_id: str | None = None,
    ) -> RoomSendResponse:
        content = self._build_content(subject, body, thread_root_event_id)
        response = await self._client.room_send(
            room_id=self._settings.matrix_room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendError):
            logger.error("Matrix message was not sent: {}", response)
            raise RuntimeError(f"Matrix message was not sent: {response.message}")

        return response

    @staticmethod
    def _build_content(subject: str, body: str, thread_root_event_id: str | None) -> dict:
        plain_body = _format_plain_message(subject, body)
        formatted_body = _format_html_message(subject, body)

        content: dict = {
            "msgtype": "m.text",
            "body": plain_body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted_body,
        }

        if thread_root_event_id is not None:
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": thread_root_event_id,
                "is_falling_back": True,
                "m.in_reply_to": {
                    "event_id": thread_root_event_id,
                },
            }

        return content


def _format_plain_message(subject: str, body: str) -> str:
    return f"#### {subject}\n```\n{body}\n```"


def _format_html_message(subject: str, body: str) -> str:
    return f"<h4>{html.escape(subject)}</h4><pre><code>{html.escape(body)}</code></pre>"
