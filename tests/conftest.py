import os
import secrets
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import engine
from backend.models import Base


@pytest.fixture(scope="session", autouse=True)
def test_database():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url or not url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must explicitly name an isolated *_test PostgreSQL database")
    os.environ["DATABASE_URL"] = url
    os.environ["ADMIN_IDS"] = "999"
    os.environ["PAYMENT_CARD"] = ""
    os.environ["PAYMENT_RECIPIENT"] = ""
    os.environ["SERVICE_TOKEN"] = secrets.token_urlsafe(48)
    os.environ["KEY_HASH_SECRET"] = secrets.token_urlsafe(48)
    os.environ["KEY_ENCRYPTION_SECRET"] = Fernet.generate_key().decode()
    os.environ["BOT_TOKEN"] = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    os.environ["BOT_USERNAME"] = "test_bot"
    os.environ["API_BASE_URL"] = "http://test"
    settings.cache_clear()
    engine.cache_clear()
    subprocess.run(
        [str(Path(__import__("sys").executable).parent / "alembic"), "upgrade", "head"], check=True
    )
    yield
    engine().dispose()


@pytest.fixture(autouse=True)
def clean_database(test_database):
    tables = ", ".join('"' + t.name + '"' for t in reversed(Base.metadata.sorted_tables))
    with engine().begin() as db:
        db.execute(text("TRUNCATE " + tables + " CASCADE"))


@pytest.fixture
def client():
    from backend.main import app

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture
def db():
    from backend.services import seed

    with Session(engine(), expire_on_commit=False) as db, db.begin():
        seed(db)
        yield db
