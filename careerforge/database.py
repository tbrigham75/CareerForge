from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings):
    return create_engine(settings.database_url, connect_args={"check_same_thread": False})


def make_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
