"""Prompt resolver tests.

Gate (phase 5): override wins, operator fallback, fatal-missing,
header validates variables, splitter works with/without ---, typo caught.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astra.errors import PromptNotFoundError, PromptVariableError
from astra.prompts.resolver import PromptResolver

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def operator_dir(tmp_path: Path) -> Path:
    d = tmp_path / "prompts"
    d.mkdir()
    return d


@pytest.fixture
def tenant_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tenant_prompts"
    d.mkdir()
    return d


def _resolver(
    operator_dir: Path, tenant_dir: Path | None = None
) -> PromptResolver:
    return PromptResolver(operator_dir, tenant_dir)


# ── Resolution order ─────────────────────────────────────────────

def test_operator_default_is_used_when_no_tenant_override(
    operator_dir: Path,
) -> None:
    (operator_dir / "my_prompt.txt").write_text("Hello {name}")
    r = _resolver(operator_dir)
    result = r.render("my_prompt", name="world")
    assert result.user_prompt == "Hello world"


def test_tenant_override_wins_over_operator(
    operator_dir: Path, tenant_dir: Path
) -> None:
    (operator_dir / "my_prompt.txt").write_text("Operator: {name}")
    (tenant_dir / "my_prompt.txt").write_text("Tenant: {name}")
    r = _resolver(operator_dir, tenant_dir)
    result = r.render("my_prompt", name="Acme")
    assert result.user_prompt == "Tenant: Acme"


def test_falls_back_to_operator_when_tenant_missing_file(
    operator_dir: Path, tenant_dir: Path
) -> None:
    (operator_dir / "my_prompt.txt").write_text("Op {x}")
    r = _resolver(operator_dir, tenant_dir)
    result = r.render("my_prompt", x="val")
    assert "Op val" in result.user_prompt


def test_prompt_not_found_raises(operator_dir: Path) -> None:
    r = _resolver(operator_dir)
    with pytest.raises(PromptNotFoundError, match="ghost_prompt"):
        r.render("ghost_prompt", x="y")


# ── Variable header ──────────────────────────────────────────────

def test_header_validates_matching_variables(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text(
        "# variables: title, url\nHere is {title} and {url}"
    )
    r = _resolver(operator_dir)
    result = r.render("p", title="T", url="U")
    assert "T" in result.user_prompt
    assert "U" in result.user_prompt


def test_header_catches_typo_in_template(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text(
        "# variables: title, url\nHere is {titile} and {url}"
    )
    r = _resolver(operator_dir)
    with pytest.raises(PromptVariableError, match="titile"):
        r.render("p", title="T", url="U")


def test_header_catches_missing_passed_variable(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text(
        "# variables: title, url\nHere is {title} and {url}"
    )
    r = _resolver(operator_dir)
    with pytest.raises(PromptVariableError, match="missing"):
        r.render("p", title="T")  # url missing


def test_header_catches_extra_passed_variable(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text(
        "# variables: title\nHere is {title}"
    )
    r = _resolver(operator_dir)
    with pytest.raises(PromptVariableError, match="extra"):
        r.render("p", title="T", url="extra")


def test_no_header_accepts_used_variables(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text("Value: {x}")
    r = _resolver(operator_dir)
    result = r.render("p", x="42")
    assert result.user_prompt == "Value: 42"


def test_no_header_rejects_missing_variable(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text("Value: {x}")
    r = _resolver(operator_dir)
    with pytest.raises(PromptVariableError):
        r.render("p")  # x not passed


# ── --- separator ─────────────────────────────────────────────────

def test_separator_splits_system_and_user(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text(
        "# variables: name\nYou are a writer.\n---\nWrite about {name}."
    )
    r = _resolver(operator_dir)
    result = r.render("p", name="Buddhism")
    assert result.system_prompt == "You are a writer."
    assert result.user_prompt == "Write about Buddhism."


def test_no_separator_returns_none_system(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text("# variables: x\nJust {x}")
    r = _resolver(operator_dir)
    result = r.render("p", x="text")
    assert result.system_prompt is None
    assert result.user_prompt == "Just text"


def test_separator_with_empty_system_section(operator_dir: Path) -> None:
    (operator_dir / "p.txt").write_text("# variables: x\n---\nUser: {x}")
    r = _resolver(operator_dir)
    result = r.render("p", x="hello")
    assert result.system_prompt is None
    assert result.user_prompt == "User: hello"


# ── Real operator default prompts ────────────────────────────────

def test_operator_default_prompts_exist() -> None:
    """Smoke test that the repo ships both required operator-default prompts."""

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / "prompts" / "linkedin_announcement.txt").exists(), (
        "prompts/linkedin_announcement.txt is required by spec/product/08-prompts.md"
    )
    assert (repo_root / "prompts" / "twitter_announcement.txt").exists(), (
        "prompts/twitter_announcement.txt is required by spec/product/08-prompts.md"
    )
