# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

KDP Studio is a CLI that generates Amazon KDP coloring books: an LLM invents the page scenes and book metadata, an image model draws black-and-white line art (one call per page), and a post-processing pipeline turns each image into a 300 DPI print-ready page.

The MVP spec, [docs/requirements.md](docs/requirements.md), is the source of truth for scope, decisions (D1–D8), functional requirements (FR-01–FR-13), non-functional requirements (NFR-01–NFR-13), and the planned layout. Read it before implementing anything, and cite requirement IDs in commits and PRs. The spec, README and user-facing CLI messages are in Polish. Profile keys are Polish too (`przedszkole`, `dorosli`, …), while image prompts and scene descriptions are in English.

Implemented so far: config loading (§7) and input validation (FR-01, FR-02). `generate` validates and stops; FR-03 onward is not built yet.

## Commands

```bash
uv sync                                    # create .venv with runtime + dev deps
uv run kdp-studio generate --theme "Dinozaury" --age przedszkole --style kawaii --format square
uv run pytest                              # all tests
uv run pytest tests/test_validation.py::test_pages_out_of_range   # single test
uv run pytest --cov=kdp_studio --cov-report=term-missing
uv run ruff check . && uv run ruff format .
uv run mypy                                # strict, covers src/ and tests/ (configured in pyproject)
```

`KDP_STUDIO_CONFIG_DIR` overrides the config directory (default: `config/` at the repo root, resolved from the package path, so it assumes an editable install).

## Tooling notes (NFR-01, NFR-13)

- Python ≥ 3.12, `uv`, `typer`, Pydantic v2. Planned image stack: Pillow, `opencv-python-headless`, potrace bindings, `cairosvg` or `resvg`.
- Typer ≥ 0.29 vendors click privately (`typer._click`); there is no `click` package. Use the public `typer.TyperException`, `typer.Exit` and `typer.Abort`.
- Ruff allows `–` and `×` (`allowed-confusables`) because Polish messages use them, and `docs/` is excluded from ruff.
- CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, so after changing dependencies in `pyproject.toml` run `uv lock` and commit `uv.lock`. Lint and mypy run once; tests run on Linux, macOS and Windows with Python 3.12 and 3.14 (NFR-11). Pre-commit (NFR-13) is still missing.
- Secrets come only from env vars or `.env` (gitignored): `OPENAI_API_KEY`, later `GEMINI_API_KEY`. Keys must never reach logs or `manifest.json`.

## Architecture (spec §8, §12)

Package: `src/kdp_studio/`. Existing modules:

- `config.py`: Pydantic models for every YAML file (`extra="forbid"`, so typos in config fail loudly) and `load_config()`, which raises `ConfigError`. Cross-file checks live in `AppConfig` (e.g. `allowed_ages` must name existing ages; `page_px` must equal `trim_in × dpi`).
- `models.py`: `BookSpec`, the validated input, plus `pages_in_book()`.
- `validation.py`: `validate_book_spec()` collects *all* input errors before raising `InputValidationError`, and returns warnings separately (KDP page minimum, style not meant for the age). Profile keys are checked here, not in `BookSpec`, because that needs the loaded config.
- `cli.py`: typer app with an `ExitCode` enum. Entry point `run()` → `main(argv)`, which runs typer with `standalone_mode=False` so usage errors (bad type, unknown flag) exit with 1 instead of typer's default 2, which §9.3 reserves for partial results. Tests call `main([...])` directly.

Still to come: `pipeline/` and `providers/`.

Flow: `CLI → BookSpec (validation) → IdeaGenerator → PromptBuilder → PageWorker × concurrency (ImageProvider → PostProcessor chain → optional QAChecker) → Manifest`.

Invariants the design depends on:

- **Provider isolation.** `pipeline/` depends only on the `Protocol` interfaces in `providers/base.py` (`TextProvider`, `ImageProvider`, `VisionProvider`, `PostProcessor`). Implementations are chosen from config through a registry (`providers.image = "openai"`). The pipeline must never import a vendor SDK, and a test or lint rule should enforce this. A new provider (Gemini is next) means one new adapter file plus a registry entry, with no changes in `pipeline/`. `ImageRequest.reference_image` is in the contract from day one, even though the OpenAI adapter ignores it in the MVP.
- **One API call = one image** (D4). Never ask a model for several pages in one call, because it starts producing grids and collages. Series consistency comes from a shared style block that is identical across every page prompt (FR-04), plus fixed negative constraints (`no grid, no multiple panels, no collage, no text…`).
- **All ideas in one LLM call** (D5, FR-03). Structured output covering the book metadata plus `pages + ceil(pages * reserve_ratio)` ideas, so the model can keep scenes distinct. The extra ideas are the reserve used when QA rejects a page.
- **Profiles are data, not code** (§7). Age, style, and format profiles in `config/{ages,styles,formats}.yaml` drive both prompt fragments and post-processing parameters (e.g. `min_speck_area`, potrace smoothing, which differ for thick toddler lines and fine adult line work). Quality tuning must not require Python changes. Defaults live in `config/settings.yaml`; CLI flags override them.
- **Post-processing chain** (FR-06): grayscale → 1-bit threshold (Otsu by default) → despeckle → potrace to SVG → render at 300 DPI, fitted into the format's safe area on white with no bleed → `page_XX.png`. Vectorizing instead of upscaling is deliberate (D6), since models return roughly 1–1.5k px and pages need 2550+ px. Each output is checked automatically for exact `page_px`, 300 DPI metadata, pure black and white, and safe-area fit (NFR-07).
- **Manifest as checkpoint** (FR-08–FR-10, NFR-04). `manifest.json` is written incrementally after every page, atomically (temp file, then rename). `--resume` regenerates only pages not marked `ok` and never re-calls the idea LLM. Each API call records its cost, and `--max-cost` stops new work once the budget is exceeded.
- **KDP page math** (FR-02, D8). Single-sided printing means `pages_in_book = pages * 2 + front_matter_pages`, and KDP's paperback minimum is 24.
- **Exit codes** (§9.3): 0 success, 1 validation or config error, 2 partial (missing `ok` pages), 3 budget exceeded, 4 provider error after retries.

## Testing approach (NFR-03)

Unit tests run offline against fake providers (`providers/fake.py`, where `FakeImageProvider` returns prepared PNGs). Post-processing is tested against golden image files. The target is ≥ 80% pipeline coverage.

## Output

Generated books go to `output/<theme-slug>_<age>_<style>_<format>/` (gitignored), containing `manifest.json`, `ideas.json`, `page_XX.png`, `svg/`, `raw/`, and `rejected/`.
