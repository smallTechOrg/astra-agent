"""Pydantic models for operator.yaml and runtime tenant views.

Per spec/product/05-config.md: operator.yaml holds operator-level settings;
tenant config and secrets live in the database (spec/product/07-data-model.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from astra.db.repos import CadenceRecord
    from astra.db.repos import TenantConfig as DBTenantConfig

LLMProvider = Literal["openai", "anthropic", "groq", "gemini"]
SourceType = Literal["wordpress"]
LogLevel = Literal["debug", "info", "warning", "error"]

_SECRET_KEYS = frozenset(
    ["WP_APP_PASSWORD", "LINKEDIN_ACCESS_TOKEN",
     "TWITTER_API_KEY", "TWITTER_API_SECRET",
     "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"]
)


class LLMConfig(BaseModel):
    """Operator-level LLM settings. Tenants may override model/provider/temperature."""

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
    log_level: LogLevel = "info"
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)


class SourceConfig(BaseModel):
    """Per-tenant source (today: wordpress only)."""

    model_config = ConfigDict(extra="allow")

    type: SourceType = "wordpress"
    url: str = ""
    username: str = ""
    poll_cron: str = "*/5 * * * *"


class LinkedInDestinationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    organization_id: str = ""
    prompt: str = "linkedin_announcement"


class TwitterDestinationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
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

    model: str | None = None
    provider: LLMProvider | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class TenantConfig(BaseModel):
    """Runtime view of a tenant, constructed from DB records."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    enabled: bool = False
    source: SourceConfig = Field(default_factory=SourceConfig)
    destinations: DestinationsConfig = Field(default_factory=DestinationsConfig)
    cadences: list[CadenceConfig] = Field(default_factory=list)
    llm: TenantLLMOverride | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        from astra.config.slug import validate_slug

        validate_slug(value)
        return value

    @classmethod
    def from_db(
        cls,
        tenant_id: str,
        tenant_name: str,
        enabled: bool,
        db_cfg: DBTenantConfig,
        cadence_records: list[CadenceRecord],
    ) -> TenantConfig:
        source = SourceConfig(
            type=db_cfg.source_type,
            url=db_cfg.source_url or "",
            username=db_cfg.source_username or "",
            poll_cron=db_cfg.source_poll_cron,
        )
        linkedin = LinkedInDestinationConfig(
            enabled=db_cfg.linkedin_enabled,
            organization_id=db_cfg.linkedin_org_id or "",
            prompt=db_cfg.linkedin_prompt,
        )
        twitter = TwitterDestinationConfig(
            enabled=db_cfg.twitter_enabled,
            announcement_prompt=db_cfg.twitter_announcement_prompt,
        )
        cadences = [
            CadenceConfig(
                name=c.name,
                cron=c.cron,
                prompt=c.prompt,
                feedback_last_n=c.feedback_last_n,
                enabled=c.enabled,
            )
            for c in cadence_records
        ]
        llm_override: TenantLLMOverride | None = None
        if any([db_cfg.llm_provider, db_cfg.llm_model,
                db_cfg.llm_temperature, db_cfg.llm_max_tokens]):
            llm_override = TenantLLMOverride(
                provider=db_cfg.llm_provider,
                model=db_cfg.llm_model,
                temperature=db_cfg.llm_temperature,
                max_tokens=db_cfg.llm_max_tokens,
            )
        return cls(
            id=tenant_id,
            name=tenant_name,
            enabled=enabled,
            source=source,
            destinations=DestinationsConfig(linkedin=linkedin, twitter=twitter),
            cadences=cadences,
            llm=llm_override,
        )
