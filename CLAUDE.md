# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

KDP Studio is a CLI that generates Amazon KDP coloring books: an LLM invents the page scenes and book metadata, an image model draws black-and-white line art (one call per page), and a post-processing pipeline turns each image into a 300 DPI print-ready page.

The MVP spec, [docs/requirements.md](docs/requirements.md), is the source of truth for scope, decisions (D1–D8), functional requirements (FR-01–FR-13), non-functional requirements (NFR-01–NFR-13), and the planned layout. Read it before implementing anything, and cite requirement IDs in commits and PRs. The spec, README and user-facing CLI messages are in Polish. Profile keys are Polish too (`przedszkole`, `dorosli`, …), while image prompts and scene descriptions are in English.

Implemented so far: config loading (§7), input validation (FR-01, FR-02), idea generation (FR-03), image prompts (FR-04) and the `profiles` command (FR-12). `generate` validates, calls the text LLM once, writes `ideas.json` and `prompts.json`, and stops; FR-05 onward is not built yet. `uv run kdp-studio generate …` makes a real, paid OpenAI call when `OPENAI_API_KEY` is set.

## Commands

```bash
uv sync                                    # create .venv with runtime + dev deps
uv run kdp-studio generate --theme "Dinozaury" --age przedszkole --style kawaii --format square
uv run kdp-studio profiles [age|style|format]   # list profile keys with descriptions (no API call)
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
- Secrets come only from env vars or `.env` (gitignored): `OPENAI_API_KEY`, later `GEMINI_API_KEY`. Keys must never reach logs or `manifest.json`. `.env` is loaded only in `cli.run()`, not in `main()`, so tests never pick up a real key. `describe_openai_error()` drops the provider message for 401s because OpenAI echoes a fragment of the key there.
- `openai` 3.x uses `httpx2` (not `httpx`); build test exceptions with `httpx2.Request`/`httpx2.Response`.

## Architecture (spec §8, §12)

Package: `src/kdp_studio/`. Existing modules:

- `config.py`: Pydantic models for every YAML file (`extra="forbid"`, so typos in config fail loudly) and `load_config()`, which raises `ConfigError`. Cross-file checks live in `AppConfig` (e.g. `allowed_ages` must name existing ages; `page_px` must equal `trim_in × dpi`).
- `models.py`: `BookSpec`, the validated input, plus `pages_in_book()`.
- `validation.py`: `validate_book_spec()` collects *all* input errors before raising `InputValidationError`, and returns warnings separately (KDP page minimum, style not meant for the age). Profile keys are checked here, not in `BookSpec`, because that needs the loaded config.
- `profiles.py` (FR-12): `format_profiles()` renders the `name` and `description` fields from the YAML, plus `allowed_ages` for styles and the default format (`cli.DEFAULT_FORMAT`, shared with `generate`).
- `cli.py`: typer app with an `ExitCode` enum. Entry point `run()` → `main(argv)`, which runs typer with `standalone_mode=False` so usage errors (bad type, unknown flag) exit with 1 instead of typer's default 2, which §9.3 reserves for partial results. Tests call `main([...])` directly; `tests/test_cli.py` has an autouse fixture that swaps `cli.create_text_provider` for `FakeTextProvider` and `chdir`s to `tmp_path`.
- `providers/base.py`: `TextProvider` protocol (`complete_json(system, user, schema) -> (parsed, Usage)`), `Usage`, `ProviderError` (exit 4). `providers/registry.py` maps the names in `settings.yaml` (`providers.text`) to lazily imported classes. `providers/openai_text.py` uses `client.responses.parse(..., text_format=schema)` with the SDK's own retries off (`max_retries=0`), because the SDK also retries permanent 429s such as `insufficient_quota`. Retries go through `providers/retry.py` (`call_with_retries`, 3 attempts, exponential backoff or `Retry-After`); each adapter supplies the transient/permanent decision (`openai_retry_decision`). `providers/fake.py` replays canned responses and records calls.
- `pipeline/ideas.py` (FR-03): `build_prompts()` assembles the English prompt from the age/style/format profiles. The LLM-facing schema (`_LLMIdeas`) deliberately has no min/max constraints; `IdeaGenerator` enforces them afterwards: it drops empty and verbatim-duplicate ideas, assigns ids `idea_01…` itself, trims to `pages + ceil(pages * reserve_ratio)`, dedupes keywords and caps them at 7. A short reserve is a warning; fewer ideas than pages, or invalid metadata, triggers one retry, then `ProviderError`.
- `pipeline/prompts.py` (FR-04): `PromptBuilder(spec, config)`. Each prompt is `Scene: <scene>.` followed by `style_block`, which is identical for every page of a book: style `prompt_fragment`, age `prompt_fragment`, format `composition_hint` and `FIXED_CONSTRAINTS` (the spec's list, verbatim; a test pins it). Prompts are built for reserve ideas too and saved to `prompts.json` until the manifest (FR-08) exists.
- `pipeline/output.py`: `book_dir()` (FR-08 naming, Polish letters transliterated by `slugify`) and `write_json_atomic()` (temp file + `os.replace`). `generate` refuses to overwrite an existing `ideas.json` until `--resume` (FR-09) exists.
- `tests/test_architecture.py` enforces NFR-02 by parsing imports in `pipeline/*.py`, `providers/base.py` and `providers/registry.py`.

Still to come: image providers (FR-05), post-processing, QA, manifest.

Flow: `CLI → BookSpec (validation) → IdeaGenerator → PromptBuilder → PageWorker × concurrency (ImageProvider → PostProcessor chain → optional QAChecker) → Manifest`.

Invariants the design depends on:

- **Provider isolation.** `pipeline/` depends only on the `Protocol` interfaces in `providers/base.py` (`TextProvider`, `ImageProvider`, `VisionProvider`, `PostProcessor`). Implementations are chosen from config through a registry (`providers.image = "openai"`). The pipeline must never import a vendor SDK (enforced by `tests/test_architecture.py`). A new provider (Gemini is next) means one new adapter file plus a registry entry, with no changes in `pipeline/`. `ImageRequest.reference_image` is in the contract from day one, even though the OpenAI adapter ignores it in the MVP.
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
