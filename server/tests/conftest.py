import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="cx_tests_"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "DATA_DIR": str(_TMP / "data"),
    "AUTO_RUN_ANALYSIS": "false",
    "SEED_DEMO_DATA": "true",
    "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789abcdef",
    "DEMO_PASSWORD": "TestPassword#2026",
    "LLM_PROVIDER": "none",
    "TOOL_FAILURE_RATE": "0.18",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = os.environ["DEMO_PASSWORD"]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(_TMP, ignore_errors=True)


def login(client, role: str) -> dict:
    r = client.post("/api/auth/login", data={"username": f"{role}@cxsentinel.ai", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def hdr(client):
    return {role: login(client, role) for role in ("admin", "analyst", "approver", "viewer")}
