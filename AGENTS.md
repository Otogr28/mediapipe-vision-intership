# Repository Guidelines

## Project Structure & Module Organization

This repository is a small Python project managed with `uv`. The current entrypoint is `main.py`, which should stay thin and delegate real application behavior to modules as the project grows. Project metadata and dependencies live in `pyproject.toml`, with locked dependency versions in `uv.lock`. The nested `mediapipe-vision-intership/` directory currently contains upstream/reference project material; avoid mixing generated outputs or local experiments into it unless intentionally updating that reference. Runtime data, captures, recordings, model files, and generated media are ignored by `.gitignore`; keep reusable sample assets under `assets/samples/` if they need to be committed.

## Build, Test, and Development Commands

- `uv sync`: create or update the local virtual environment from `pyproject.toml` and `uv.lock`.
- `uv run python main.py`: run the current application entrypoint.
- `uv add <package>`: add a dependency and update the lockfile.
- `uv run pytest`: run the test suite once tests are added.

Use `uv run ...` for project commands so contributors use the pinned environment consistently.

## Coding Style & Naming Conventions

Write Python using 4-space indentation, type hints for public functions, and small functions with clear responsibilities. Use `snake_case` for modules, functions, and variables; use `PascalCase` for classes; reserve uppercase names for constants. Prefer explicit imports and avoid committing notebook scratch work, generated media, or large model artifacts. If formatters or linters are introduced, add them to `pyproject.toml` and document the exact command here.

## Testing Guidelines

No test suite is committed yet. Add tests under `tests/` using `pytest`, with files named `test_<module>.py` and test functions named `test_<behavior>()`. Keep tests focused on observable behavior, especially MediaPipe input/output handling, path validation, and failure cases. Store tiny deterministic fixtures in `tests/fixtures/` or `assets/samples/`, not in ignored output directories.

## Commit & Pull Request Guidelines

This repository has no existing commit history, so use concise imperative commits such as `Add pose detection entrypoint` or `Fix sample asset loading`. Keep each commit focused and include dependency lockfile changes when dependencies change. Pull requests should include a short summary, steps run locally, linked issues when applicable, and screenshots or sample output for visual/media-processing changes. Mention any required local files, models, or environment variables explicitly.

## Security & Configuration Tips

Do not commit `.env` files, private captures, large datasets, or model checkpoints. Provide `.env.example` when configuration becomes necessary, and document required variables in `README.md`.

## Shared Agent Context Rule

This project uses `SHARED.md` as the coordination file between AI agents.
Before starting work, read `SHARED.md`.
After completing meaningful work, append a concise update to `SHARED.md` with what changed, what decisions were made, and what the next agent should know.
Do not overwrite another agent's notes.
Do not remove context unless it is clearly outdated and replaced with better information.

## Codex Startup Hook

For Codex, this `AGENTS.md` file is the project-level instruction hook. At the start of every Codex session in this repository, the first project action must be to read `SHARED.md` and treat its contents as active context before making plans, inspecting unrelated files, or editing anything. Do not modify Claude-specific configuration to enforce this rule.
