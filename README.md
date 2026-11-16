# KDP Studio

Automat do generowania kolorowanek pod Amazon KDP: LLM wymyśla zawartość stron, model obrazu generuje line art, a pipeline przygotowuje grafiki do druku (300 DPI).

Specyfikacja MVP: [`docs/requirements.md`](docs/requirements.md).

## Uruchomienie

Wymaga Pythona ≥ 3.12 i [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run kdp-studio generate --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30
```

`generate` waliduje parametry (FR-01, FR-02), wymyśla pomysły na strony i metadane książki (FR-03) i weryfikuje je (FR-03a, FR-03b), a potem generuje grafiki (FR-05) i zamienia je w gotowe strony (FR-06). Gotowe strony to `page_XX.png` w pełnym wymiarze druku KDP (300 DPI, czysta czerń i biel, marginesy według tabeli KDP), do zaimportowania w Canvie i rozciągnięcia na całą stronę. Wszystko trafia do `output/<temat>_<wiek>_<styl>_<format>/`. Wersje wektorowe są w `svg/`, a surowe wyniki modelu w `raw/`. Obok stron powstaje `canva.md` z instrukcją składania tej książki w Canvie (wymiar projektu, kolejność stron, ustawienia eksportu) i `manifest.json` z parametrami, modelami i statusem każdej strony.

Uwaga: każda strona to płatne wywołanie modelu obrazu (ok. $0.02 za grafikę w jakości `low`), a limit budżetu (`--max-cost`, FR-10) jeszcze nie działa. Jakość ustawisz flagą `--image-quality` albo w `config/settings.yaml`, tam też jest model. Potrzebny jest klucz API OpenAI (osobny od abonamentu ChatGPT) w zmiennej `OPENAI_API_KEY` albo w pliku `.env`:

```bash
echo 'OPENAI_API_KEY=sk-...' > .env
```

Po weryfikacji pomysłów program sprawdza różnorodność całej książki (FR-03b): ile scen ma kilka postaci i czy te same czynności, miejsca albo przedmioty nie powtarzają się na zbyt wielu stronach. Rozkład liczy program z cech, które model podaje przy każdym pomyśle, a braki naprawia najpierw zamianą z zapasem, potem jedną poprawką modelu. Limity ustawisz w `config/settings.yaml` (`diversity`) i w profilach wieku (`multi_subject_share`), a rozkład jest w `ideas.json` (`diversity`).

### Generowanie krokowe (FR-17)

`generate` to trzy kroki po kolei. Każdy możesz uruchomić osobno i między nimi przejrzeć oraz poprawić wynik:

```bash
uv run kdp-studio ideas --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30
uv run kdp-studio images output/dinozaury_przedszkole_kawaii_square --image-quality low
uv run kdp-studio finalize output/dinozaury_przedszkole_kawaii_square
```

- **Po `ideas`** (pomysły, prompty i manifest, bez grafik, więc tanio) możesz poprawić `scene` w `ideas.json`, usunąć pomysły albo zmienić ich kolejność. Pierwsze pomysły to strony, reszta to zapas. `kdp-studio ideas <katalog> --redo idea_07,idea_19` wymyśla nowe pomysły w miejsce wskazanych.
- **Po `images`** przejrzyj `raw/`. W `manifest.json` możesz ustawić stronie `"action": "regenerate"` albo zmienić `idea_id` na pomysł z zapasu. Możesz też usunąć plik z `raw/` albo podmienić go na własną poprawioną wersję: program ją wykryje i zostawi. Kolejne `kdp-studio images` wykona tylko to, co się zmieniło.
- **`finalize`** nie wywołuje API, więc możesz go powtarzać przy strojeniu obróbki w `config/ages.yaml`.

Każdy krok bez zmian nic nie robi, a przerwany krok wznawiasz, uruchamiając go ponownie.

### Postęp, czasy i logi (NFR-09)

W terminalu kroki `images` i `finalize` pokazują pasek postępu z czasem do końca. Każdy krok kończy się linią `Czas kroku (…)`, a `generate` podsumowuje czasy wszystkich kroków i całości, np. `Czas: pomysły 48 s, grafiki 6 min 12 s, obróbka 2 min 05 s; razem 9 min 07 s.`

Szczegóły trafiają do `kdp-studio.log` w katalogu książki: jeden obiekt JSON w wierszu, dopisywany przez każdy krok (początek i koniec kroku z czasem, każda strona z czasem, tokenami i błędem, odrzucenia QA, ostrzeżenia). Z `--log-level debug` (albo `log_level: debug` w `settings.yaml`) log zapisuje też każde wywołanie API z czasem, tokenami i promptem grafiki. Przykład, czasy obróbki stron:

```bash
jq -r 'select(.event == "page_final") | "\(.name) \(.duration_s) s"' output/<książka>/kdp-studio.log
```

Z flagą `--qa` (albo `qa: true` w `settings.yaml`) każda gotowa strona przechodzi kontrolę jakości modelem z wizją (FR-07): panele lub kolaż, cieniowanie, tekst, otwarte kontury, poziom szczegółów niezgodny z wiekiem, scena niezgodna z opisem. Odrzucona strona trafia do `rejected/page_XX_tryN.png` (powód jest w `manifest.json`), a jej miejsce zajmuje grafika z zapasowego pomysłu, najwyżej 2 ponowienia na stronę (`qa_max_retries`). Ocena jednej strony to ok. 3,6 tys. tokenów wejścia modelu tekstowego.

Dostępne profile wieku, stylu i formatu wypisuje `uv run kdp-studio profiles` (albo `profiles age`, `profiles style`, `profiles format`). Profile są w katalogu `config/`, a model i inne ustawienia w `config/settings.yaml`.
