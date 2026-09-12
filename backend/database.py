import os

from sqlalchemy import create_engine, text


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
    pool_timeout=3,
    connect_args={
        "connect_timeout": 3,
    },
)


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return True
    except Exception:
        return False