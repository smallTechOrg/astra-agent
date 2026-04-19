"""PromptResolver: load, validate, and render prompts from the DB.

Per spec/product/08-prompts.md:
- Resolution: tenant DB row → operator DB row → PromptNotFoundError (fatal).
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
    from astra.db.connection import Database

_VAR_HEADER_RE = re.compile(r"^#\s*variables:\s*(.+)$", re.IGNORECASE)
_SEPARATOR = "---"


@dataclass(frozen=True)
class RenderedPrompt:
    system_prompt: str | None
    user_prompt: str


class PromptResolver:
    """Resolve and render prompts for a tenant from the DB."""

    def __init__(self, db: Database, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def render(self, prompt_name: str, **variables: str) -> RenderedPrompt:
        """Load from DB, validate, and render a prompt.

        Raises:
            PromptNotFoundError: if neither tenant nor operator row exists.
            PromptVariableError: if declared/used variables don't match passed ones.
        """
        from astra.db.repos import PromptsRepo

        repo = PromptsRepo(self._db)
        record = await repo.resolve(self._tenant_id, prompt_name)
        if record is None:
            raise PromptNotFoundError(
                f"Prompt {prompt_name!r} not found for tenant {self._tenant_id!r} "
                f"or as operator default"
            )

        return _render_content(prompt_name, record.content, variables)


def _render_content(
    prompt_name: str, raw: str, variables: dict[str, str]
) -> RenderedPrompt:
    """Parse, validate, and render prompt content."""
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
