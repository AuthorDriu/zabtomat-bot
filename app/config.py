from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    matrix_homeserver: str = Field(..., alias="MATRIX_HOMESERVER")
    matrix_room_id: str = Field(..., alias="MATRIX_ROOM_ID")
    matrix_access_token: str = Field(..., alias="MATRIX_ACCESS_TOKEN")

    app_host: str = Field("127.0.0.1", alias="APP_HOST")
    app_port: int = Field(10061, alias="APP_PORT")
    database_path: Path = Field(Path("./database/database.sqlite3"), alias="DATABASE_PATH")
    log_dir: Path = Field(Path("./logs"), alias="LOG_DIR")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
