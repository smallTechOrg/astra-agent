# Tech stack

**Scope:** implementation language, runtime, and canonical library choices for this repo.

This document records *what* the stack is and *why*. Coding conventions that use this stack live in [`code-style.md`](code-style.md).

---

## Language: Python

Astra is implemented in Python. Reasons:

- The async I/O ecosystem (`asyncio`, `httpx`, `aiosqlite`) covers all of Astra's I/O patterns without threading complexity.
- Pydantic v2 gives first-class config validation and secret handling with minimal boilerplate.
- The operator audience (small teams running their own instance) is most likely to read, debug, and extend Python.
- No compiled build step — `pip install -e .` and run.

Alternatives considered: Go (better binary distribution, worse LLM/HTTP ecosystem at this scale), Node (strong async, weaker typing story for config validation). Neither offered a meaningful advantage for this use case.

---

## Runtime pin

**Python 3.12.5**, pinned in [`.tool-versions`](../../.tool-versions) (managed by [asdf](https://asdf-vm.com/)).

`.tool-versions` is the single source of truth for the runtime version. When the pin changes, update all of the following — nothing else:

| File | Field |
|---|---|
| `.tool-versions` | `python X.Y.Z` — **the pin** |
| `pyproject.toml` | `requires-python = ">=X.Y"` |
| `pyproject.toml` | `[tool.ruff] target-version = "pyXY"` |
| `pyproject.toml` | `[tool.mypy] python_version = "X.Y"` |

No other file should state a Python version. `README.md` and any other prose must reference `.tool-versions` rather than repeat the number.

---

## Canonical libraries

Do **not** introduce alternatives without a spec change. Every dependency is a future maintenance cost.

| Purpose | Library | Why this one |
|---|---|---|
| HTTP client | `httpx.AsyncClient` | Async-native, clean API, `respx` test support. Not `aiohttp` (worse ergonomics), not `requests` (sync). |
| Database | `aiosqlite` | Async SQLite with no ORM overhead. Not `sqlite3` (sync), not SQLAlchemy (too heavy for one schema). |
| Config / models | `pydantic` v2, `pydantic-settings` | Best-in-class validation; `SecretStr` prevents secret leakage. |
| Structured logging | `structlog` | Context binding (`log.bind(tenant_id=...)`) is the right primitive for multi-tenant logging. |
| Retry / backoff | `tenacity` | Declarative `@retry` with `wait_exponential` and `stop_after_attempt`. |
| Scheduler | `APScheduler` (`AsyncIOScheduler`) | Runs inside the existing event loop; cron trigger maps directly to tenant config. |
| CLI | `click` | Composable command groups, `@pass_obj` context pattern, well-tested. |
| YAML | `PyYAML` | Standard; no compelling reason to switch. |
| Testing | `pytest`, `pytest-asyncio`, `respx` | `respx` intercepts `httpx` at the transport layer — no real HTTP in tests. |
| Lint | `ruff` | Replaces flake8 + isort + pyupgrade; fast; zero-config for this project's rules. |
| Type check | `mypy` (`strict = true`) | Catches real bugs; `strict` mode prevents gradual type erosion. |
