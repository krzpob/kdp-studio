# KDP Studio: generator kolorowanek (MVP)

Specyfikacja wymagań na potrzeby implementacji. Dokument zbiera ustalenia z sesji projektowej z 15.11.2026.

---

## 1. Cel

Narzędzie CLI, które na podstawie kilku parametrów (temat, wiek odbiorcy, styl, format, liczba stron) generuje komplet grafik do kolorowanki pod Amazon KDP:

1. **LLM** wymyśla unikalne sceny na każdą stronę i metadane książki.
2. **Model obrazu** generuje czarno-biały line art, jedno wywołanie na stronę.
3. **Post-processing** zamienia wynik na grafikę gotową do druku (czysta czerń i biel, 300 DPI, marginesy).

Wynik MVP to **jeden katalog** z grafikami i plikami metadanych. Każda grafika to gotowa, pełna strona (z marginesami), którą importuje się do **Canvy**. Tam użytkownik składa PDF wnętrza książki.

## 2. Zakres

### W zakresie MVP
- CLI z parametrami wejściowymi (sekcja 5).
- Generowanie pomysłów na strony i metadanych książki (tytuł, opis, słowa kluczowe).
- Generowanie grafik przez **OpenAI Image API**.
- Profile wieku, stylu i formatu w plikach konfiguracyjnych (YAML).
- Post-processing do gotowych stron PNG w wymiarach druku KDP (pełna strona z marginesami), które importuje się do Canvy bez dalszej obróbki (FR-06).
- Instrukcja składania książki w Canvie, generowana dla każdej książki (FR-08, sekcja 10.1).
- Opcjonalna automatyczna kontrola jakości (QA) przez model z wizją.
- Wznawianie przerwanego generowania, śledzenie kosztów i limit budżetu.

### Poza zakresem MVP (roadmapa, sekcja 13)
- Składanie PDF wnętrza książki w skrypcie. W MVP robi to użytkownik w Canvie (D9). Automatyczne składanie to opcjonalny etap 2.
- Okładka (projektowana ręcznie w Canvie albo w pakiecie Adobe).
- Adapter Gemini API (Nano Banana). Architektura musi go umożliwiać od początku.
- Adapter Adobe Firefly.
- Interfejs graficzny (Streamlit, Gradio albo React).
- Publikacja w KDP.

## 3. Kluczowe decyzje

| # | Decyzja | Uzasadnienie |
|---|---|---|
| D1 | **Python + CLI**, bez Django i Reacta | Wynikiem jest katalog plików, a UI nic nie wnosi do jakości grafik. Python ma najlepszy ekosystem do obróbki obrazu (Pillow, OpenCV, potrace) i oficjalne SDK dostawców AI. |
| D2 | **Grafiki z OpenAI Image API** na start, **Gemini API jako następny adapter** | Dostawca obrazów jest wymienny przez interfejs `ImageProvider`. Zmiana dostawcy to nowa klasa adaptera i zmiana konfiguracji, bez zmian w pipeline. |
| D3 | **Firefly odrzucony w MVP** | API Firefly Services to produkt enterprise (kontrakt, wysoki próg wejścia). Kredyty z abonamentu Creative Cloud nie działają przez API. Pakiet Adobe zostaje do ręcznej pracy nad okładkami i poprawkami. |
| D4 | **Jedno wywołanie API = jedna grafika** | Doświadczenie z ChatGPT: proszony o serię model zaczyna generować „zestawy” (siatki, kolaże). Wywołania API są bezstanowe, więc problem znika, a spójność serii zapewnia wspólny blok stylu w promptach. |
| D5 | **Pomysły na strony w jednym wywołaniu LLM** | Model widzi całą listę naraz i pilnuje, żeby sceny się nie powtarzały. Generuje też ok. 20% zapasu na strony odrzucone przez QA. |
| D6 | **Wektoryzacja (potrace), a potem render do 300 DPI** | Modele zwracają ok. 1–1.5k px, a strona potrzebuje 2550+ px. Wektoryzacja daje idealnie ostre linie, czego zwykły upscale nie zapewnia. |
| D7 | **Formaty: `letter` (8.5"×11", pion) i `square` (8.5"×8.5")** | Dwa najpopularniejsze formaty kolorowanek na KDP. Formatów poziomych KDP nie obsługuje w tym rozmiarze. |
| D8 | **Druk jednostronny** (grafika, potem pusta strona) | Standard w kolorowankach, bo kredki i flamastry nie przebijają na następną grafikę. Wpływa na liczenie stron (FR-02). |
| D9 | **PDF wnętrza składany w Canvie**, nie w skrypcie | Canva daje kontrolę nad stroną tytułową i układem bez pisania kodu. Skrypt dostarcza pełne strony PNG, które wystarczy rozciągnąć na całą stronę projektu. Do Canvy trafia PNG, a nie SVG: Canva przyjmuje SVG tylko do 3 MB, 150–200 px szerokości i w profilu SVG 1.1, a gęsty line art z potrace przekracza te limity. |

## 4. Pojęcia

- **Strona kolorowanki (page):** jedna grafika do kolorowania.
- **Strona książki:** strona fizyczna. Przy druku jednostronnym 1 grafika = 2 strony książki.
- **Profil wieku / stylu / formatu:** zestaw parametrów w YAML, z którego składa się prompt i parametry obróbki.
- **Zapasowy pomysł (reserve idea):** dodatkowa scena używana, gdy strona nie przejdzie QA.

## 5. Parametry wejściowe

| Parametr | Typ | Wymagany | Przykład | Opis |
|---|---|---|---|---|
| `--theme` | string | tak | `"Dinozaury"` | Tematyka lub roboczy tytuł kolorowanki |
| `--age` | enum | tak | `przedszkole` | `przedszkole`, `wczesnoszkolne`, `szkolne`, `nastolatki`, `dorosli` |
| `--style` | string (klucz profilu) | tak | `kawaii` | Klucz z `config/styles.yaml` |
| `--format` | enum | nie (domyślnie `letter`) | `square` | `letter` (8.5"×11") albo `square` (8.5"×8.5") |
| `--pages` | int | nie (domyślnie `30`) | `30` | Liczba grafik (stron kolorowanki) |

Parametry techniczne opisuje sekcja 9.

## 6. Wymagania funkcjonalne

### FR-01: Walidacja wejścia
- Wszystkie parametry są walidowane przed pierwszym wywołaniem API.
- Nieznany `--age`, `--style` albo `--format` kończy program błędem z listą dozwolonych wartości.
- `--pages` musi być w zakresie 1–200.

### FR-02: Walidacja liczby stron względem KDP
- Program liczy `pages_in_book = pages * 2 + front_matter_pages` (druk jednostronny, `front_matter_pages` z konfiguracji, domyślnie 2: strona tytułowa i „This book belongs to…”).
- Jeśli `pages_in_book < 24` (minimum KDP dla paperbacka), program pokazuje ostrzeżenie z minimalną poprawną liczbą grafik. Z flagą `--strict` kończy się błędem.
- Jeśli `pages_in_book` przekracza ostatni próg tabeli marginesów KDP (sekcja 7.4), program kończy się błędem walidacji.

### FR-03: Generowanie pomysłów i metadanych książki
- **Jedno** wywołanie LLM ze strukturyzowanym wyjściem (JSON Schema lub structured outputs).
- Wejście promptu: temat, profil wieku, profil stylu, format, liczba stron.
- Wyjście (`ideas.json`):
  - `book`: `title`, `subtitle`, `description` (pod listing KDP), `keywords` (do 7);
  - `pages`: lista `pages + ceil(pages * reserve_ratio)` pomysłów (`reserve_ratio` domyślnie 0.2), każdy z polami `id`, `title`, `scene` (opis sceny po angielsku, gotowy do promptu), `elements` (lista obiektów).
- Pomysły muszą:
  - być unikalne w obrębie książki (różne sceny, nie tylko inne sformułowania);
  - pasować do formatu: `square` to centralny obiekt lub kompozycja koncentryczna, `letter` to postać lub scena w pionie;
  - pasować do wieku: liczba obiektów i złożoność sceny zgodne z profilem wieku.
- Treści nie mogą zawierać postaci chronionych prawem autorskim ani znaków towarowych. LLM dostaje to jako twarde ograniczenie.

### FR-04: Budowanie promptów obrazu
- Prompt dla każdej strony składa się z: opisu sceny z FR-03, **wspólnego bloku stylu** (identycznego dla wszystkich stron książki), fragmentu z profilu wieku i fragmentu z profilu formatu.
- Każdy prompt zawiera stałe ograniczenia: `black and white line art, coloring book page, single illustration, one scene, pure white background, closed outlines, no shading, no grayscale, no text, no grid, no multiple panels, no collage, no frame`.
- Gotowy prompt zapisuje się w manifeście (FR-08), żeby dało się odtworzyć i debugować wynik.

### FR-05: Generowanie grafik
- Jedno wywołanie `ImageProvider.generate()` na stronę.
- Równoległość konfigurowalna (`--concurrency`, domyślnie 4).
- Ponawianie z wykładniczym odczekiwaniem (backoff) przy błędach 429 i 5xx, maks. 3 próby na wywołanie.
- Adapter mapuje proporcje formatu na rozmiar obsługiwany przez model (sekcja 8). Jeśli model obsługuje dowolne wymiary, adapter używa dokładnych proporcji.
- Surowy wynik zapisuje się do `raw/page_XX.png` przed obróbką.

### FR-06: Post-processing do druku (strony gotowe do importu w Canvie)
Kolejne kroki (implementacje `PostProcessor`):
1. konwersja do skali szarości;
2. progowanie do czerni i bieli (próg konfigurowalny, domyślnie Otsu), jako krok pośredni przed wektoryzacją;
3. usunięcie drobnego szumu (izolowane piksele i plamki poniżej progu powierzchni);
4. wektoryzacja przez potrace do SVG i zapis w `svg/page_XX.svg`. SVG to **archiwum** (np. do ręcznych poprawek), a nie plik do importu w Canvie (D9);
5. render SVG do pełnego wymiaru strony `page_px`:
   - grafika wpasowana z zachowaniem proporcji w obszar treści, czyli stronę pomniejszoną o margines `margin_in` **z każdej strony**, i wyśrodkowana;
   - `margin_in = max(safe_margin_in, outside_min_in, gutter_in(pages_in_book))`, gdzie `gutter_in(pages_in_book)` to margines przy grzbiecie z tabeli KDP (sekcja 7.4), a `pages_in_book` liczy się jak w FR-02. Margines liczy się raz na książkę, więc wszystkie strony mają identyczne marginesy;
   - margines symetryczny, bo program nie wie, po której stronie grzbietu grafika wyląduje w Canvie (zależy to od liczby stron wstępnych i od składania). Ten sam plik jest poprawny na stronie lewej i prawej. Kosztem jest nieco mniejsza grafika przy zewnętrznej krawędzi;
   - nieprzezroczyste białe tło, bez kanału alfa (KDP wymaga spłaszczenia przezroczystości);
   - po renderze ponowne progowanie, żeby wygładzanie krawędzi (antyaliasing) nie zostawiło szarych pikseli;
6. zapis `page_XX.png`:
   - **8-bit grayscale** (tryb `L`), wyłącznie wartości 0 i 255, bez kanału alfa;
   - metadane DPI = 300;
   - limity importu Canvy (PNG < 50 MB, ≤ 250 mln pikseli) są spełnione z zapasem: strona letter to ok. 8.4 mln pikseli.

Wymiary pochodzą z profilu formatu (sekcja 7.3), a marginesy z profilu formatu i tabeli KDP (sekcja 7.4).

Przykłady przy `safe_margin_in: 0.5` i `front_matter_pages: 2`:

| `--pages` | `pages_in_book` | Gutter KDP | `margin_in` |
|---|---|---|---|
| 30 | 62 | 0.375" | 0.5" |
| 100 | 202 | 0.5" | 0.5" |
| 200 | 402 | 0.625" | 0.625" |

**Kryterium akceptacji:** w Canvie, w projekcie o wymiarach `trim_in` profilu, plik rozciągnięty na całą stronę daje poprawne marginesy bez skalowania ani przycinania.

### FR-07: Kontrola jakości (QA), opcjonalna
- Włączana flagą `--qa` (domyślnie wyłączona w MVP).
- Model z wizją ocenia każdą grafikę po FR-06 i zwraca JSON: `{pass: bool, issues: [...]}`.
- Kryteria odrzucenia: kilka paneli, siatka lub kolaż; cieniowanie lub szarości; tekst lub litery; otwarte kontury uniemożliwiające kolorowanie; poziom szczegółowości niezgodny z profilem wieku; elementy niezgodne z opisem sceny.
- Odrzucona strona jest generowana ponownie z **zapasowego pomysłu**. Maks. 2 ponowienia na pozycję, potem strona dostaje status `failed` w manifeście.
- Program kończy się sukcesem, jeśli jest co najmniej `--pages` stron ze statusem `ok`. W przeciwnym razie zwraca kod wyjścia 2 (sekcja 9.3).

### FR-08: Struktura wyjścia i manifest
- Katalog wyjściowy: `<output-dir>/<slug-tematu>_<age>_<style>_<format>/` (np. `output/dinozaury_przedszkole_kawaii_square/`).
- Zawartość: patrz sekcja 10.
- Gotowe strony leżą w katalogu głównym książki jako `page_XX.png`, z numerem dopełnionym zerami do długości największego numeru (min. 2 cyfry, np. `page_01` … `page_30`). Kolejność alfabetyczna = kolejność stron, więc po przeciągnięciu całej paczki do Canvy strony są we właściwej kolejności.
- W katalogu głównym nie ma innych plików PNG (surowe i odrzucone są w podkatalogach), żeby do Canvy dało się zaznaczyć i przesłać wszystkie pliki naraz.
- Program zapisuje `canva.md`: instrukcję składania tej konkretnej książki (wymiar projektu, liczba grafik i stron książki, kolejność stron wstępnych i pustych, ustawienia eksportu). Treść według sekcji 10.1.
- `manifest.json` zawiera parametry wejściowe, wersję narzędzia, użytych dostawców i modele, `pages_in_book` i użyty `margin_in` (FR-06) oraz dla każdej strony: id pomysłu, prompt, status, liczbę prób, koszt, czas, wynik QA.
- Manifest jest zapisywany przyrostowo po każdej stronie, żeby przerwanie nie gubiło postępu.

### FR-09: Wznawianie
- `--resume <katalog>` wczytuje `manifest.json` i `ideas.json` i generuje tylko strony bez statusu `ok`.
- Ponowne uruchomienie nie wywołuje ponownie LLM dla pomysłów ani nie generuje gotowych stron (idempotentność).

### FR-10: Koszty i limit budżetu
- Każde wywołanie API zapisuje szacowany koszt (z cennika w konfiguracji albo z `usage` zwracanego przez API).
- `--max-cost <USD>` (domyślnie 5.00): po przekroczeniu limitu program kończy bieżące zadania, nie startuje nowych i zapisuje manifest (status `budget_exceeded`).
- Na końcu program wypisuje podsumowanie: liczbę stron ok/failed, łączny koszt i czas.

### FR-11: Tryb próbny (dry run)
- `--dry-run` uruchamia tylko FR-01–FR-04: zapisuje `ideas.json` i prompty, bez generowania grafik. Służy do taniego strojenia profili.

### FR-12: Podgląd profili
- Komenda `profiles` wypisuje dostępne wartości `age`, `style` i `format` z krótkimi opisami z YAML.

### FR-13: Przypomnienie o ujawnieniu AI
- `manifest.json` i podsumowanie w konsoli zawierają informację, że przy publikacji w KDP trzeba zaznaczyć *AI-generated content* (obrazy).

## 7. Profile (konfiguracja YAML)

Profile są danymi, nie kodem: strojenie jakości nie może wymagać zmian w Pythonie.

### 7.1 Profile wieku: `config/ages.yaml`

| Klucz | Linia | Obiekty | Tło | Wypełnienia | Fragment promptu (szkic) |
|---|---|---|---|---|---|
| `przedszkole` | bardzo gruba | 1 duży, proste kształty | brak | duże, zamknięte pola | `very thick bold outlines, one large simple subject, minimal details, no background, large closed areas, for toddlers` |
| `wczesnoszkolne` | gruba | 1–3 | proste | średnie | `thick clean outlines, simple scene with 1-3 subjects, simple background, for kids 6-8` |
| `szkolne` | średnia | pełna scena | tak | więcej detali | `medium outlines, full scene, moderate detail, for kids 9-12` |
| `nastolatki` | cienka | scena, stylizacja | pełne | wzory | `fine clean lines, detailed scene, decorative patterns, for teens` |
| `dorosli` | bardzo cienka | wzory, mandale, zentangle | gęste | drobne pola | `fine intricate line work, highly detailed patterns, many small areas to color, for adults` |

Każdy profil ma też parametry obróbki (np. `min_speck_area`, wygładzanie potrace), bo cienkie linie dla dorosłych wymagają innego progowania niż grube linie dla przedszkolaków.

### 7.2 Profile stylu: `config/styles.yaml`

Lista otwarta. Startowe propozycje: `kawaii`, `cartoon`, `realistic`, `mandala`, `boho`, `manga`, `zentangle`.
Każdy styl ma: `name`, `description`, `prompt_fragment` i opcjonalnie `allowed_ages` (np. `zentangle` tylko dla `nastolatki` i `dorosli`). Niedozwolone połączenie wieku i stylu daje ostrzeżenie.

### 7.3 Profile formatu: `config/formats.yaml`

```yaml
letter:            # 8.5" × 11", pion
  trim_in: [8.5, 11]
  dpi: 300
  page_px: [2550, 3300]
  aspect: "3:4"
  safe_margin_in: 0.5     # nasz minimalny margines (wygoda kolorowania); KDP wymaga ≥ 0.25"
  composition_hint: "vertical composition, subject fills the portrait frame"
square:            # 8.5" × 8.5"
  trim_in: [8.5, 8.5]
  dpi: 300
  page_px: [2550, 2550]
  aspect: "1:1"
  safe_margin_in: 0.5
  composition_hint: "centered composition, single focal subject or concentric design"
```

Bez spadu (bleed): grafika zawsze mieści się w obszarze bezpiecznym na białym tle.

Profil formatu nie ma pola `gutter_in`: margines przy grzbiecie zależy od liczby stron książki, a nie od formatu (sekcja 7.4).

### 7.4 Marginesy KDP: `config/settings.yaml`

Wartości z tabeli marginesów KDP dla druku bez spadu. Kolumna „z spadem” (≥ 0.375" na zewnątrz) nie dotyczy MVP, bo nie używamy spadu.

```yaml
kdp_margins:
  outside_min_in: 0.25          # zewnętrzne marginesy bez spadu: co najmniej 0.25"
  gutter_by_pages:              # margines przy grzbiecie wg liczby stron książki
    - {max_pages: 150, gutter_in: 0.375}   # 24–150
    - {max_pages: 300, gutter_in: 0.5}     # 151–300
    - {max_pages: 500, gutter_in: 0.625}   # 301–500
    - {max_pages: 700, gutter_in: 0.75}    # 501–700
    - {max_pages: 828, gutter_in: 0.875}   # 701–828
```

Zasady:
- `gutter_in(pages_in_book)` to wartość z pierwszego wiersza, dla którego `pages_in_book ≤ max_pages`.
- Walidacja konfiguracji: wiersze rosną według `max_pages` i `gutter_in`, a `safe_margin_in` każdego formatu jest ≥ `outside_min_in`.
- `pages_in_book` większe niż ostatni `max_pages` to błąd walidacji (FR-02). Przy limicie `--pages` 200 i domyślnych 2 stronach wstępnych książka ma maks. 402 strony, więc ten przypadek wystąpi tylko przy zmienionej konfiguracji.
- Gdy KDP zmieni tabelę, aktualizuje się tylko YAML.

## 8. Architektura i API wewnętrzne

### 8.1 Pipeline

```
CLI (typer)
  └─ BookSpec (walidacja: FR-01, FR-02)
      ├─ IdeaGenerator ── TextProvider ──► ideas.json            (FR-03)
      ├─ PromptBuilder ◄─ ages/styles/formats.yaml               (FR-04)
      ├─ PageWorker × concurrency                                (FR-05..07)
      │    ├─ ImageProvider.generate() ──► raw/page_XX.png
      │    ├─ PostProcessor chain      ──► svg/, page_XX.png
      │    └─ QAChecker (opcjonalnie)  ──► pass / użyj zapasu
      └─ Manifest (zapis przyrostowy, koszty, wznawianie)        (FR-08..10)
```

### 8.2 Interfejsy (szkic, `typing.Protocol`)

```python
class TextProvider(Protocol):
    def complete_json(self, system: str, user: str, schema: type[BaseModel]) -> tuple[BaseModel, Usage]: ...

class ImageProvider(Protocol):
    name: str
    def supported_aspects(self) -> list[str]: ...
    def generate(self, req: ImageRequest) -> ImageResult: ...
    # ImageRequest: prompt, aspect, quality, seed (opcjonalnie), reference_image (opcjonalnie)
    # ImageResult: png_bytes, width, height, usage/cost, raw_response_meta

class VisionProvider(Protocol):
    def assess(self, image_png: bytes, instructions: str, schema: type[BaseModel]) -> tuple[BaseModel, Usage]: ...

class PostProcessor(Protocol):
    def process(self, img: Image, ctx: PageContext) -> Image: ...
```

Zasady:
- Pipeline zależy wyłącznie od interfejsów. Implementacje są wybierane z konfiguracji przez rejestr (`providers.image = "openai"`).
- **Dodanie Gemini** = nowy plik `providers/gemini_image.py` z klasą implementującą `ImageProvider` i wpis w rejestrze. Zero zmian w `pipeline/`.
- `ImageRequest.reference_image` jest w kontrakcie od początku (pierwsza zaakceptowana strona jako referencja stylu), nawet jeśli adapter OpenAI w MVP go ignoruje.
- Modele danych (`BookSpec`, `PageIdea`, `PageResult`, `Manifest`) w Pydantic v2.

### 8.3 Dostawcy w MVP

| Rola | Dostawca | Model (konfigurowalny) | Uwagi |
|---|---|---|---|
| Pomysły (tekst) | OpenAI | aktualny model GPT z rodziny 5.x, wersja mini (ustalić przy implementacji) | structured outputs |
| Grafiki | OpenAI Image API (`images.generate`) | `gpt-image-2.5-flare` (szybki, „everyday”); alternatywnie `gpt-image-2.5-sunburst` (najwyższa jakość) | `gpt-image-1` wyłączony 23.10.2026; przypinać pełną nazwę snapshotu |
| QA (wizja) | OpenAI | ten sam model co do pomysłów | tylko z `--qa` |

Mapowanie rozmiarów dla OpenAI: `square` → `1024x1024`, `letter` → `1024x1536` (proporcja 2:3; różnica względem 3:4 wyrównywana białym marginesem w FR-06). Jeśli wybrany model obsługuje dowolne wymiary, adapter używa wymiarów 3:4.

**Uwaga:** abonament ChatGPT nie obejmuje API. Potrzebny jest osobny klucz API OpenAI z włączonymi płatnościami (platform.openai.com).

### 8.4 Następny adapter: Gemini (Nano Banana)
- Model: `Nano Banana 2.1` (Gemini API, płatność za obraz). Natywnie obsługuje proporcje `1:1` i `3:4` oraz obrazy referencyjne.
- Klucz: `GEMINI_API_KEY` z Google AI Studio.
- Wymagania wobec adaptera są takie same jak w FR-05.

## 9. Interfejs CLI

### 9.1 Komendy

```bash
# Generowanie książki
kdp-studio generate \
  --theme "Dinozaury" \
  --age przedszkole \
  --style kawaii \
  --format square \
  --pages 30 \
  [--output-dir ./output] \
  [--concurrency 4] \
  [--max-cost 5.00] \
  [--qa] \
  [--dry-run] \
  [--strict] \
  [--image-provider openai] \
  [--seed 1234] \
  [--verbose]

# Wznowienie przerwanego generowania
kdp-studio generate --resume ./output/dinozaury_przedszkole_kawaii_square

# Lista dostępnych profili
kdp-studio profiles [age|style|format]
```

### 9.2 Konfiguracja i sekrety
- Sekrety wyłącznie w zmiennych środowiskowych lub `.env` (w `.gitignore`): `OPENAI_API_KEY`, później `GEMINI_API_KEY`.
- Ustawienia domyślne w `config/settings.yaml` (dostawcy, modele, cenniki, `reserve_ratio`, `front_matter_pages`, domyślna równoległość). Flagi CLI nadpisują `settings.yaml`.

### 9.3 Kody wyjścia

| Kod | Znaczenie |
|---|---|
| 0 | Sukces: wszystkie strony `ok` |
| 1 | Błąd walidacji wejścia lub konfiguracji |
| 2 | Zakończono częściowo: brakuje stron `ok` (failed lub QA) |
| 3 | Przekroczony budżet (`--max-cost`) |
| 4 | Błąd dostawcy API po wyczerpaniu ponowień |

## 10. Struktura katalogu wyjściowego

```
output/dinozaury_przedszkole_kawaii_square/
├── manifest.json
├── ideas.json
├── canva.md                        # instrukcja składania w Canvie (sekcja 10.1)
├── page_01.png … page_30.png      # pełne strony do importu w Canvie, 300 DPI
├── svg/page_01.svg …               # archiwum wektorowe (nie do Canvy)
├── raw/page_01.png …               # surowe wyniki z modelu
└── rejected/page_07_try1.png …     # odrzucone przez QA (z powodem w manifeście)
```

Przykład wpisu strony w `manifest.json`:

```json
{
  "page": 7,
  "idea_id": "idea_07",
  "status": "ok",
  "attempts": 2,
  "provider": "openai",
  "model": "gpt-image-2.5-flare",
  "prompt": "…",
  "qa": {"pass": true, "issues": []},
  "cost_usd": 0.08,
  "duration_s": 14.2,
  "files": {"png": "page_07.png", "svg": "svg/page_07.svg", "raw": "raw/page_07.png"}
}
```

### 10.1 Składanie książki w Canvie

Treść `canva.md` (wartości w nawiasach wypełnia program):

1. Utwórz projekt o wymiarach własnych `[trim_in]` cali (np. 8.5 × 11 in).
2. Strony wstępne: `[front_matter_pages]` (domyślnie strona tytułowa i „This book belongs to…”).
3. Prześlij wszystkie `page_XX.png` naraz.
4. Każdą grafikę wstaw na osobną stronę i rozciągnij na całą stronę. Marginesy (`[margin_in]` cala z każdej strony, zgodnie z tabelą KDP dla `[pages_in_book]` stron) są już w pliku, więc niczego nie skaluj ani nie przycinaj.
5. Po każdej grafice dodaj pustą stronę (druk jednostronny, D8). Razem `[pages_in_book]` stron.
6. Pobierz jako **PDF Print** z zaznaczonym **Flatten PDF**. Bez spadu (bleed).
7. Przy publikacji w KDP zaznacz *AI-generated content* dla obrazów (FR-13).

## 11. Wymagania pozafunkcjonalne

| ID | Obszar | Wymaganie |
|---|---|---|
| NFR-01 | Technologia | Python ≥ 3.12, zarządzanie projektem przez `uv`, CLI w `typer`, modele w `pydantic` v2, obraz: `Pillow`, `opencv-python-headless`, `pypotrace` lub `potracer`, render SVG: `cairosvg` lub `resvg`. |
| NFR-02 | Wymienność dostawców | Zmiana dostawcy grafik = nowy adapter + zmiana konfiguracji. Pipeline nie importuje SDK dostawców (sprawdzane testem lub regułą lintera). |
| NFR-03 | Testowalność | Testy jednostkowe na fałszywych dostawcach (`FakeImageProvider` zwraca przygotowane PNG), bez sieci. Post-processing testowany na plikach-wzorcach. Pokrycie pipeline ≥ 80%. |
| NFR-04 | Niezawodność | Ponowienia z backoffem, przyrostowy manifest, wznawianie (FR-09). Przerwanie Ctrl+C nie uszkadza manifestu (zapis atomowy: plik tymczasowy, potem zmiana nazwy). |
| NFR-05 | Wydajność | 30 stron przy `--concurrency 4` w ≤ 15 min (bez QA), zależnie od limitów API. Post-processing jednej strony ≤ 5 s. |
| NFR-06 | Koszt | Docelowo ≤ 3 USD za 30-stronicową książkę z QA. Twardy limit przez `--max-cost`. |
| NFR-07 | Jakość druku | Każdy `page_XX.png` ma dokładnie wymiary `page_px` profilu formatu, metadane 300 DPI, tryb 8-bit grayscale bez kanału alfa, wyłącznie wartości 0 i 255, a czarne piksele mieszczą się w obszarze treści (FR-06). Sprawdzane automatycznie po zapisie. |
| NFR-08 | Odtwarzalność | Manifest zawiera wszystko, czego potrzeba do ponownego wygenerowania strony (prompt, model, snapshot, seed, jeśli dostępny). |
| NFR-09 | Obserwowalność | Logi strukturalne (poziomy INFO/DEBUG), pasek postępu w konsoli, podsumowanie kosztów i czasu na końcu. |
| NFR-10 | Bezpieczeństwo | Klucze API nigdy nie trafiają do logów, manifestu ani repozytorium. |
| NFR-11 | Przenośność | Działa na Linux, macOS i Windows. Zależności natywne (cairo, potrace) opisane w README albo zastąpione czysto pythonowymi odpowiednikami. |
| NFR-12 | Zgodność z KDP | Domyślne profile formatów zgodne ze specyfikacją KDP (trim, 300 DPI, marginesy, min. 24 strony). Przypomnienie o ujawnieniu AI (FR-13). Prompty nie generują postaci ani znaków chronionych prawem autorskim. |
| NFR-13 | Jakość kodu | `ruff` (lint i format), `mypy --strict` dla `pipeline/` i `providers/`, pre-commit, CI w GitHub Actions (lint, typy, testy). |

## 12. Proponowana struktura repozytorium

```
kdp-studio/
├── pyproject.toml
├── config/
│   ├── settings.yaml
│   ├── ages.yaml
│   ├── styles.yaml
│   └── formats.yaml
├── src/kdp_studio/
│   ├── cli.py
│   ├── models.py            # BookSpec, PageIdea, PageResult, Manifest
│   ├── config.py            # ładowanie YAML i .env
│   ├── pipeline/
│   │   ├── ideas.py
│   │   ├── prompts.py
│   │   ├── worker.py
│   │   ├── postprocess.py
│   │   ├── qa.py
│   │   └── manifest.py
│   └── providers/
│       ├── base.py          # Protocols + rejestr
│       ├── openai_text.py
│       ├── openai_image.py
│       └── fake.py          # do testów
└── tests/
```

## 13. Roadmapa

| Etap | Zakres | Kryterium wyjścia |
|---|---|---|
| 0. Spike promptów | Notebook: 3 tematy × 5 wieków × 2 style, ocena ręczna | Prompty dają czysty line art w ≥ 80% prób |
| 1. MVP CLI | FR-01–FR-13 z dostawcą OpenAI | Kompletna 30-stronicowa książka w katalogu, złożona w Canvie według `canva.md` i przyjęta przez kreator KDP bez błędów |
| 2. PDF w skrypcie (opcjonalnie) | Automatyczne składanie wnętrza (strony wstępne, puste strony po grafikach) zamiast ręcznego w Canvie | Uruchamiamy, gdy ręczne składanie w Canvie zacznie spowalniać wydawanie kolejnych książek |
| 3. Gemini | Adapter `GeminiImageProvider` i porównanie jakości z OpenAI | Przełączenie przez `--image-provider gemini` |
| 4. UI | Streamlit albo Gradio (React dopiero przy produkcie dla innych) | Generowanie bez terminala |

## 14. Otwarte pytania

1. Startowa lista stylów i dozwolone połączenia wiek × styl.
2. Język metadanych książki (`title`, `description`, `keywords`): angielski (rynek US) czy parametr `--lang`?
3. Czy QA ma być domyślnie włączone po etapie 0, gdy znany będzie jego koszt i skuteczność?
4. Czy używać pierwszej zaakceptowanej strony jako referencji stylu dla kolejnych (spójność kontra koszt i czas)?
5. Wybór modelu tekstowego i domyślnej jakości (`quality`) modelu obrazu po spike'u.

## 15. Źródła i referencje
- KDP: rozmiary stron (trim sizes), wymagania druku i ujawnianie treści AI: https://kdp.amazon.com/help/topic/GVBQ3CMEQW3W2VL6
- OpenAI Image API: https://developers.openai.com/api/docs/guides/image-generation
- Gemini API (Nano Banana), cennik: https://ai.google.dev/gemini-api/docs/pricing
- Adobe: kredyty generatywne (zakres użycia): https://helpx.adobe.com/firefly/using/generative-credits-faq.html
- Canva: formaty i limity przesyłanych plików (PNG, SVG): https://www.canva.com/help/upload-formats-requirements/
- KDP: wymagania dla plików do druku (300 DPI, spłaszczanie przezroczystości): https://kdp.amazon.com/help/topic/G202145060
