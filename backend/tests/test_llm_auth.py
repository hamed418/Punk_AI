"""
tests/test_llm_auth.py
──────────────────────
The LLM authenticates through Vertex (Application Default Credentials) only —
there is no API-key mode. These pin that a GOOGLE_API_KEY left in the
environment (the old prod service still carries one) can never win.

No network and no ADC needed — clients build lazily.
"""

import pytest
from google import genai
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings


@pytest.fixture(autouse=True)
def _leftover_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "leftover-secret")
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", "p")
    monkeypatch.setattr(settings, "VERTEX_LOCATION", "global")


def test_langchain_client_uses_vertex_not_the_env_key():
    api = ChatGoogleGenerativeAI(model="gemini-2.5-flash", **settings.llm_auth).client._api_client
    assert api.vertexai is True
    assert (api.project, api.location) == ("p", "global")
    assert api.api_key is None


def test_raw_sdk_client_uses_vertex_not_the_env_key():
    api = genai.Client(**settings.genai_auth)._api_client
    assert api.vertexai is True
    assert (api.project, api.location) == ("p", "global")
    assert api.api_key is None


def test_auth_kwargs_carry_no_api_key():
    assert set(settings.llm_auth) == {"vertexai", "project", "location"}
    assert set(settings.genai_auth) == {"vertexai", "project", "location"}
