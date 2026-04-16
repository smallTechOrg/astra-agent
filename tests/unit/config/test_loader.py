from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astra.config import ConfigLoader
from astra.errors import (
    ConfigValidationError,
    CronParseError,
    DuplicateCadenceNameError,
    SecretInYamlError,
    TenantIdMismatchError,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _valid_tenant_yaml(tenant_id: str = "acme-corp") -> str:
    return f"""
id: {tenant_id}
name: Acme Corp
enabled: true
source:
  type: wordpress
  url: https://blog.acme.com
  username: admin
  app_password_env: WP_APP_PASSWORD
  poll_cron: "*/5 * * * *"
destinations:
  linkedin:
    enabled: true
    organization_id: "12345"
    access_token_env: LINKEDIN_ACCESS_TOKEN
    prompt: linkedin_announcement
  twitter:
    enabled: false
cadences:
  - name: daily-tips
    cron: "0 14 * * *"
    prompt: twitter_cadence_daily_tips
    feedback_last_n: 20
    enabled: true
"""


def _build_config_dir(
    tmp_path: Path,
    tenants: dict[str, tuple[str, dict[str, str]]],
    operator_yaml: str | None = None,
    operator_env: dict[str, str] | None = None,
) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    if operator_yaml is not None:
        _write(config_dir / "operator.yaml", operator_yaml)
    if operator_env:
        _write(
            config_dir / ".env",
            "\n".join(f"{k}={v}" for k, v in operator_env.items()),
        )
    for tenant_id, (yaml_body, env) in tenants.items():
        tenant_dir = config_dir / "tenants" / tenant_id
        _write(tenant_dir / "tenant.yaml", yaml_body)
        if env:
            _write(
                tenant_dir / ".env",
                "\n".join(f"{k}={v}" for k, v in env.items()),
            )
    return config_dir


def test_happy_path_loads_tenant(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        tenants={
            "acme-corp": (
                _valid_tenant_yaml(),
                {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "tok"},
            )
        },
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    tenant = loaded.tenants["acme-corp"]
    assert not tenant.degraded
    assert tenant.config.enabled is True
    assert "WP_APP_PASSWORD" in tenant.secrets
    assert tenant.secrets["WP_APP_PASSWORD"].get_secret_value() == "pw"


def test_missing_secret_marks_tenant_degraded_not_fatal(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        tenants={"acme-corp": (_valid_tenant_yaml(), {})},
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    tenant = loaded.tenants["acme-corp"]
    assert tenant.degraded
    assert tenant.degraded_reason is not None
    assert "WP_APP_PASSWORD" in tenant.degraded_reason


def test_secret_in_yaml_rejected(tmp_path: Path) -> None:
    bad_yaml = _valid_tenant_yaml() + "\nwp_app_password: literal-secret\n"
    config_dir = _build_config_dir(
        tmp_path,
        tenants={"acme-corp": (bad_yaml, {})},
    )
    with pytest.raises(SecretInYamlError):
        ConfigLoader(config_dir, os_env={}).load()


def test_invalid_cron_rejected(tmp_path: Path) -> None:
    bad = _valid_tenant_yaml().replace("*/5 * * * *", "not a cron")
    config_dir = _build_config_dir(
        tmp_path,
        tenants={"acme-corp": (bad, {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"})},
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "acme-corp" not in loaded.tenants
    assert "acme-corp" in loaded.load_errors
    assert "cron" in loaded.load_errors["acme-corp"].lower()


def test_duplicate_cadence_name_rejected(tmp_path: Path) -> None:
    duped = _valid_tenant_yaml() + """\
  - name: daily-tips
    cron: "30 14 * * *"
    prompt: twitter_cadence_daily_tips
    feedback_last_n: 20
    enabled: true
"""
    config_dir = _build_config_dir(
        tmp_path,
        tenants={"acme-corp": (duped, {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"})},
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "duplicate cadence" in loaded.load_errors["acme-corp"].lower()


def test_unknown_top_level_key_is_warning_not_error(tmp_path: Path) -> None:
    extra = _valid_tenant_yaml() + "\nforward_compat_field: something\n"
    config_dir = _build_config_dir(
        tmp_path,
        tenants={"acme-corp": (extra, {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"})},
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    tenant = loaded.tenants["acme-corp"]
    assert tenant.load_warnings
    assert any("forward_compat_field" in w for w in tenant.load_warnings)


def test_id_directory_mismatch_fatal_only_for_this_tenant(tmp_path: Path) -> None:
    mismatched = _valid_tenant_yaml().replace("id: acme-corp", "id: wrong-id")
    config_dir = _build_config_dir(
        tmp_path,
        tenants={
            "acme-corp": (mismatched, {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"}),
            "beta-inc": (
                _valid_tenant_yaml("beta-inc"),
                {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"},
            ),
        },
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "acme-corp" in loaded.load_errors
    assert "beta-inc" in loaded.tenants
    assert not loaded.tenants["beta-inc"].degraded


def test_two_tenant_isolation_bad_yaml_does_not_break_sibling(tmp_path: Path) -> None:
    bad_yaml = "id: broken\nname: Broken\nsource:\n  type: wordpress\n"  # missing url/username
    config_dir = _build_config_dir(
        tmp_path,
        tenants={
            "broken": (bad_yaml, {}),
            "acme-corp": (
                _valid_tenant_yaml(),
                {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "t"},
            ),
        },
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "broken" in loaded.load_errors
    assert "acme-corp" in loaded.tenants
    assert not loaded.tenants["acme-corp"].degraded


def test_os_env_overrides_tenant_env(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        tenants={
            "acme-corp": (
                _valid_tenant_yaml(),
                {"WP_APP_PASSWORD": "from-tenant-env", "LINKEDIN_ACCESS_TOKEN": "t"},
            )
        },
    )
    loaded = ConfigLoader(
        config_dir, os_env={"WP_APP_PASSWORD": "from-os-env"}
    ).load()
    tenant = loaded.tenants["acme-corp"]
    assert tenant.secrets["WP_APP_PASSWORD"].get_secret_value() == "from-os-env"


def test_missing_tenant_yaml_is_per_tenant_error(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    (config_dir / "tenants" / "empty").mkdir(parents=True)
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "empty" in loaded.load_errors


def test_invalid_slug_id_rejected(tmp_path: Path) -> None:
    bad = _valid_tenant_yaml("Bad_Id")
    bad = bad.replace("Bad_Id", "Bad_Id").replace("Bad_Id", "Bad_Id")
    config_dir = tmp_path / "config"
    (config_dir / "tenants" / "Bad_Id").mkdir(parents=True)
    (config_dir / "tenants" / "Bad_Id" / "tenant.yaml").write_text(_valid_tenant_yaml("Bad_Id"))
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert "Bad_Id" in loaded.load_errors


def test_disabled_destination_missing_secret_is_ok(tmp_path: Path) -> None:
    yaml_text = _valid_tenant_yaml().replace(
        "  twitter:\n    enabled: false",
        "  twitter:\n    enabled: false\n    api_key_env: TWITTER_API_KEY",
    )
    config_dir = _build_config_dir(
        tmp_path,
        tenants={
            "acme-corp": (
                yaml_text,
                {"WP_APP_PASSWORD": "pw", "LINKEDIN_ACCESS_TOKEN": "tok"},
            )
        },
    )
    loaded = ConfigLoader(config_dir, os_env={}).load()
    assert not loaded.tenants["acme-corp"].degraded


def test_raises_typed_errors() -> None:
    for cls in (
        ConfigValidationError,
        SecretInYamlError,
        TenantIdMismatchError,
        DuplicateCadenceNameError,
        CronParseError,
    ):
        with pytest.raises(cls):
            raise cls("test")
