"""Single source of truth for all settings. Everything reads `settings` from here."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The Olist dataset's real date span. "last year" always means 2017.
DATASET_MIN_DATE = "2016-09-04"
DATASET_MAX_DATE = "2018-10-17"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_mode: str = "llm"                        # AGENT_MODE: llm | fallback
    openrouter_api_key: str = ""                   # OPENROUTER_API_KEY
    openrouter_model: str = "qwen/qwen-turbo"      # OPENROUTER_MODEL (any tool-calling model)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    agent_timeout_seconds: float = 60.0            # AGENT_TIMEOUT_SECONDS
    tool_timeout_seconds: float = 20.0             # TOOL_TIMEOUT_SECONDS
    data_dir: Path = Path("data")                  # DATA_DIR — the 9 Olist CSVs
    storage_dir: Path = Path("storage")            # STORAGE_DIR — SQLite files
    port: int = 8000                               # PORT

    @property
    def dataset_db_path(self) -> Path:
        return self.storage_dir / "olist.db"

    @property
    def app_db_path(self) -> Path:
        return self.storage_dir / "app.db"


settings = Settings()
