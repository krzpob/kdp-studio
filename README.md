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

Uwaga: każda strona to płatne wywołanie modelu obrazu (ok. $0.045 za grafikę w jakości `medium`, czyli ok. $2.30 za 50 grafik). Jakość ustawisz flagą `--image-quality` albo w `config/settings.yaml`, tam też jest model. Potrzebny jest klucz API OpenAI (osobny od abonamentu ChatGPT) w zmiennej `OPENAI_API_KEY` albo w pliku `.env`:

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

### Strona „This book belongs to…” (FR-14)

Polecenie `kdp-studio belongs-to <katalog>` dodaje do książki stronę wstępną z miejscem na imię właściciela, w motywie i stylu kolorowanki. Działa po kroku `images`, także na książce już gotowej, i wtedy odświeża `canva.md`. `generate --belongs-to-page` robi to samo jako krok między `images` a `finalize`. Model obrazu rysuje tylko ramkę z elementami motywu wokół pustej tabliczki. Napis „This book belongs to:” i linię na imię wpisuje program czcionką Fredoka (SIL OFL, `assets/fonts/`). Dla najmłodszych są to litery konturowe, które też można pokolorować.

Jeśli tabliczka z modelu nie jest pusta, program generuje ramkę ponownie, najwyżej 2 razy. Potem przechodzi na układ zapasowy: grafika pierwszej strony książki u góry i napis pod nią. Wynik to `front_belongs_to.png` w katalogu książki, który w Canvie jest pierwszy na liście. `canva.md` mówi, że to druga strona wstępna. Napis, pole na tekst i czcionkę ustawisz w `config/settings.yaml` (`belongs_to_page`), a wielkość liter i miejsca na imię w profilach wieku (`belongs_to`). Strona kosztuje jedną grafikę plus ewentualne ponowienia. Po zmianie napisu albo czcionki wystarczy ponownie uruchomić `belongs-to`: program przerysuje tekst bez nowej grafiki. `belongs-to --remove` usuwa stronę z książki (surowa grafika zostaje), a `action: regenerate` we wpisie `front_matter.belongs_to` w manifeście zamawia nową ramkę.

```bash
uv run kdp-studio belongs-to output/<książka> [--qa] [--image-quality low] [--max-cost 1.00]
uv run kdp-studio belongs-to output/<książka> --remove
```

### Okładka (FR-15)

```bash
uv run kdp-studio cover output/<książka> [--cover-page 07] [--thumbnails 03,12,21] \
  [--template PAPERBACK_8.500x8.500_104_BW_WHITE_en_US.png] [--qa] [--back-text]
```

`cover` składa okładkę paperback do KDP w `output/<książka>/cover/`. Wymiary (grzbiet z liczby stron, spad, linie zgięcia, strefy bezpieczne, pole kodu kreskowego) liczy wzorami KDP. Opcjonalny szablon z kalkulatora okładek KDP tylko je sprawdza: szablon dla innej liczby stron albo innego formatu to błąd.

Przód powstaje ze szkicu: grafika wybranej strony z pustym pasem u góry trafia do modelu obrazu jako referencja. Model ją koloruje i dorysowuje tło do krawędzi spadu. Program nakłada na kolor ostre kontury 300 DPI, jeśli kontury modelu się nie przesunęły, a potem wpisuje tytuł i podtytuł czcionką Fredoka: kolorowe litery z czarnym obrysem. Sprawdza też, czy tytuł jest czytelny w miniaturze 160 px z wyników Amazon. Kolorowanie to jedna płatna grafika (plus ponowienia przy błędach) i liczy się do `--max-cost`. `--no-color` daje bezpłatny szkic.

Bez `--cover-page` i `--thumbnails` strony proponuje model z wizją: program składa arkusz kontaktowy z ponumerowanymi miniaturami gotowych stron (`cover/raw/contact_sheet.png`), a model wybiera przód, miniatury tyłu i uzasadnia wybór. `--no-select-pages` bierze pierwszą stronę i strony rozłożone po książce.

Tył i grzbiet to drugie wywołanie modelu obrazu, z gotowym przodem jako referencją. Model z wizją podaje wcześniej wysokość horyzontu i kolory tła przy lewej krawędzi przodu, a prompt każe je kontynuować. Program sprawdza styk grzbietu z przodem (różnica kolorów ΔE w pasach poziomych i położenie horyzontu), w razie potrzeby ponawia (najwyżej `max_retries`), a na koniec wygładza przejście po stronie grzbietu. Na tle tyłu są miniatury stron w ramkach, z dala od pola kodu, opcjonalnie opis książki z metadanych (`--back-text`), a na grzbiecie tytuł, gdy książka ma co najmniej 100 stron.

Kolorowa okładka to 2 płatne grafiki (przód, tył z grzbietem) i 1–3 tanie oceny modelem z wizją (wybór stron, ocena przodu, opcjonalnie QA); wszystko liczy się do `--max-cost`. Z `--qa` model z wizją sprawdza gotową okładkę: czy model obrazu nie dorysował tekstu, czy przód pokazuje wybraną stronę i czy tył pasuje stylem. Odrzucenie zapisuje pliki, ale kończy się kodem 2 (`cover.status: qa_failed`), żebyś obejrzał `cover.png` przed wysłaniem do KDP.

Wynik:
- `cover.pdf` w CMYK do przesłania do KDP;
- `cover.png` i `front.png` w RGB;
- `cover_preview.png` ze strefami i szablonem;
- `cover_proof.png` (symulacja druku) i `cover_gamut.png` (miejsca, gdzie kolor zmieni się w druku).

Okładkę może też zrobić `generate --cover` jako ostatni krok, po `finalize` (domyślnie `cover.in_generate: false` w `config/settings.yaml`). Strony wybiera wtedy model z wizją, pozostałe ustawienia okładki pochodzą z `settings.yaml`, a jej koszt liczy się do tego samego `--max-cost`. Okładka powstaje tylko wtedy, gdy wszystkie strony są gotowe; w przeciwnym razie `generate` ją pomija, a po dokończeniu książki uruchamiasz `cover`.

Do konwersji CMYK potrzebny jest profil ICC, który wskazujesz w `config/settings.yaml` (`cover.cmyk.profile`). KDP żadnego nie podaje; zwykle używa się U.S. Web Coated (SWOP) v2 z pakietu profili Adobe, który pobierasz sam. Do prób na macOS wystarczy `/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc`. Ostateczną kontrolą kolorów jest egzemplarz próbny z KDP.

### Koszt i limit (FR-10)

Program liczy koszt każdego wywołania API z tokenów zwracanych przez API i cennika `api_pricing` w `config/settings.yaml` (ceny przepisane ze strony OpenAI, z datą sprawdzenia). Gdy OpenAI zmieni ceny albo przełączysz model, zaktualizuj ten cennik: model bez ceny to błąd przed pierwszym wywołaniem. Koszt każdej strony, pomysłów i całej książki zapisuje się w `manifest.json` (`cost_usd`), a konsola pokazuje koszt stron, kroków i podsumowanie `generate`.

`--max-cost` (domyślnie `max_cost_usd: 5.00` z `settings.yaml`) to limit jednego uruchomienia `ideas`, `images` albo `generate`. Po jego przekroczeniu strony w toku się kończą, nowe nie startują, manifest dostaje status `budget_exceeded`, a program kończy się kodem 3. Brakujące strony dokończysz tak:

```bash
uv run kdp-studio images output/<książka> --max-cost 10
```

### Postęp, czasy i logi (NFR-09)

W terminalu kroki `images` i `finalize` pokazują pasek postępu z czasem do końca. Każdy krok kończy się linią `Czas kroku (…)`, a `generate` podsumowuje czasy wszystkich kroków i całości, np. `Czas: pomysły 48 s, grafiki 6 min 12 s, obróbka 2 min 05 s; razem 9 min 07 s.`

Szczegóły trafiają do `kdp-studio.log` w katalogu książki: jeden obiekt JSON w wierszu, dopisywany przez każdy krok (początek i koniec kroku z czasem, każda strona z czasem, tokenami i błędem, odrzucenia QA, ostrzeżenia). Z `--log-level debug` (albo `log_level: debug` w `settings.yaml`) log zapisuje też każde wywołanie API z czasem, tokenami i promptem grafiki. Przykład, czasy obróbki stron:

```bash
jq -r 'select(.event == "page_final") | "\(.name) \(.duration_s) s"' output/<książka>/kdp-studio.log
```

Z flagą `--qa` (albo `qa: true` w `settings.yaml`) każda gotowa strona przechodzi kontrolę jakości modelem z wizją (FR-07): panele lub kolaż, cieniowanie, tekst, otwarte kontury, poziom szczegółów niezgodny z wiekiem, scena niezgodna z opisem oraz temat, którego nie widać w samym czarno-białym rysunku (np. zimowy brzeg, który bez kolorów może być letnią plażą). Odrzucona strona trafia do `rejected/page_XX_tryN.png` (powód jest w `manifest.json`) i jest generowana ponownie z tego samego pomysłu, najwyżej 2 razy (`qa_max_retries`). Gdy to nie pomoże, strona bierze zapasowy pomysł, łącznie najwyżej 2 pomysły na stronę (`qa_max_ideas`). Ocena jednej strony to ok. 3,6 tys. tokenów wejścia modelu tekstowego.

Dostępne profile wieku, stylu i formatu wypisuje `uv run kdp-studio profiles` (albo `profiles age`, `profiles style`, `profiles format`). Profile są w katalogu `config/`, a model i inne ustawienia w `config/settings.yaml`.
