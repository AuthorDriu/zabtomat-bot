from __future__ import annotations

from pathlib import Path

import peewee
import peewee_async
from loguru import logger


database: peewee_async.SqliteDatabase | None = None


class BaseModel(peewee_async.AioModel):
    class Meta:
        database = None


class Problem(BaseModel):
    problem_ident = peewee.TextField(primary_key=True)
    message_ident = peewee.TextField(null=False)

    class Meta:
        table_name = "problems"


class ProblemUpdate(BaseModel):
    problem_ident = peewee.TextField(null=False)
    event_id = peewee.TextField(null=False)

    class Meta:
        table_name = "problem_updates"
        primary_key = peewee.CompositeKey("problem_ident", "event_id")


def init_database(database_path: Path) -> None:
    global database

    logger.info("Initializing SQLite database: {}", database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    database = peewee_async.SqliteDatabase(str(database_path))
    BaseModel._meta.database = database
    Problem._meta.database = database
    ProblemUpdate._meta.database = database

    with database.allow_sync():
        database.create_tables([Problem, ProblemUpdate], safe=True)

    database.set_allow_sync(False)
    logger.info("Database is ready")


async def save_problem_message(problem_ident: str, message_ident: str) -> None:
    logger.info("Saving problem mapping: problem_ident={}, message_ident={}", problem_ident, message_ident)
    await Problem.replace(problem_ident=problem_ident, message_ident=message_ident).aio_execute()


async def problem_exists(problem_ident: str) -> bool:
    logger.info("Checking stored problem mapping: problem_ident={}", problem_ident)
    try:
        await Problem.aio_get(Problem.problem_ident == problem_ident)
    except Problem.DoesNotExist:
        return False

    return True


async def get_problem_message_ident(problem_ident: str) -> str | None:
    logger.info("Looking for stored Matrix event for problem_ident={}", problem_ident)
    try:
        problem = await Problem.aio_get(Problem.problem_ident == problem_ident)
    except Problem.DoesNotExist:
        logger.warning("Stored Matrix event was not found for problem_ident={}", problem_ident)
        return None

    return problem.message_ident


async def delete_problem(problem_ident: str) -> None:
    logger.info("Deleting problem mappings: problem_ident={}", problem_ident)
    await ProblemUpdate.delete().where(ProblemUpdate.problem_ident == problem_ident).aio_execute()
    await Problem.delete().where(Problem.problem_ident == problem_ident).aio_execute()


async def save_problem_update(problem_ident: str, event_id: str) -> None:
    logger.info("Saving problem update mapping: problem_ident={}, event_id={}", problem_ident, event_id)
    await ProblemUpdate.create(problem_ident=problem_ident, event_id=event_id).aio_execute()


async def problem_update_exists(problem_ident: str, event_id: str) -> bool:
    logger.info("Checking stored problem update mapping: problem_ident={}, event_id={}", problem_ident, event_id)
    try:
        await ProblemUpdate.aio_get(
            (ProblemUpdate.problem_ident == problem_ident) & (ProblemUpdate.event_id == event_id)
        )
    except ProblemUpdate.DoesNotExist:
        return False

    return True
