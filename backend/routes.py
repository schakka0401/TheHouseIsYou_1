from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_database_session
from backend.models import GameResult, GameSession
from backend.schemas import (
    GameResultCreate,
    GameResultResponse,
    GameSessionCreate,
    GameSessionResponse,
)


router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
)


@router.post(
    "",
    response_model=GameSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    session_data: GameSessionCreate,
    database: Session = Depends(get_database_session),
):
    game_session = GameSession(
        player_name=session_data.player_name,
    )

    database.add(game_session)
    database.commit()
    database.refresh(game_session)

    return game_session


@router.get(
    "/{session_id}",
    response_model=GameSessionResponse,
)
def get_session(
    session_id: UUID,
    database: Session = Depends(get_database_session),
):
    game_session = database.get(GameSession, session_id)

    if game_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game session not found",
        )

    return game_session


@router.post(
    "/{session_id}/results",
    response_model=GameResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_result(
    session_id: UUID,
    result_data: GameResultCreate,
    database: Session = Depends(get_database_session),
):
    game_session = database.get(GameSession, session_id)

    if game_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game session not found",
        )

    game_result = GameResult(
        session_id=session_id,
        game_name=result_data.game_name,
        input_data=result_data.input_data,
        result_data=result_data.result_data,
        score_change=result_data.score_change,
        duration_ms=result_data.duration_ms,
    )

    game_session.total_score += result_data.score_change

    database.add(game_result)
    database.commit()
    database.refresh(game_result)

    return game_result


@router.get(
    "/{session_id}/results",
    response_model=list[GameResultResponse],
)
def get_results(
    session_id: UUID,
    database: Session = Depends(get_database_session),
):
    game_session = database.get(GameSession, session_id)

    if game_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game session not found",
        )

    statement = (
        select(GameResult)
        .where(GameResult.session_id == session_id)
        .order_by(GameResult.created_at)
    )

    return database.scalars(statement).all()