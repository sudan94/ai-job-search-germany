"""Process configuration, and the one setting that silently broke every API call."""

from __future__ import annotations

from app.config import DEFAULT_OPENAI_BASE_URL, Settings
from app.llm import _client_kwargs


def test_blank_env_values_mean_not_configured():
    config = Settings(openai_api_key="   ", openai_base_url="", adzuna_app_id="")
    assert config.openai_api_key is None
    assert config.openai_base_url is None
    assert config.adzuna_app_id is None
    assert config.llm_enabled is False


def test_a_blank_base_url_falls_back_to_the_real_api():
    """`.env` ships OPENAI_BASE_URL blank, and the SDK reads that variable itself.

    Left as an empty string it makes every request relative, which surfaces as
    an unexplained "Connection error" on scoring, letters and embeddings.
    """
    config = Settings(openai_base_url="")
    assert config.openai_base_url_effective == DEFAULT_OPENAI_BASE_URL

    assert _client_kwargs()["base_url"].startswith("https://")


def test_a_configured_gateway_is_kept():
    config = Settings(openai_base_url="http://localhost:11434/v1")
    assert config.openai_base_url_effective == "http://localhost:11434/v1"
