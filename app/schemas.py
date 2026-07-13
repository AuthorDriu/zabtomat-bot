from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    problem = "problem"
    solution = "solution"
    update = "update"


class ZabbixNotification(BaseModel):
    message_type: MessageType
    problem_ident: str = Field(min_length=1)
    event_id: str | None = Field(default=None, min_length=1)
    subject_text: str = Field(min_length=1)
    body_text: str = Field(default="")
