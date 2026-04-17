"""PromptResolver: load, validate, and render prompt files.

Per spec/product/08-prompts.md:
- Resolution: tenant override → operator default → PromptNotFoundError (fatal).
- `# variables: a, b, c` header declares expected placeholders.
- `---` separator splits system_prompt from user_prompt.
- Python str.format() for {placeholder} substitution.
- PromptVariableError if declared ≠ passed (catches typos at render time).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.errors import PromptNotFoundError, PromptVariableError

if TYPE_CHECKING:
    from pathlib import Path

_VAR_HEADER_RE = re.compile(r"^#\s*variables:\s*(.+)$", re.IGNORECASE)
_SEPARATOR = "---"


@dataclass(frozen=True)
class RenderedPrompt:
    system_prompt: str | None
    user_prompt: str


class PromptResolver:
    """Resolve and render prompts for a tenant.

    *operator_prompts_dir* is the repo-root `prompts/` directory.
    *tenant_prompts_dir* is `config/tenants/<id>/prompts/` (may not exist).
    """

    def __init__(
        self,
        operator_prompts_dir: Path,
        tenant_prompts_dir: Path | None = None,
    ) -> None:
        self._operator = operator_prompts_dir
        self._tenant = tenant_prompts_dir

    def _locate(self, name: str) -> Path:
        """Return the Path for prompt *name*, following resolution order."""

        if self._tenant is not None:
            candidate = self._tenant / f"{name}.txt"
            if candidate.exists():
                return candidate

        candidate = self._operator / f"{name}.txt"
        if candidate.exists():
            return candidate

        raise PromptNotFoundError(
            f"Prompt {name!r} not found in tenant overrides or operator defaults"
        )

    def render(self, prompt_name: str, **variables: str) -> RenderedPrompt:
        """Load, validate, and render a prompt.

        Raises:
            PromptNotFoundError: if neither tenant nor operator file exists.
            PromptVariableError: if declared/used variables don't match passed ones.
        """

        path = self._locate(prompt_name)
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()

        declared: frozenset[str] | None = None
        content_start = 0

        if lines and _VAR_HEADER_RE.match(lines[0]):
            header_match = _VAR_HEADER_RE.match(lines[0])
            assert header_match is not None
            declared = frozenset(
                v.strip() for v in header_match.group(1).split(",") if v.strip()
            )
            content_start = 1

        content = "\n".join(lines[content_start:]).strip()

        # Validate variables before rendering.
        used = _extract_placeholders(content)
        passed = frozenset(variables.keys())

        if declared is not None:
            if declared != used:
                diff = (declared - used) | (used - declared)
                raise PromptVariableError(
                    f"Prompt {prompt_name!r}: declared={sorted(declared)}, "
                    f"used={sorted(used)}, mismatch={sorted(diff)}"
                )
            if declared != passed:
                missing = declared - passed
                extra = passed - declared
                parts = []
                if missing:
                    parts.append(f"missing={sorted(missing)}")
                if extra:
                    parts.append(f"extra={sorted(extra)}")
                raise PromptVariableError(
                    f"Prompt {prompt_name!r}: {'; '.join(parts)}"
                )
        else:
            # No header — used must equal passed.
            if used != passed:
                missing = used - passed
                extra = passed - used
                parts = []
                if missing:
                    parts.append(f"missing values for {sorted(missing)}")
                if extra:
                    parts.append(f"unexpected variables {sorted(extra)}")
                raise PromptVariableError(
                    f"Prompt {prompt_name!r}: {'; '.join(parts)}"
                )

        rendered = content.format(**variables)

        if _SEPARATOR in rendered.splitlines():
            sep_index = rendered.splitlines().index(_SEPARATOR)
            rendered_lines = rendered.splitlines()
            system = "\n".join(rendered_lines[:sep_index]).strip() or None
            user = "\n".join(rendered_lines[sep_index + 1:]).strip()
            return RenderedPrompt(system_prompt=system, user_prompt=user)

        return RenderedPrompt(system_prompt=None, user_prompt=rendered)


def _extract_placeholders(text: str) -> frozenset[str]:
    """Return all {placeholder} names used in *text* via string.Formatter."""

    formatter = string.Formatter()
    return frozenset(
        fname
        for _, fname, _, _ in formatter.parse(text)
        if fname is not None and fname != ""
    )
