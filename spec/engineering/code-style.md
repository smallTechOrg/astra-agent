# Rule: code style and libraries

**Scope:** all Python code in this repo (the eventual `src/` and `tests/` trees, rebuilt from spec).

Astra is a small-to-medium Python async codebase. Keep it that way.

## Language baseline

- **Python 3.12** (pinned in `.tool-versions`). `requires-python = ">=3.12"` in `pyproject.toml`. Use modern syntax: `X | None` over `Optional[X]`, `list[X]` over `List[X]`, structural pattern matching where it genuinely clarifies.
- **Async by default**. Every I/O-bound function is `async def`. Blocking calls are confined to narrow, documented spots (e.g. `webbrowser.open()` in the OAuth CLI helper).
- **Type hints everywhere** on function signatures. Internal variables usually don't need hints unless inference is ambiguous.

## Library choices

These are the canonical libraries for this repo. Do **not** introduce alternatives without a spec change:

| Purpose | Library | Notes |
|---|---|---|
| HTTP client | `httpx.AsyncClient` | Not `aiohttp`, not `requests`. |
| Database | `aiosqlite` | Not `sqlite3` (sync), not SQLAlchemy. |
| Config / models | `pydantic` v2, `pydantic-settings` | `SecretStr` for secrets. |
| Structured logging | `structlog` | `log.bind(tenant_id=...)` is the norm. |
| Retry / backoff | `tenacity` | `@retry` decorator with `wait_exponential`, `stop_after_attempt`. |
| Scheduler | `APScheduler` (AsyncIOScheduler) | |
| CLI | `click` | |
| YAML | `PyYAML` (already present) | |
| Testing | `pytest`, `pytest-asyncio`, `respx` | `respx` for HTTP mocks. |
| Lint | `ruff` | Zero tolerance for ruff errors on merged code. |
| Type check | `mypy` | `strict = true` for `src/astra/`. |

## Patterns

### Boundaries and validation
Validate at system edges, not internal ones. User-facing YAML, env vars, HTTP responses, and LLM output get validated. Internal function-to-function calls trust their types.

### Errors
- Raise typed exceptions (`TenantNotFoundError`, `DestinationAuthError`, etc.) with specific names. Don't raise bare `RuntimeError` or `ValueError` unless that's genuinely what happened.
- Catch narrow, not broad. `except httpx.HTTPStatusError` over `except Exception`, except where [`tenant-isolation.md`](tenant-isolation.md) explicitly requires a broad catch.

### Comments and docstrings
- Default to **no comments**. Names and types carry meaning.
- Docstrings on public functions, classes, and modules — short. One paragraph describing purpose. No `Args:` / `Returns:` blocks unless the parameter semantics are non-obvious.
- Never write comments that restate what the code does. Only write comments for **why** — a constraint, a workaround, a non-obvious invariant.

### Structure
- One class or cohesive function group per file.
- `from __future__ import annotations` at the top of every module (deferred evaluation of annotations).
- Imports ordered: stdlib, third-party, first-party (`astra.*`). `ruff` enforces this.

### Async
- `async with` context managers for clients. No manual `.close()` calls unless inside a context manager's implementation.
- `asyncio.gather()` with `return_exceptions=True` for fan-out where failures should not cancel siblings. See `SocialDistributor` in current code for pattern (will be rewritten in v2).
- Never run blocking calls on the event loop. If you must, `asyncio.to_thread()`.

## Testing norms

- Every new module in `src/astra/` has a matching `tests/unit/test_<module>.py`.
- Tests are async unless the code under test is truly sync.
- Mock HTTP with `respx`, not custom monkeypatches.
- Tenant-scoped code: see the test-coverage requirement in [`tenant-isolation.md`](tenant-isolation.md).
- Tests must run in <3 seconds each. A slow test is almost always a sign of a missing mock.

## What to avoid

- **Premature abstraction.** Three similar lines is better than a helper function that five callers have to understand.
- **Feature flags for features we haven't shipped.** Just write the code.
- **Backwards-compat shims** for code that's never been released.
- **Global singletons.** Explicit dependency passing, always.
- **New dependencies** without a spec-level justification. Every dependency is a future maintenance cost.
