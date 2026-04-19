"""Prompt resolver tests (DB-backed).

Gate: override wins, operator fallback, fatal-missing,
header validates variables, splitter works with/without ---, typo caught.
Prompts are now stored in the `prompts` table per spec/product/08-prompts.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astra.db.repos import PromptsRepo, TenantsRepo
from astra.errors import PromptNotFoundError, PromptVariableError
from astra.prompts.resolver import PromptResolver

if TYPE_CHECKING:
    from astra.db import Database


@pytest.fixture
async def db(db: Database) -> Database:
    """Seed a tenant for prompt tests."""
    await TenantsRepo(db).upsert("acme", "Acme", enabled=True)
    return db


def _resolver(db: Database, tenant_id: str = "acme") -> PromptResolver:
    return PromptResolver(db=db, tenant_id=tenant_id)


# ── Resolution order ─────────────────────────────────────────────

async def test_operator_default_is_used_when_no_tenant_override(
    db: Database,
) -> None:
    await PromptsRepo(db).upsert_operator("my_prompt", "Hello {name}")
    r = _resolver(db)
    result = await r.render("my_prompt", name="world")
    assert result.user_prompt == "Hello world"


async def test_tenant_override_wins_over_operator(db: Database) -> None:
    await PromptsRepo(db).upsert_operator("my_prompt", "Operator: {name}")
    await PromptsRepo(db).upsert_tenant("acme", "my_prompt", "Tenant: {name}")
    r = _resolver(db)
    result = await r.render("my_prompt", name="Acme")
    assert result.user_prompt == "Tenant: Acme"


async def test_falls_back_to_operator_when_tenant_has_no_override(
    db: Database,
) -> None:
    await PromptsRepo(db).upsert_operator("my_prompt", "Op {x}")
    r = _resolver(db)
    result = await r.render("my_prompt", x="val")
    assert "Op val" in result.user_prompt


async def test_prompt_not_found_raises(db: Database) -> None:
    r = _resolver(db)
    with pytest.raises(PromptNotFoundError, match="ghost_prompt"):
        await r.render("ghost_prompt", x="y")


# ── Variable header ──────────────────────────────────────────────

async def test_header_validates_matching_variables(db: Database) -> None:
    await PromptsRepo(db).upsert_operator(
        "p", "# variables: title, url\nHere is {title} and {url}"
    )
    r = _resolver(db)
    result = await r.render("p", title="T", url="U")
    assert "T" in result.user_prompt
    assert "U" in result.user_prompt


async def test_header_catches_typo_in_template(db: Database) -> None:
    await PromptsRepo(db).upsert_operator(
        "p", "# variables: title, url\nHere is {titile} and {url}"
    )
    r = _resolver(db)
    with pytest.raises(PromptVariableError, match="titile"):
        await r.render("p", title="T", url="U")


async def test_header_catches_missing_passed_variable(db: Database) -> None:
    await PromptsRepo(db).upsert_operator(
        "p", "# variables: title, url\nHere is {title} and {url}"
    )
    r = _resolver(db)
    with pytest.raises(PromptVariableError, match="missing"):
        await r.render("p", title="T")  # url missing


async def test_header_catches_extra_passed_variable(db: Database) -> None:
    await PromptsRepo(db).upsert_operator(
        "p", "# variables: title\nHere is {title}"
    )
    r = _resolver(db)
    with pytest.raises(PromptVariableError, match="extra"):
        await r.render("p", title="T", url="extra")


async def test_no_header_accepts_used_variables(db: Database) -> None:
    await PromptsRepo(db).upsert_operator("p", "Value: {x}")
    r = _resolver(db)
    result = await r.render("p", x="42")
    assert result.user_prompt == "Value: 42"


async def test_no_header_rejects_missing_variable(db: Database) -> None:
    await PromptsRepo(db).upsert_operator("p", "Value: {x}")
    r = _resolver(db)
    with pytest.raises(PromptVariableError):
        await r.render("p")  # x not passed


# ── --- separator ─────────────────────────────────────────────────

async def test_separator_splits_system_and_user(db: Database) -> None:
    await PromptsRepo(db).upsert_operator(
        "p", "# variables: name\nYou are a writer.\n---\nWrite about {name}."
    )
    r = _resolver(db)
    result = await r.render("p", name="Buddhism")
    assert result.system_prompt == "You are a writer."
    assert result.user_prompt == "Write about Buddhism."


async def test_no_separator_returns_none_system(db: Database) -> None:
    await PromptsRepo(db).upsert_operator("p", "# variables: x\nJust {x}")
    r = _resolver(db)
    result = await r.render("p", x="text")
    assert result.system_prompt is None
    assert result.user_prompt == "Just text"


async def test_separator_with_empty_system_section(db: Database) -> None:
    await PromptsRepo(db).upsert_operator("p", "# variables: x\n---\nUser: {x}")
    r = _resolver(db)
    result = await r.render("p", x="hello")
    assert result.system_prompt is None
    assert result.user_prompt == "User: hello"


# ── Seed prompts from migration ──────────────────────────────────

async def test_migration_seeds_operator_defaults(db: Database) -> None:
    """Migration 002 seeds the two required operator defaults when table is empty."""
    from astra.db.migrations._002_prompts import SQL as seed_sql
    await db.execute(seed_sql)
    repo = PromptsRepo(db)
    li = await repo.get_operator("linkedin_announcement")
    tw = await repo.get_operator("twitter_announcement")
    assert li is not None, "linkedin_announcement must be seeded by migration"
    assert tw is not None, "twitter_announcement must be seeded by migration"
    assert "{title}" in li.content
    assert "{title}" in tw.content
