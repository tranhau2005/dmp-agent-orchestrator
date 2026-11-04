from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url: str) -> async_sessionmaker:
    return async_sessionmaker(create_async_engine(database_url), expire_on_commit=False)
