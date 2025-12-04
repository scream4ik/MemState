import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from memstate.constants import Operation


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    payload: dict[str, Any]
    source: str | None = None
    session_id: str | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TxEntry(BaseModel):
    uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seq: int
    ts: datetime
    op: Operation
    fact_id: str | None
    fact_before: dict[str, Any] | None = None
    fact_after: dict[str, Any] | None = None
    actor: str | None = None
    reason: str | None = None
