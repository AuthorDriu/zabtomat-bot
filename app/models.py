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


def init_database(database_path: Path) -> None:
    global database

    logger.info("Initializing SQLite database: {}", database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    database = peewee_async.SqliteDatabase(str(database_path))
    BaseModel._meta.database = database
    Problem._meta.database = database

    with database.allow_sync():
        database.create_tables([Problem], safe=True)

    database.set_allow_sync(False)
    logger.info("Database is ready")


async def save_problem_message(problem_ident: str, message_ident: str) -> None:
    logger.info("Saving problem mapping: problem_ident={}, message_ident={}", problem_ident, message_ident)
    await Problem.replace(problem_ident=problem_ident, message_ident=message_ident).aio_execute()


async def get_problem_message_ident(problem_ident: str) -> str | None:
    logger.info("Looking for stored Matrix event for problem_ident={}", problem_ident)
    try:
        problem = await Problem.aio_get(Problem.problem_ident == problem_ident)
    except Problem.DoesNotExist:
        logger.warning("Stored Matrix event was not found for problem_ident={}", problem_ident)
        return None

    return problem.message_ident


async def delete_problem(problem_ident: str) -> None:
    logger.info("Deleting problem mapping: problem_ident={}", problem_ident)
    await Problem.delete().where(Problem.problem_ident == problem_ident).aio_execute()
