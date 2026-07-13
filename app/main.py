from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from loguru import logger

from app.config import get_settings
from app.logging import configure_logging
from app.matrix_client import MatrixNotifier
from app.models import (
    delete_problem,
    get_problem_message_ident,
    init_database,
    problem_exists,
    problem_update_exists,
    save_problem_message,
    save_problem_update,
)
from app.schemas import MessageType, ZabbixNotification


_problem_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _get_problem_lock(problem_ident: str) -> asyncio.Lock:
    lock = _problem_locks.get(problem_ident)
    if lock is None:
        lock = asyncio.Lock()
        _problem_locks[problem_ident] = lock
    return lock


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_dir)
    init_database(settings.database_path)
    app.state.matrix_notifier = MatrixNotifier(settings)
    logger.info("Application started on {}:{}", settings.app_host, settings.app_port)

    try:
        yield
    finally:
        await app.state.matrix_notifier.close()
        logger.info("Application stopped")


app = FastAPI(title="Zabbix Matrix Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/zabbix", status_code=status.HTTP_202_ACCEPTED)
async def receive_zabbix_notification(
    notification: ZabbixNotification,
    request: Request,
) -> dict[str, str]:
    logger.info(
        "Received Zabbix notification: type={}, problem_ident={}",
        notification.message_type,
        notification.problem_ident,
    )

    notifier: MatrixNotifier = request.app.state.matrix_notifier

    async with _get_problem_lock(notification.problem_ident):
        if notification.message_type == MessageType.problem:
            if await problem_exists(notification.problem_ident):
                logger.warning(
                    "Duplicate problem notification ignored: problem_ident={}",
                    notification.problem_ident,
                )
                return {"status": "ignored", "reason": "duplicate_problem"}

            event_id = await notifier.send_problem(notification.subject_text, notification.body_text)
            await save_problem_message(notification.problem_ident, event_id)
            return {"status": "sent", "event_id": event_id}

        reply_to_event_id = await get_problem_message_ident(notification.problem_ident)
        if reply_to_event_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Problem '{notification.problem_ident}' was not found in the database",
            )

        if notification.message_type == MessageType.solution:
            event_id = await notifier.send_solution(
                notification.subject_text,
                notification.body_text,
                reply_to_event_id,
            )
            await delete_problem(notification.problem_ident)
            return {"status": "sent", "event_id": event_id, "reply_to_event_id": reply_to_event_id}

        if notification.event_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'event_id' is required for update notifications",
            )

        if await problem_update_exists(notification.problem_ident, notification.event_id):
            logger.warning(
                "Duplicate problem update notification ignored: problem_ident={}, event_id={}",
                notification.problem_ident,
                notification.event_id,
            )
            return {"status": "ignored", "reason": "duplicate_update"}

        event_id = await notifier.send_update(
            notification.subject_text,
            notification.body_text,
            reply_to_event_id,
        )
        await save_problem_update(notification.problem_ident, notification.event_id)
        return {"status": "sent", "event_id": event_id, "reply_to_event_id": reply_to_event_id}
