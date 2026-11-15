# KDP Studio

Automat do generowania kolorowanek pod Amazon KDP: LLM wymyśla zawartość stron, model obrazu generuje line art, a pipeline przygotowuje grafiki do druku (300 DPI).

Specyfikacja MVP: [`docs/requirements.md`](docs/requirements.md).

## Uruchomienie

Wymaga Pythona ≥ 3.12 i [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run kdp-studio generate --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30
```

Na razie `generate` tylko waliduje parametry (FR-01, FR-02). Dostępne profile wieku, stylu i formatu są w katalogu `config/`.
