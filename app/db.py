"""Database engine, session factory and declarative base."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # survive Postgres restarts and idle disconnects
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator["Session"]:  # noqa: F821 - FastAPI dependency
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
