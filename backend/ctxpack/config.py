"""Settings from .env (secrets + behaviour) and numbers from config/*.yaml.

Secrets are only ever read here and passed to the clients that need them.
Nothing in this module prints, logs or returns a secret value.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
CONFIG_DIR = Path(__file__).resolve().parent / "config"

OFFLINE_SALT = "fixtures-only-not-a-secret"  # offline demo only: recorded data, nothing real is hashed

SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "APIFY_API_TOKEN",
    "AUTHOR_HASH_SALT",
    "RUN_KEY",
    "DATABASE_URL",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets (SecretStr: never shown when printed) ---
    anthropic_api_key: SecretStr | None = None
    apify_api_token: SecretStr | None = None
    author_hash_salt: SecretStr | None = None
    run_key: SecretStr | None = None
    database_url: SecretStr | None = None

    # --- Behaviour ---
    use_fixtures: bool = False
    llm_fake: bool = False
    data_dir: str = "../data"
    retention_days: int = 30
    daily_spend_cap_usd: float = 25.0
    synth_model_role: str = "synth"
    log_level: str = "INFO"
    worker_mode: str = "inprocess"

    def is_set(self, name: str) -> bool:
        """True if the secret has a non-empty value. Never returns the value."""
        value = getattr(self, name.lower())
        return value is not None and value.get_secret_value().strip() != ""

    @property
    def offline(self) -> bool:
        """Recorded data AND the fake model: nothing can be paid for. A fresh clone with no .env runs
        this way (README): local SQLite, a fixed demo salt, and runs start without a run key."""
        return self.use_fixtures and self.llm_fake

    @property
    def data_path(self) -> Path:
        """DATA_DIR resolved relative to backend/ (absolute paths kept)."""
        path = Path(self.data_dir)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def sqlalchemy_url(url: str) -> str:
    """Neon gives postgres:// or postgresql://; SQLAlchemy needs the psycopg 3 driver name."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    """Load config/<name>.yaml (models, modes, scoring, catalog)."""
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def model_for(role: str) -> str:
    """Model name for a role (reasoner, worker, evaluator, synth)."""
    return load_yaml("models")["roles"][role]


def mode_limits(mode: str) -> dict[str, Any]:
    """Per-run limits for 'quick' or 'standard'."""
    return load_yaml("modes")["modes"][mode]
