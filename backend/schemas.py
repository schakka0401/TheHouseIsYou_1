from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GameSessionCreate(BaseModel):
    player_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )


class GameSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_name: str | None
    total_score: int
    final_analysis: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class GameResultCreate(BaseModel):
    game_name: str = Field(
        min_length=1,
        max_length=80,
    )

    input_data: dict[str, Any]
    result_data: dict[str, Any]

    score_change: int = 0

    duration_ms: int | None = Field(
        default=None,
        ge=0,
    )


class GameResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    game_name: str
    input_data: dict[str, Any]
    result_data: dict[str, Any]
    score_change: int
    duration_ms: int | None
    created_at: datetime