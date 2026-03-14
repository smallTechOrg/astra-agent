from __future__ import annotations

from pathlib import Path
from typing import Self

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "default.yaml"


# ── Section models ──────────────────────────────────────────────


class LLMConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    api_key: str = ""


class WordPressConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    url: str = "http://localhost:8080"
    username: str = "admin"
    app_password: str = ""


class TwitterConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    access_secret: str = ""
    bearer_token: str = ""


class LinkedInConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    access_token: str = ""
    organization_id: str = ""


class TwitterBotConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    enabled: bool = False
    search_keywords: list[str] = Field(default_factory=lambda: ["WordPress", "blogging tips"])
    max_interactions_per_run: int = 10
    cooldown_seconds: int = 30


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    enabled: bool = True
    post_cron: str = "0 9 * * *"
    share_cron: str = "0 */6 * * *"
    engage_cron: str = "0 */2 * * *"


# ── Root configuration ──────────────────────────────────────────


class AstraConfig(BaseSettings):
    """Root configuration for the Astra Agent.

    Loading order (later wins):
      1. Field defaults (defined above)
      2. YAML config file
      3. Environment variables prefixed with ``ASTRA_``

    Use ``AstraConfig.load()`` as the primary entry-point.
    """

    model_config = SettingsConfigDict(
        env_prefix="ASTRA_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    wordpress: WordPressConfig = Field(default_factory=WordPressConfig)
    twitter: TwitterConfig = Field(default_factory=TwitterConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    twitter_bot: TwitterBotConfig = Field(default_factory=TwitterBotConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    database_path: str = "data/astra.db"
    log_level: str = "info"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Reorder so env vars take priority over init kwargs (YAML)."""
        return env_settings, init_settings, dotenv_settings, file_secret_settings

    # ── Factory ──────────────────────────────────────────────────

    @classmethod
    def load(cls, config_path: Path | None = None) -> Self:
        """Build an ``AstraConfig`` from YAML + environment variables.

        Parameters
        ----------
        config_path:
            Optional path to a YAML file.  Falls back to
            ``config/default.yaml`` inside the project root.

        Returns
        -------
        AstraConfig
            Fully-resolved configuration instance.
        """
        path = config_path or _DEFAULT_CONFIG
        yaml_overrides: dict = {}

        if path.exists():
            logger.info("loading_config", path=str(path))
            with path.open("r") as fh:
                raw = yaml.safe_load(fh)
            if isinstance(raw, dict):
                yaml_overrides = raw
        else:
            logger.warning("config_file_not_found", path=str(path))

        # pydantic-settings picks up env vars automatically during init.
        # We pass the YAML data as keyword init values so that env vars
        # (which pydantic-settings reads) still take highest precedence.
        return cls(**yaml_overrides)
