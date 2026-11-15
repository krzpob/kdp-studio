# KDP Studio

Automat do generowania kolorowanek pod Amazon KDP: LLM wymyśla zawartość stron, model obrazu generuje line art, a pipeline przygotowuje grafiki do druku (300 DPI).

Specyfikacja MVP: [`docs/requirements.md`](docs/requirements.md).

## Uruchomienie

Wymaga Pythona ≥ 3.12 i [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run kdp-studio generate --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30
```

Na razie `generate` waliduje parametry (FR-01, FR-02), generuje pomysły na strony oraz metadane książki (FR-03) do `output/<temat>_<wiek>_<styl>_<format>/ideas.json`, buduje z nich prompty obrazu (FR-04) do `prompts.json` generuje grafiki (FR-05) i zamienia je w gotowe strony (FR-06): `page_XX.png` w pełnym wymiarze druku KDP (300 DPI, czysta czerń i biel, marginesy według tabeli KDP), do zaimportowania w Canvie i rozciągnięcia na całą stronę. Wersje wektorowe trafiają do `svg/`, surowe wyniki modelu do `raw/`. Obok stron powstaje `canva.md` z instrukcją składania tej książki w Canvie (wymiar projektu, kolejność stron, ustawienia eksportu) i `manifest.json` z parametrami, modelami i statusem każdej strony. Uwaga: każda strona to płatne wywołanie modelu obrazu (ok. $0.02 za grafikę w jakości `low`), a limit budżetu (`--max-cost`, FR-10) jeszcze nie działa. Jakość i model ustawisz w `config/settings.yaml`. Wymaga klucza API OpenAI (osobnego od abonamentu ChatGPT) w zmiennej `OPENAI_API_KEY` albo w pliku `.env`:

```bash
echo 'OPENAI_API_KEY=sk-...' > .env
```

Dostępne profile wieku, stylu i formatu wypisuje `uv run kdp-studio profiles` (albo `profiles age`, `profiles style`, `profiles format`). Profile są w katalogu `config/`, a model i inne ustawienia w `config/settings.yaml`.
