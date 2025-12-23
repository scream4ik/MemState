import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from memstate.constants import Operation


class Fact(BaseModel):
    """
    Represents a fact record with metadata and payload information.

    The class is designed to encapsulate structured information about a fact
    along with its metadata such as identification, type, source, session
    data, and timestamp. It provides a framework for creating and managing
    facts with unique identifiers and associated information.

    Attributes:
        id (str): Unique identifier for the fact.
        type (str): Type or category of the fact.
        payload (dict[str, Any]): Detailed content or data associated with the fact.
        source (str | None): Optional source identifying the origin of the fact.
        session_id (str | None): Optional session identifier associated with the fact.
        ts (datetime): Timestamp indicating when the fact was created.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    payload: dict[str, Any]
    source: str | None = None
    session_id: str | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TxEntry(BaseModel):
    """
    Represents a transaction entry with associated details, including an operation,
    sequence information, timestamps, facts, and metadata.

    This class is used to encapsulate and manage the details of a single transaction.
    It includes attributes for identifying the transaction, recording its sequence and
    timestamp, specifying the type of operation performed, and tracing any changes or
    metadata associated with the transaction.

    Attributes:
        uuid (str): Unique identifier for the transaction entry.
        session_id (str | None): Identifier of the session associated with the transaction.
        seq (int): Sequence number indicating the order of the transaction.
        ts (datetime): Timestamp indicating when the transaction occurred.
        op (Operation): Operation performed by the transaction.
        fact_id (str | None): Identifier of the fact related to the transaction.
        fact_before (dict[str, Any] | None): State of the fact before the transaction occurred.
        fact_after (dict[str, Any] | None): State of the fact after the transaction occurred.
        actor (str | None): Identifier of the actor responsible for the transaction.
        reason (str | None): Reason or justification for the transaction.
    """

    uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str | None
    seq: int
    ts: datetime
    op: Operation
    fact_id: str | None
    fact_before: dict[str, Any] | None = None
    fact_after: dict[str, Any] | None = None
    actor: str | None = None
    reason: str | None = None


class SearchResult(BaseModel):
    """
    Represents a search result with related metadata.

    This class encapsulates the result of a search operation, providing information
    about the unique identifier of the search result and its associated score.

    Attributes:
        fact_id (str): Unique identifier for the search result.
        score (float): Relevance score of the search result.
    """

    fact_id: str
    score: float


class ScoredFact(BaseModel):
    """
    Represents a scored fact model.

    This class is used to associate a fact with a corresponding
    score, which indicates the relevance or significance of the fact
    in a given context.

    Attributes:
        fact (Fact): The fact associated with the score.
        score (float): The significance or relevance score for the fact.
    """

    fact: Fact
    score: float
