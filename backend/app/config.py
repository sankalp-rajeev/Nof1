"""Validated process configuration; no provider calls at import time."""

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROUTE = re.compile(r"(?:gemini|ollama|deepseek):[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
FUZZY_MATCH_THRESHOLD = 90
MAX_CORRECTION_DAYS = 6
MAX_TRACKED_OUTCOMES = 3
MAX_TRACKED_EXPOSURES = 5
RATING_MIN = 0
RATING_MAX = 10
BASE_CONTEXT_TOKENS = 2000
PATH_CONTEXT_TOKENS = 3000
CONTEXT_MESSAGE_LIMIT = 6
CONTEXT_NAME_LIMIT = 20
TOOL_CALL_LIMIT = 3
TIMELINE_ROW_LIMIT = 200
PATH_DAYS = 14
CHAT_LOCK_NAMESPACE = 741905
MAX_EXTRACTED_EVENTS = 40
MAX_EVENT_NAME_LENGTH = 200
PROPOSAL_EXPIRY_DAYS = 3
EXPERIMENT_GRACE_DAYS = 3
INSIGHT_COOLDOWN_DAYS = 3
INSIGHT_MIN_DAYS = 14
EXPERIMENT_LIMITATION = (
    "This small, unblinded test concerns one person, uses day-level resampling, "
    "and assumes a short washout."
)
TIME_OF_DAY_HOURS = {"morning": 8, "afternoon": 14, "evening": 19, "night": 22, "unspecified": 12}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False
    database_url: str = "postgresql+psycopg://nof1:nof1@localhost:5432/nof1"
    database_url_test: str = "postgresql+psycopg://nof1:nof1@localhost:5432/nof1_test"
    frontend_origin: str = "http://localhost:3000"
    gemini_api_key: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_analyzer: str = "gemini:CHANGE_ME"
    llm_composer: str = "gemini:CHANGE_ME"
    llm_narrator: str = "gemini:CHANGE_ME"
    sim_persona: str = "ollama:CHANGE_ME"
    sim_xcheck_extractor: str = "deepseek:CHANGE_ME"
    max_spend_usd: float = Field(default=1.0, ge=0)
    max_total_tokens: int = Field(default=2_000_000, gt=0)
    max_user_daily_llm_calls: int = Field(default=60, gt=0)
    max_output_tokens: int = Field(default=800, gt=0)
    llm_timeout_s: float = Field(default=20, gt=0)
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = ""

    @field_validator(
        "llm_analyzer", "llm_composer", "llm_narrator", "sim_persona", "sim_xcheck_extractor"
    )
    @classmethod
    def validate_model_route(cls, value: str) -> str:
        if not MODEL_ROUTE.fullmatch(value):
            raise ValueError("Expected provider:model with provider gemini, ollama, or deepseek")
        return value
