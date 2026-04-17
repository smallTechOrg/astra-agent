# Rule: code style

**Scope:** all Python code in this repo (`src/` and `tests/`).

Language, runtime, and library choices are in [`tech-stack.md`](tech-stack.md). This document covers conventions only.

---

## Async

- Every I/O-bound function is `async def`. Blocking calls are confined to narrow, documented spots (e.g. `webbrowser.open()` in the OAuth CLI helper).
- `async with` context managers for clients. No manual `.close()` calls unless inside a context manager's implementation.
- `asyncio.gather()` with `return_exceptions=True` for fan-out where failures should not cancel siblings.
- Never run blocking calls on the event loop. If you must, use `asyncio.to_thread()`.

## Types

- Type hints on all function signatures. Internal variables usually don't need hints unless inference is ambiguous.
- `X | None` over `Optional[X]`, `list[X]` over `List[X]`.
- `from __future__ import annotations` at the top of every module (deferred annotation evaluation).

## Errors

- Raise typed exceptions (`TenantNotFoundError`, `DestinationAuthError`, etc.). Don't raise bare `RuntimeError` or `ValueError` unless that's genuinely what happened.
- Catch narrow, not broad. `except httpx.HTTPStatusError` over `except Exception`, except where [`tenant-isolation.md`](tenant-isolation.md) explicitly requires a broad catch.

## Comments and docstrings

- Default to **no comments**. Names and types carry meaning.
- Short docstrings on public functions, classes, and modules — one paragraph, purpose only. No `Args:` / `Returns:` blocks unless parameter semantics are non-obvious.
- Only comment the **why** — a constraint, a workaround, a non-obvious invariant.

## Structure

- One class or cohesive function group per file.
- Imports ordered: stdlib, third-party, first-party (`astra.*`). `ruff` enforces this.

## Validation

Validate at system edges, not internal ones. User-facing YAML, env vars, HTTP responses, and LLM output get validated. Internal function-to-function calls trust their types.

## Testing

- Every new module in `src/astra/` has a matching `tests/unit/` counterpart.
- Tests are async unless the code under test is truly sync.
- Mock HTTP with `respx`, not custom monkeypatches.
- Tests must run in under 3 seconds each. A slow test is almost always a missing mock.
- Tenant-scoped code: see [`tenant-isolation.md`](tenant-isolation.md) for coverage requirements.

## What to avoid

- **Premature abstraction.** Three similar lines is better than a helper that five callers must understand.
- **Feature flags for features we haven't shipped.** Just write the code.
- **Backwards-compat shims** for code that's never been released.
- **Global singletons.** Explicit dependency passing, always.
- **New dependencies** without a spec change. See [`tech-stack.md`](tech-stack.md).
