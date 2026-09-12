import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    (
        "postgresql+psycopg://"
        "houseofyou_app:local_development_password"
        "@localhost:5432/the_house_of_you"
    ),
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
    pool_recycle=300,
    connect_args={
        "connect_timeout": 3,
        "application_name": "the-house-of-you-api",
    },
)

SessionFactory = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_database_session() -> Generator[Session, None, None]:
    database = SessionFactory()

    try:
        yield database
    finally:
        database.close()


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return True
    except Exception:
        logger.exception("Database readiness check failed")
        return False