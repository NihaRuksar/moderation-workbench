import json
import os

# Must be set BEFORE importing the app, so tests use their own database file
os.environ["DATABASE_URL"] = "sqlite:///./test_moderation.db"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.services import ai_review


@pytest.fixture()
def client():
    """A fresh database for every test: empty tables, then the seed runs at startup."""
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    """Replaces the real AI call in every test, so no test can reach Groq.
    A test sets fake_ai["reply"] to a dict (valid JSON), a string, or an Exception."""
    state = {
        "calls": 0,
        "reply": {
            "findings": [],
            "proposed_action": "no_action",
            "severity": "low",
            "confidence": 0.95,
            "needs_human": False,
            "reasoning": "test",
        },
    }

    def fake_call(messages):
        state["calls"] += 1
        reply = state["reply"]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict):
            return json.dumps(reply)
        return reply

    monkeypatch.setattr(ai_review, "AI_API_KEY", "test-key")
    monkeypatch.setattr(ai_review, "_call_ai", fake_call)
    return state


@pytest.fixture(scope="session", autouse=True)
def remove_test_database():
    yield
    engine.dispose()
    if os.path.exists("test_moderation.db"):
        os.remove("test_moderation.db")