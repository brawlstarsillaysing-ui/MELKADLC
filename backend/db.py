from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.config import settings


@lru_cache
def engine():
    return create_engine(settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def session():
    with Session(engine(), expire_on_commit=False) as db:
        with db.begin():
            yield db
