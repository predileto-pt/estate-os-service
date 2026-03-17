# ADR-003: Evaluate Lefthook for pre-commit and pre-push git hooks

## Status

Proposed

## Date

2026-03-17

## Context

The project currently has no git hooks enforcing code quality checks before commits or pushes. Developers must manually remember to run `ruff check`, `ruff format`, and `pytest` before pushing. The sibling `applicants-intake-service` already uses Lefthook with the following hooks:

- **pre-commit**: `uv lock`, `ruff format --check`, `ruff check`, `mypy` (parallel, on staged files only)
- **pre-push**: same checks on all files + `pytest` (full test suite)

### Why not just copy the config?

The project does **not** currently use mypy, and adding type-checking to a codebase with ~80 source files and several third-party libraries (Supabase, Reducto, SQLAlchemy, FastAPI, Pydantic, boto3) may require significant effort to reach a passing state.

## Effort Estimate

### Low effort (can adopt immediately)

| Hook | Command | Scope | Notes |
|------|---------|-------|-------|
| `ruff format --check` | pre-commit | staged `.py` files | Already configured in `pyproject.toml`, passes today |
| `ruff check` | pre-commit | staged `.py` files | Already configured, passes today |
| `uv lock` | pre-commit | `pyproject.toml` / `uv.lock` | Ensures lock file stays in sync |
| `pytest` (unit + integration) | pre-push | all test files | ~155 tests, runs in seconds, no Docker needed |

These four hooks can be adopted with zero code changes.

### Medium effort (requires investigation)

| Hook | Command | Effort | Notes |
|------|---------|--------|-------|
| `mypy` | pre-commit | **2-4 hours** | Needs `mypy` added to dev deps, a `[tool.mypy]` config section, and likely `type: ignore` annotations or stub packages for libraries without type support (e.g., `reductoai`, `testcontainers`, `logfire`). Third-party stubs needed: `boto3-stubs`, `types-jwt`. SQLAlchemy and Pydantic have native type support. |

### Optional additions (not in intake-service)

| Hook | Effort | Benefit |
|------|--------|---------|
| `pytest` (database + e2e) on pre-push | Adds ~30s, requires Docker running | Catches DB-level regressions before push |
| Commit message linting (e.g., conventional commits) | ~30 min setup | Consistent git history |

## Benefits

1. **Catch issues early** — formatting and lint errors are caught before they enter the commit history, avoiding fix-up commits.
2. **Consistency** — same checks run for every developer; no reliance on remembering to run linters.
3. **Alignment** — matches the pattern already established in `applicants-intake-service`.
4. **Fast feedback** — pre-commit hooks run only on staged files and execute in parallel (~1-2s).

## Risks

- **mypy adoption friction** — the codebase has never used mypy; enabling it will surface type errors that need fixing or suppressing. This is the only item that requires non-trivial effort.
- **Developer experience** — hooks that are too slow or that fail on unrelated files can frustrate developers. Mitigation: run on staged files only, use `--force-exclude`, keep pre-commit under 5s.

## Recommendation

Adopt Lefthook in two phases:

1. **Now**: add `lefthook.yml` with `ruff format`, `ruff check`, and `uv lock` on pre-commit, plus `pytest` (excluding database/e2e) on pre-push. Zero code changes required.
2. **Later**: add `mypy` to dev dependencies, configure `[tool.mypy]` with gradual strictness, install necessary stubs, and enable the mypy pre-commit hook once the codebase passes.
