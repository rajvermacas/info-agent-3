# Repository Guidelines

## Project Structure & Module Organization

- `src/` contains the application packages:
  - `src/mock_smtp/`: mock SMTP server + REST API (ports 1025/8025)
  - `src/mail_agent/`: LangGraph-based mail agent + A2A JSON-RPC/SSE server (8000) + webhook listener (9000)
  - `src/ui/`: HTMX + Tailwind UI server (8080), templates in `src/ui/templates/`, static assets in `src/ui/static/`
- `tests/` contains `pytest` suites (e.g., `tests/test_mail_agent/`, `tests/test_ui/`).
- `scripts/` contains dev utilities (e.g., `scripts/a2a_client.py`, `scripts/poc_reply_simulator.py`).
- `test_data/` contains sample attachments used by scripts/tests.

## Build, Test, and Development Commands

- Install (editable + dev deps): `python -m venv venv && source venv/bin/activate && pip install -e ".[dev]"`
- Configure env: `cp .env.example .env` (add an LLM key/provider before running the agent)
- Run servers:
  - `uv run mock-smtp`
  - `uv run mail-agent a2a`
  - `uv run ui-server`
- Run a one-off task: `uv run mail-agent run "send mail to ..."`
- Run tests: `pytest` (coverage config lives in `pyproject.toml`)

## Coding Style & Naming Conventions

- Python 3.12+, 4-space indentation, keep imports tidy, prefer type hints for new code.
- Follow existing naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Keep files reasonably sized (project convention: <800 lines when practical).

## Testing Guidelines

- Framework: `pytest` (+ `pytest-asyncio`, `pytest-cov`).
- Conventions: files `test_*.py`, test functions `test_*`, optional `Test*` classes.
- Run targeted suites: `pytest tests/test_mail_agent/` or `pytest tests/test_ui/`.

## Commit & Pull Request Guidelines

- Commits follow Conventional Commits (examples in history): `feat: ...`, `fix(ui): ...`, `docs: ...`.
- PRs should include: a clear description, how to run/verify (`pytest`, relevant `uv run ...`), and UI screenshots when applicable.
- If you add/change env vars, update `.env.example` and document in `README.md`.

## Security & Configuration Tips

- Never commit secrets from `.env`. Prefer `.env.example` for defaults and documentation.
- LLM provider configuration is required for the mail agent; validate with `uv run mail-agent config`.
