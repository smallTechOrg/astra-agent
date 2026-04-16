"""Pydantic models for operator.yaml and tenant.yaml.

Each model maps 1:1 to the YAML shape in spec/product/05-config.md. Secrets
never appear here as values — only as env-var pointers (`*_env` fields).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LLMProvider = Literal["openai", "anthropic", "groq", "gemini"]
SourceType = Literal["wordpress"]
LogLevel = Literal["debug", "info", "warning", "error"]


class LLMConfig(BaseModel):
    """Operator-level LLM settings. A tenant may override `api_key_env` and `model`."""

    model_config = ConfigDict(extra="allow")

    provider: LLMProvider = "groq"
    model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.8
    max_tokens: int = 2048
    api_key_env: str = "LLM_API_KEY"


class DaemonConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    share_sweep_cron: str = "*/10 * * * *"
    startup_grace_seconds: int = 5


class OperatorConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    database_path: str = "state/astra.db"
    log_level: LogLevel = "info"
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)


class SourceConfig(BaseModel):
    """Per-tenant source (today only wordpress)."""

    model_config = ConfigDict(extra="allow")

    type: SourceType
    url: str
    username: str
    app_password_env: str = "WP_APP_PASSWORD"
    poll_cron: str = "*/5 * * * *"


class LinkedInDestinationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    organization_id: str = ""
    access_token_env: str = "LINKEDIN_ACCESS_TOKEN"
    prompt: str = "linkedin_announcement"


class TwitterDestinationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    api_key_env: str = "TWITTER_API_KEY"
    api_secret_env: str = "TWITTER_API_SECRET"
    access_token_env: str = "TWITTER_ACCESS_TOKEN"
    access_secret_env: str = "TWITTER_ACCESS_SECRET"
    announcement_prompt: str = "twitter_announcement"


class DestinationsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    linkedin: LinkedInDestinationConfig = Field(default_factory=LinkedInDestinationConfig)
    twitter: TwitterDestinationConfig = Field(default_factory=TwitterDestinationConfig)


class CadenceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    cron: str
    prompt: str
    feedback_last_n: int = 20
    enabled: bool = True


class TenantLLMOverride(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_key_env: str | None = None
    model: str | None = None
    provider: LLMProvider | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class TenantConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    enabled: bool = False
    source: SourceConfig
    destinations: DestinationsConfig = Field(default_factory=DestinationsConfig)
    cadences: list[CadenceConfig] = Field(default_factory=list)
    llm: TenantLLMOverride | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        from astra.config.slug import validate_slug

        validate_slug(value)
        return value
