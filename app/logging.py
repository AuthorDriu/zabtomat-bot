from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from loguru import logger


def _archive_rotated_log(file_path: str) -> None:
    """Add a rotated log file to logs.zip without overwriting existing archive entries."""
    log_path = Path(file_path)
    archive_path = log_path.parent.parent / "logs.zip"

    if not log_path.exists():
        return

    archive_name = f"{log_path.parent.name}/{log_path.name}"

    with ZipFile(archive_path, mode="a", compression=ZIP_DEFLATED) as archive:
        archive.write(log_path, arcname=archive_name)

    log_path.unlink(missing_ok=True)


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        log_dir / "bot_{time:DD-MM-YY_HH-mm-ss}.log",
        rotation="00:00",
        compression=_archive_rotated_log,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
    )

    logger.info("Logging configured: directory={}", log_dir)
