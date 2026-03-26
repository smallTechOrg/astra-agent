from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from astra.config import AstraConfig, LLMConfig, WordPressConfig


class TestDefaultConfig:
    """Test that AstraConfig can be created with default field values."""

    def test_default_llm_provider(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.llm.provider == "openai"

    def test_default_llm_model(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.llm.model == "gpt-4o"

    def test_default_llm_temperature(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.llm.temperature == 0.7

    def test_default_wordpress_url(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.wordpress.url == "http://localhost:8080"

    def test_default_database_path(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.database_path == "data/astra.db"

    def test_default_log_level(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.log_level == "info"

    def test_default_scheduler_enabled(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.scheduler.enabled is True

    def test_default_twitter_bot_disabled(self) -> None:
        cfg = AstraConfig(_env_file=None)
        assert cfg.twitter_bot.enabled is False


class TestYamlLoading:
    """Test AstraConfig.load() reads from a YAML file."""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        config_data = {
            "llm": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "api_key": "sk-yaml-key",
                "temperature": 0.5,
                "max_tokens": 8192,
            },
            "wordpress": {
                "url": "https://myblog.example.com",
                "username": "yaml_user",
                "app_password": "yaml_pass",
            },
            "database_path": "/tmp/yaml_test.db",
            "log_level": "warning",
        }
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = AstraConfig.load(config_path=config_file, _env_file=None)

        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.model == "claude-sonnet-4-20250514"
        assert cfg.llm.api_key == "sk-yaml-key"
        assert cfg.llm.temperature == 0.5
        assert cfg.llm.max_tokens == 8192
        assert cfg.wordpress.url == "https://myblog.example.com"
        assert cfg.wordpress.username == "yaml_user"
        assert cfg.database_path == "/tmp/yaml_test.db"
        assert cfg.log_level == "warning"

    def test_load_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.yaml"
        cfg = AstraConfig.load(config_path=missing, _env_file=None)
        # Should fall back to defaults without raising
        assert cfg.llm.provider == "openai"
        assert cfg.database_path == "data/astra.db"

    def test_load_partial_yaml_merges_with_defaults(self, tmp_path: Path) -> None:
        config_data = {"log_level": "error"}
        config_file = tmp_path / "partial.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = AstraConfig.load(config_path=config_file, _env_file=None)

        assert cfg.log_level == "error"
        # Other fields retain defaults
        assert cfg.llm.provider == "openai"
        assert cfg.wordpress.url == "http://localhost:8080"

    def test_load_empty_yaml_uses_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        cfg = AstraConfig.load(config_path=config_file, _env_file=None)
        assert cfg.llm.provider == "openai"


class TestEnvVarOverride:
    """Test that environment variables override YAML and defaults."""

    def test_env_overrides_top_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRA_LOG_LEVEL", "critical")
        cfg = AstraConfig()
        assert cfg.log_level == "critical"

    def test_env_overrides_nested_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRA_LLM__PROVIDER", "anthropic")
        monkeypatch.setenv("ASTRA_LLM__API_KEY", "sk-env-key")
        cfg = AstraConfig()
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.api_key == "sk-env-key"

    def test_env_overrides_nested_wordpress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRA_WORDPRESS__URL", "https://env-blog.example.com")
        cfg = AstraConfig()
        assert cfg.wordpress.url == "https://env-blog.example.com"

    def test_env_overrides_database_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASTRA_DATABASE_PATH", "/tmp/env_db.sqlite")
        cfg = AstraConfig()
        assert cfg.database_path == "/tmp/env_db.sqlite"

    def test_env_overrides_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_data = {"log_level": "debug"}
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(yaml.dump(config_data))

        monkeypatch.setenv("ASTRA_LOG_LEVEL", "critical")
        cfg = AstraConfig.load(config_path=config_file)
        # Env var should win over YAML
        assert cfg.log_level == "critical"


class TestNestedConfigAccess:
    """Test accessing deeply nested configuration properties."""

    def test_llm_section(self, sample_config: AstraConfig) -> None:
        assert isinstance(sample_config.llm, LLMConfig)
        assert sample_config.llm.provider == "openai"
        assert sample_config.llm.model == "gpt-4o-test"
        assert sample_config.llm.api_key == "sk-test-fake-key-000"

    def test_wordpress_section(self, sample_config: AstraConfig) -> None:
        assert isinstance(sample_config.wordpress, WordPressConfig)
        assert sample_config.wordpress.url == "http://wp.test.local"
        assert sample_config.wordpress.username == "testuser"
        assert sample_config.wordpress.app_password == "test-app-pw"

    def test_twitter_section(self, sample_config: AstraConfig) -> None:
        assert sample_config.twitter.api_key == "tw-key"
        assert sample_config.twitter.api_secret == "tw-secret"

    def test_linkedin_section(self, sample_config: AstraConfig) -> None:
        assert sample_config.linkedin.access_token == "li-token"
        assert sample_config.linkedin.organization_id == "li-org-123"

    def test_scheduler_defaults_preserved(self, sample_config: AstraConfig) -> None:
        assert sample_config.scheduler.post_cron == "0 9 * * *"

    def test_twitter_bot_keywords_default(self) -> None:
        cfg = AstraConfig()
        assert "WordPress" in cfg.twitter_bot.search_keywords
        assert cfg.twitter_bot.max_interactions_per_run == 10
