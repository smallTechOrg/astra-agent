"""Secret resolution and secret-in-YAML detection.

Per spec/engineering/secret-hygiene.md: any key matching *_token, *_secret,
*_password, *_key, *_credential is rejected at YAML load. Secret values are
always resolved from env (tenant .env → operator .env → OS env) via `*_env`
pointers.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from pydantic import SecretStr

from astra.errors import SecretInYamlError

if TYPE_CHECKING:
    from pathlib import Path

_SECRET_KEY_RE = re.compile(r"_(token|secret|password|key|credential)$", re.IGNORECASE)


def assert_no_secret_values(data: object, *, path: str = "") -> None:
    """Walk a parsed-YAML tree and raise if any key name marks it a secret.

    `*_env` pointers are allowed (they name an env var, not the secret itself).
    """

    if isinstance(data, dict):
        for key, value in data.items():
            key_str = str(key)
            if _SECRET_KEY_RE.search(key_str) and not key_str.endswith("_env"):
                raise SecretInYamlError(
                    f"secret-named key {path + '.' + key_str if path else key_str!r} "
                    f"found in YAML. Secrets must live in .env; reference them via "
                    f"a *_env pointer instead."
                )
            assert_no_secret_values(value, path=f"{path}.{key_str}" if path else key_str)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            assert_no_secret_values(item, path=f"{path}[{idx}]")


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Minimal dotenv parser. Values with spaces are fine; no quoting required."""

    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        result[key] = value
    return result


class SecretResolver:
    """Resolve an env-var pointer to its value per spec precedence rules.

    Precedence (highest wins):
      1. OS env var (including ASTRA_TENANT__<UPPER_ID>__ override path)
      2. Per-tenant .env
      3. Operator .env
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        tenant_env: dict[str, str],
        operator_env: dict[str, str],
        os_env: dict[str, str] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._tenant_env = dict(tenant_env)
        self._operator_env = dict(operator_env)
        self._os_env = dict(os_env) if os_env is not None else dict(os.environ)

    def resolve(self, env_var: str) -> SecretStr | None:
        """Return the secret or None if no source has a non-empty value."""

        value = self._os_env.get(env_var)
        if value:
            return SecretStr(value)
        value = self._tenant_env.get(env_var)
        if value:
            return SecretStr(value)
        value = self._operator_env.get(env_var)
        if value:
            return SecretStr(value)
        return None

    def tenant_env_override_prefix(self) -> str:
        normalized = self._tenant_id.upper().replace("-", "_")
        return f"ASTRA_TENANT__{normalized}__"
