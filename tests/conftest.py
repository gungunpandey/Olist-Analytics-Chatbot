import asyncio
import sys
from pathlib import Path

import pytest

from app.db.loader import connect, load_database

if sys.platform == "win32":
    # subprocess support for the MCP stdio client under pytest-asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("db") / "olist.db"
    load_database(FIXTURES, db_path)
    return db_path


@pytest.fixture()
def fixture_db(fixture_db_path):
    conn = connect(fixture_db_path)
    yield conn
    conn.close()
