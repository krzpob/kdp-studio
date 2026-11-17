# KDP Studio: generator kolorowanek (MVP)

Specyfikacja wymagań na potrzeby implementacji. Dokument zbiera ustalenia z sesji projektowej z 15.11.2026.

---

## 0. Stan implementacji

Stan na 17.11.2026. ✅ zrobione, 🟡 częściowo, ⬜ do zrobienia, ↪ zastąpione innym wymaganiem. Te same znaczniki stoją przy nagłówkach wymagań w sekcji 6.

**Wymagania funkcjonalne**

| ID | Stan | PR | Uwagi |
|---|---|---|---|
| FR-01 | ✅ | #4 | |
| FR-02 | ✅ | #4 | |
| FR-03 | ✅ | #5, #6, #20 | |
| FR-03a | ✅ | #12 | |
| FR-03b | ✅ | #22, #24 | |
| FR-04 | ✅ | #8, #15, #20 | |
| FR-05 | ✅ | #9 | |
| FR-06 | ✅ | #11 | |
| FR-07 | ✅ | #14 | |
| FR-08 | ✅ | #13, #23 | |
| FR-09 | ↪ FR-17 | #23 | |
| FR-10 | ✅ | #29 | Cennik `api_pricing` w `settings.yaml`, limit na jedno uruchomienie komendy. |
| FR-11 | ↪ FR-17 | #23 | |
| FR-12 | ✅ | #7 | |
| FR-13 | ✅ | #13 | |
| FR-14 | ✅ | #30 | Poza MVP. Specyfikacja: #16. Czcionka Fredoka (OFL), układ zapasowy z grafiką pierwszej strony. |
| FR-15 | ✅ | #31, #32, #39 | Poza MVP. Specyfikacja: #17. Trzy etapy: geometria, szablon, układ, CMYK i PDF; kolorowy przód z modelu; tył z grzbietem z modelu z kontrolą styku, wybór stron i QA modelem z wizją, opis na tyle. Kryterium wyjścia etapu 1b (plik przyjęty przez KDP) czeka na próbę. |
| FR-16 | ⬜ | | Poza MVP. Specyfikacja: #18. |
| FR-17 | ✅ | #23, #24 | |
| FR-18 | ⬜ | | Poza MVP. Specyfikacja: #25. |
| Profile (§7) | ✅ | #3, #15, #22 | |

**Wymagania pozafunkcjonalne**

| ID | Stan | Uwagi |
|---|---|---|
| NFR-01 | ✅ | `potracer` i `resvg-py`, bez bibliotek natywnych. |
| NFR-02 | ✅ | Pilnuje tego test `tests/test_architecture.py`. |
| NFR-03 | ✅ | Pokrycie modułów `pipeline/` wynosi 91–100%, całego pakietu 98%. Obróbkę testuje plik-wzorzec `tests/fixtures/line_art_bear.png`. |
| NFR-04 | ✅ | Ponowienia z backoffem, atomowy zapis manifestu, wznawianie przez FR-17. |
| NFR-05 | 🟡 | Obróbka strony trwa ok. 2,5 s. Czasu całej 30-stronicowej książki nie zmierzono. |
| NFR-06 | ✅ | 50 grafik w jakości `medium` kosztowało ok. 2,30 USD (trzy prawdziwe książki), więc 30 grafik z QA to ok. 1,40 USD. Twardy limit daje `--max-cost` (FR-10). |
| NFR-07 | ✅ | `verify_page()` po każdym zapisie strony. |
| NFR-08 | ✅ | Manifest zapisuje prompt, model i jakość. OpenAI nie obsługuje seeda. |
| NFR-09 | ✅ | Logi JSON w `kdp-studio.log` (`--log-level info\|debug`), pasek postępu w krokach 2 i 3, czas i koszt każdego kroku oraz podsumowanie `generate` (#28, FR-10). |
| NFR-10 | ✅ | |
| NFR-11 | ✅ | CI na Linux, macOS i Windows (Python 3.12 i 3.14). |
| NFR-12 | ✅ | |
| NFR-13 | 🟡 | Są `ruff`, `mypy --strict` i CI. Brakuje pre-commit. |

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
- Okładka: komenda `kdp-studio cover` tworzy gotowy PDF okładki (FR-15). W MVP okładkę projektuje się ręcznie w Canvie albo w pakiecie Adobe.
- Koszt druku, cena minimalna i tantiemy z tabel KDP oraz podpowiedź ceny: komenda `kdp-studio price` (FR-16).
- Strona „This book belongs to…” dopasowana do motywu kolorowanki, włączana przełącznikiem (FR-14). W MVP użytkownik robi ją ręcznie w Canvie.
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
| D10 | **Geometria okładki liczona wzorami KDP**, nie odczytywana z szablonu przez LLM (FR-15) | Wymiary wynikają jednoznacznie z formatu i liczby stron (oprawa, papier i druk są stałe, FR-15), a pomyłka w jednej cyfrze odrzuca plik. Szablon KDP służy tylko do kontroli i podglądu, odczytywany deterministycznie po kolorach pikseli. Tekst na okładce wpisuje program, model obrazu rysuje tylko ilustracje. |

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

### ✅ FR-01: Walidacja wejścia
- Wszystkie parametry są walidowane przed pierwszym wywołaniem API.
- Nieznany `--age`, `--style` albo `--format` kończy program błędem z listą dozwolonych wartości.
- `--pages` musi być w zakresie 1–200.

### ✅ FR-02: Walidacja liczby stron względem KDP
- Program liczy `pages_in_book = pages * 2 + front_matter_pages` (druk jednostronny, `front_matter_pages` z konfiguracji, domyślnie 2: strona tytułowa i „This book belongs to…”).
- Jeśli `pages_in_book < 24` (minimum KDP dla paperbacka), program pokazuje ostrzeżenie z minimalną poprawną liczbą grafik. Z flagą `--strict` kończy się błędem.
- Jeśli `pages_in_book` przekracza ostatni próg tabeli marginesów KDP (sekcja 7.4), program kończy się błędem walidacji.

### ✅ FR-03: Generowanie pomysłów i metadanych książki
- **Jedno** wywołanie LLM ze strukturyzowanym wyjściem (JSON Schema lub structured outputs).
- Wejście promptu: temat, profil wieku, profil stylu, format, liczba stron.
- Wyjście (`ideas.json`):
  - `book`: `title`, `subtitle`, `description` (pod listing KDP), `keywords` (do 7);
  - `pages`: lista `pages + ceil(pages * reserve_ratio)` pomysłów (`reserve_ratio` domyślnie 0.2), każdy z polami `id`, `title`, `scene` (opis sceny po angielsku, gotowy do promptu), `elements` (lista obiektów).
- Pomysły muszą:
  - wyraźnie pasować do tematu: główny motyw, czynność albo dobrze widoczny przedmiot jest typowy dla tematu i jest na liście `elements`. Motywy zwyczajowo kojarzone z tematem się liczą (dla świąt także bałwan, sanki, śnieg). Ogólne słowa („holiday”, „festive”) nie wystarczą, a scena, która wyglądałaby tak samo w każdy inny dzień (tort urodzinowy z koroną, herbatka, kosz z praniem), potrzebuje konkretnego elementu tematu (dla świąt: pierniczki, choinka, skarpety na prezenty);
  - być unikalne w obrębie książki (różne sceny, nie tylko inne sformułowania);
  - pasować do formatu: `square` to centralny obiekt lub kompozycja koncentryczna, `letter` to postać lub scena w pionie;
  - pasować do wieku: liczba obiektów i złożoność sceny zgodne z profilem wieku.
- Treści nie mogą zawierać postaci chronionych prawem autorskim ani znaków towarowych. LLM dostaje to jako twarde ograniczenie.

### ✅ FR-03a: Weryfikacja pomysłów przed generowaniem grafik
- Domyślnie włączona (`review_ideas: true` w `settings.yaml`); `--no-review-ideas` wyłącza.
- Osobne wywołanie LLM (ten sam model tekstowy, inny prompt: rola recenzenta) ocenia każdy pomysł według listy kontrolnej: zgodność z tematem (reguła z FR-03), unikalność, złożoność dla wieku, kompozycja dla formatu, jedna scena do narysowania konturem bez tekstu, brak chronionych postaci i znaków.
- Recenzent poprawia tylko pomysły, które nie przechodzą listy (większość dobrej listy to `ok`), a przy kilku poprawkach dobiera różne elementy tematu, żeby strony nie wyglądały tak samo.
- Werdykt dla każdego pomysłu: `ok`, `revise` (drobna poprawka, najczęściej dodanie elementu tematu, np. kotek-piekarz piecze pierniczki; recenzent zwraca poprawiony tytuł, scenę i elementy) albo `reject` (z powodem po polsku).
- Odrzucone pomysły zastępuje zapas. Gdy po weryfikacji pomysłów jest mniej niż `pages + ceil(pages * reserve_ratio)`, generator dogenerowuje brakujące (różne od przyjętych i odrzuconych), a one też przechodzą weryfikację. Maks. 2 rundy dogenerowania.
- Mniej przyjętych pomysłów niż `pages` po wszystkich rundach: błąd z kodem 4. Mniejszy zapas niż docelowy: ostrzeżenie.
- `ideas.json` dostaje ślad weryfikacji w polu `review`: `rejected` (tytuł, scena, powód), `revised` (id, pierwotny tytuł i scena, powód), `added`, `rounds`. Ostateczne id to `idea_01…` po weryfikacji.
- Uzasadnienie: weryfikacja kosztuje ułamek centa na książkę, a jedna wyrzucona grafika kilka centów. Nie zastępuje QA z wizją (FR-07), które łapie problemy widoczne dopiero na obrazku (tekst, siatka, cieniowanie).

### ✅ FR-03b: Różnorodność pomysłów w skali książki
Weryfikacja z FR-03a ocenia każdy pomysł osobno, a powtarzalność to cecha całej książki: w pierwszych książkach na prawie każdej stronie był jeden kotek siedzący obok przedmiotu, a choinka pojawiała się w co drugiej scenie.

- **Cechy sceny.** Model przy każdym pomyśle (generowanie, dogenerowanie, poprawka weryfikacji) podaje: `subject` (rodzaj głównej postaci, np. `kitten`), `characters` (liczba postaci), `action` (główna czynność, czasownik w formie podstawowej) i `setting` (miejsce akcji, 1–3 słowa). Wszystko po angielsku, małymi literami. Pole `elements` już istnieje.
- **Rozkład liczy program, nie model.** Model wiarygodnie opisuje jedną scenę, ale słabo liczy w kilkudziesięciu naraz. Liczone są tylko strony książki (pierwsze `pages` pomysłów), bez zapasu.
- **Limity** (kod porównuje rozkład z konfiguracją, profile to dane):
  - co najmniej `multi_subject_share` stron z 2+ postaciami, z profilu wieku (`ages.yaml`): `przedszkole` 0 (jeden duży obiekt), `wczesnoszkolne` 0,25, `szkolne` 0,3, `nastolatki` 0,2, `dorosli` 0 (wzory). Ten sam udział trafia do promptu generowania jako cel;
  - najwyżej `max_action_share` (0,3) stron z tą samą czynnością, `max_setting_share` (0,3) z tym samym miejscem i `max_element_share` (0,35) z tym samym przedmiotem (`settings.yaml`, `diversity`). Przedmiot to rdzeń nazwy z `elements` (ostatnie słowo w liczbie pojedynczej, „decorated trees” → `tree`), bez głównej postaci, która z założenia jest na każdej stronie.
- **Motywy tematu.** Generator zwraca `theme_anchors`: miejsca, przedmioty lub czynności, które nazywa sam temat (dla „Kotki w kuchni” `kitchen`). Nie podlegają limitom. Dla większości tematów lista jest pusta („Świąteczne kotki” nie nazywają miejsca ani przedmiotu).
- **Wyrównanie** (tylko przy włączonej weryfikacji FR-03a, po jej rundach):
  1. Zamiana stron z zapasem, dopóki każda zamiana zmniejsza przekroczenia limitów. Bez wywołań API.
  2. Gdy problemy zostają: jedno wywołanie LLM z listą problemów (liczby od programu), kandydatami do zmiany (pomysły, które tworzą problem) i budżetem zmian równym sumie przekroczeń. Zmieniony pomysł musi dalej spełniać listę kontrolną FR-03a. Program przyjmuje zmianę tylko wtedy, gdy dotyczy kandydata, nie powtarza innej sceny i zmniejsza przekroczenia, więc model nie może pogorszyć rozkładu.
  3. Problemy, które zostały, to ostrzeżenia w konsoli, nie błąd.
- **Wynik:** `ideas.json` dostaje `theme_anchors` i `diversity` (`pages`, rozkład liczby postaci, najczęstsze czynności, miejsca i przedmioty, `issues`, `moved_from_reserve`, `revised`). Poprawki dla różnorodności trafiają też do `review.revised` z powodem zaczynającym się od „różnorodność:”. Konsola pokazuje rozkład po pomysłach.
- Bez weryfikacji (`--no-review-ideas`) program tylko mierzy rozkład i ostrzega.
- Pomysły bez cech (starsze pliki, ręczna edycja w FR-17) pomiar pomija w danym wymiarze.
- Ograniczenie: synonimy liczą się osobno (`tree` i `evergreen`, `living room` i `lounge`), więc limity są raczej łagodne niż surowe.

### ✅ FR-04: Budowanie promptów obrazu
- Prompt dla każdej strony składa się z: opisu sceny z FR-03, **wspólnego bloku stylu** (identycznego dla wszystkich stron książki), fragmentu z profilu wieku i fragmentu z profilu formatu.
- Każdy prompt zawiera stałe ograniczenia: `black and white line art, coloring book page, single illustration, one scene, pure white background, closed outlines, no shading, no grayscale, no text, no grid, no multiple panels, no collage, no frame`.
- Gotowy prompt zapisuje się w manifeście (FR-08), żeby dało się odtworzyć i debugować wynik.

### ✅ FR-05: Generowanie grafik
- Jedno wywołanie `ImageProvider.generate()` na stronę.
- Równoległość konfigurowalna (`--concurrency`, domyślnie 4).
- Ponawianie z wykładniczym odczekiwaniem (backoff) przy błędach 429 i 5xx, maks. 3 próby na wywołanie.
- Adapter mapuje proporcje formatu na rozmiar obsługiwany przez model (sekcja 8). Jeśli model obsługuje dowolne wymiary, adapter używa dokładnych proporcji.
- Surowy wynik zapisuje się do `raw/page_XX.png` przed obróbką.

### ✅ FR-06: Post-processing do druku (strony gotowe do importu w Canvie)
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

### ✅ FR-07: Kontrola jakości (QA), opcjonalna
- Włączana flagą `--qa` (domyślnie wyłączona w MVP).
- Model z wizją ocenia każdą grafikę po FR-06 i zwraca JSON: `{pass: bool, issues: [...]}`.
- Kryteria odrzucenia: kilka paneli, siatka lub kolaż; cieniowanie lub szarości; tekst lub litery; otwarte kontury uniemożliwiające kolorowanie; poziom szczegółowości niezgodny z profilem wieku; elementy niezgodne z opisem sceny.
- Odrzucona strona jest generowana ponownie z **zapasowego pomysłu**. Maks. 2 ponowienia na pozycję, potem strona dostaje status `failed` w manifeście.
- Program kończy się sukcesem, jeśli jest co najmniej `--pages` stron ze statusem `ok`. W przeciwnym razie zwraca kod wyjścia 2 (sekcja 9.3).
- Zapasowe pomysły to wspólna pula dla całej książki, wydawana po kolei stronom odrzuconym przez QA. Gdy pula się skończy, odrzucona strona dostaje status `failed`.
- Odrzucona strona trafia do `rejected/page_XX_tryN.png`, a manifest zapisuje dla niej numer próby, id pomysłu, plik i powody (`rejected`). Wpis strony pokazuje pomysł i prompt ostatniej próby.
- Błąd samej oceny (np. odmowa modelu) oznacza stronę jako `failed`; błąd krytyczny dostawcy (klucz, brak środków) przerywa przebieg jak w FR-05.

### ✅ FR-08: Struktura wyjścia i manifest
- Katalog wyjściowy: `<output-dir>/<slug-tematu>_<age>_<style>_<format>/` (np. `output/dinozaury_przedszkole_kawaii_square/`).
- Zawartość: patrz sekcja 10.
- Gotowe strony leżą w katalogu głównym książki jako `page_XX.png`, z numerem dopełnionym zerami do długości największego numeru (min. 2 cyfry, np. `page_01` … `page_30`). Kolejność alfabetyczna = kolejność stron, więc po przeciągnięciu całej paczki do Canvy strony są we właściwej kolejności.
- W katalogu głównym nie ma innych plików PNG (surowe i odrzucone są w podkatalogach), żeby do Canvy dało się zaznaczyć i przesłać wszystkie pliki naraz. Jedyny wyjątek to strony wstępne z FR-14 (`front_*.png`), które też idą do Canvy i alfabetycznie stoją przed `page_*`.
- Program zapisuje `canva.md`: instrukcję składania tej konkretnej książki (wymiar projektu, liczba grafik i stron książki, kolejność stron wstępnych i pustych, ustawienia eksportu). Treść według sekcji 10.1.
- `manifest.json` zawiera parametry wejściowe, wersję narzędzia, użytych dostawców i modele, `pages_in_book` i użyty `margin_in` (FR-06) oraz dla każdej strony: id pomysłu, prompt, status, liczbę prób, koszt, czas, wynik QA.
- Manifest jest zapisywany przyrostowo po każdej stronie, żeby przerwanie nie gubiło postępu.

### ↪ FR-09: Wznawianie
Zastąpione przez FR-17. Wznowienie to ponowne uruchomienie przerwanego kroku: `kdp-studio images <katalog>` generuje tylko strony, których brakuje, i nie wywołuje ponownie LLM dla pomysłów (idempotentność).

### ✅ FR-10: Koszty i limit budżetu
- Każde wywołanie API zapisuje szacowany koszt (z cennika w konfiguracji albo z `usage` zwracanego przez API).
- `--max-cost <USD>` (domyślnie 5.00): po przekroczeniu limitu program kończy bieżące zadania, nie startuje nowych i zapisuje manifest (status `budget_exceeded`).
- Na końcu program wypisuje podsumowanie: liczbę stron ok/failed, łączny koszt i czas.

**Szczegóły**
- **Cennik:** `api_pricing` w `settings.yaml`, przepisany ze strony dostawcy, z adresem źródła i datą sprawdzenia (`source`, `checked`). Dla każdego modelu podaje cenę w USD za milion tokenów wejścia i wyjścia. Koszt wywołania liczy się z tokenów, które zwraca API. Tokeny z pamięci podręcznej program liczy po pełnej cenie, więc koszt jest raczej zawyżony.
- **Model bez ceny** w cenniku to błąd konfiguracji (kod 1) przed pierwszym wywołaniem API, bo bez ceny program nie pilnowałby limitu.
- **Zakres limitu:** limit dotyczy jednego uruchomienia komendy (`ideas`, `images`, `generate`). Domyślna wartość to `max_cost_usd` w `settings.yaml`, a `--max-cost` ją nadpisuje.
- **Sprawdzanie limitu:** program sprawdza limit przed każdą nową stroną i przed każdą grafiką z zapasowego pomysłu po odrzuceniu przez QA. Koszt strony dolicza się zaraz po jej zakończeniu, zanim wątek weźmie następną. Strony w innych wątkach mogą jeszcze trwać, więc limit może zostać przekroczony najwyżej o grafiki w toku.
- **Po przekroczeniu w `images`:** strona, której QA odrzuciło grafikę, nie dostaje zapasowego pomysłu i jest oznaczona jako nieudana. Manifest dostaje status `budget_exceeded` z opisem w `error`, a program kończy się kodem 3. Kolejne `kdp-studio images` z wyższym limitem dokańcza brakujące strony.
- **Po przekroczeniu w `generate`:** krok 3 (`finalize`) czeka, aż kroki 1 i 2 zostaną dokończone. Jeśli limit zużyją już pomysły, grafiki nie startują.
- **Manifest:** strona ma `cost_usd` z grafik i QA, sumowany przez wszystkie uruchomienia (ponowne wygenerowanie dolicza się do poprzedniego kosztu). `ideas.cost_usd` obejmuje pomysły, weryfikację i `--redo`. Pole `cost_usd` w katalogu głównym manifestu to łączny koszt książki.
- **Konsola:** koszt pomysłów, koszt każdej strony, koszt każdego kroku (`Czas kroku (grafiki): 6 min 12 s, koszt $2.27.`). `generate` kończy się podsumowaniem: liczba gotowych i nieudanych stron, koszt według rodzaju (pomysły, grafiki, QA) z limitem oraz czasy kroków.
- **Log (NFR-09):** `cost_usd` przy `page_raw`, `ideas_saved`, `images_done` i `run_end`. Na poziomie `debug` koszt ma też każde wywołanie API (`api_call`).

### ↪ FR-11: Tryb próbny (dry run)
Zastąpione przez FR-17. Tryb próbny to sam krok 1: `kdp-studio ideas …` zapisuje pomysły i prompty bez generowania grafik, co służy do taniego strojenia profili.

### ✅ FR-17: Generowanie krokowe z ręczną weryfikacją

Generowanie dzieli się na trzy kroki, każdy jako osobna komenda. Między krokami użytkownik może sam przejrzeć i poprawić wynik, zamiast polegać tylko na weryfikacji modelem. `generate` uruchamia wszystkie trzy po kolei, z tymi samymi parametrami co dotąd.

| Krok | Komenda | Wynik | Wywołania API |
|---|---|---|---|
| 1. Pomysły | `kdp-studio ideas --theme … --age … --style … --format … --pages …` | katalog książki, `ideas.json`, `prompts.json`, `manifest.json` (strony `pending`) | LLM: pomysły i weryfikacja pomysłów (FR-03, FR-03a) |
| 2. Surowe grafiki | `kdp-studio images <katalog>` | `raw/page_XX.png`, z `--qa` po kontroli jakości i wymianie odrzuconych na zapas | model obrazu, opcjonalnie model z wizją (FR-05, FR-07) |
| 3. Obróbka | `kdp-studio finalize <katalog>` | `page_XX.png` do Canvy, `svg/`, `canva.md` | brak (FR-06, FR-08) |

**Stan w manifeście**
- `manifest.json` powstaje już w kroku 1. Stan książki: `ideas_ready` → `raw_ready` → `completed` (albo `partial`/`failed` jak dotąd).
- Każda strona ma: `idea_id`, `status` (`pending`, `raw_ok`, `ok`, `failed`), wynik QA, sumę kontrolną promptu (`prompt_sha256`), sumę kontrolną surowego pliku (`raw_sha256`) oraz pole `action` dla użytkownika.
- Każdy krok sprawdza, czy poprzedni jest gotowy, i wykonuje tylko brakującą pracę. Bez zmian ponowne uruchomienie kroku nic nie robi.
- Plik blokady w katalogu książki zapobiega dwóm równoczesnym uruchomieniom. Użytkownik edytuje pliki tylko między uruchomieniami.

**Ręczna weryfikacja po kroku 1**
- Użytkownik edytuje `ideas.json`: poprawia opis sceny (`scene`, `elements`), usuwa pomysły albo zmienia kolejność. Pierwsze `pages` pomysłów to strony, reszta to zapas. Kolejność decyduje o przypisaniu tylko do pierwszej grafiki. Potem przypisanie jest w `manifest.json` (`idea_id`), bo strony mogą mieć już grafiki, a QA mogło podmienić pomysł na zapasowy.
- `kdp-studio ideas <katalog> --redo idea_07,idea_19`: LLM wymyśla w miejsce wskazanych pomysłów nowe, różne od wszystkich pozostałych (mechanizm dogenerowania z FR-03a). Nowe pomysły przechodzą weryfikację i dostają te same `id`. Generator dostaje wskazówki różnorodności z reszty stron książki (FR-03b): czynności, miejsca i przedmioty, które już osiągnęły limit, ma omijać, a brakujące sceny z kilkoma postaciami uzupełniać. Wyrównania (zamiany z zapasem, poprawek LLM) przy `--redo` nie ma, więc wynik to tylko pomiar i ostrzeżenia.
- Krok 2 sprawdza `ideas.json` (schemat, wystarczająca liczba pomysłów, unikalne `id`) i buduje prompty od nowa. Błąd kończy się kodem 1, zanim powstanie jakakolwiek grafika.

**Ręczna weryfikacja po kroku 2**

Użytkownik przegląda `raw/` i zmienia `manifest.json`. Następne `kdp-studio images <katalog>` wykonuje:
- `"action": "regenerate"`: nowa grafika z tego samego pomysłu;
- zmieniony `idea_id` (np. na pomysł z zapasu): grafika z nowego pomysłu. Ten sam pomysł nie może trafić na dwie strony;
- zmieniony opis sceny w `ideas.json`: program wykrywa zmianę promptu po `prompt_sha256` i generuje stronę ponownie, bez dodatkowego oznaczania;
- usunięty plik z `raw/`: strona zostaje wygenerowana ponownie.

Po wykonaniu program czyści `action`.

Własna poprawiona wersja pliku w `raw/` (np. z Photoshopa) jest dozwolona. Program wykrywa ją po `raw_sha256`, oznacza stronę jako `edited_by_user` i nie generuje jej ponownie.

**Szczegóły kroku 2**
- Do kolejki trafia strona z `action: regenerate`, bez surowej grafiki (brak pliku albo nieudana próba), nieudana (także po błędzie obróbki w kroku 3) i ze zmienionym promptem. Prompt zmienia się też po zmianie fragmentu promptu w profilach wieku, stylu albo formatu, więc po takiej zmianie krok 2 generuje ponownie wszystkie strony.
- Przed generowaniem program usuwa nieaktualne `page_XX.png` i `svg/page_XX.svg` tych stron, żeby do Canvy nie trafiła stara wersja.
- Zapas dla QA to pomysły bez strony, w kolejności z `ideas.json`, bez pomysłów już odrzuconych przez QA.
- Odrzucona albo nieudana w obróbce podglądu surowa grafika trafia do `rejected/<strona>_tryN.png`. Pusty slot w `raw/` oznacza, że kolejne `kdp-studio images` wygeneruje stronę ponownie.
- Błąd krytyczny (kod 4) zostawia stan `failed`. Po usunięciu przyczyny `kdp-studio images` dokańcza tylko brakujące strony.
- Plik blokady to `.kdp-studio.lock` w katalogu książki. Po twardym przerwaniu procesu (bez Ctrl+C) zostaje i trzeba go usunąć ręcznie: komunikat to mówi.

**QA w kroku 2**
- Z `--qa` każda strona przechodzi kontrolę jakości w kroku 2, a odrzucone są wymieniane na zapas jak dotąd (FR-07). Użytkownik ogląda już przefiltrowany zestaw.
- Kontrola ocenia stronę po obróbce, bo jest skalibrowana na tym, co idzie do druku. Krok 2 robi więc tymczasową obróbkę na potrzeby kontroli, a na dysk zapisuje tylko surowy plik. Obróbka jest deterministyczna, więc krok 3 daje ten sam wynik, który oceniała kontrola.

**Krok 3**
- `finalize` przetwarza tylko strony, których surowy plik albo parametry obróbki się zmieniły. Strona z błędem obróbki nie jest obrabiana ponownie z tymi samymi wejściami. Żeby ją naprawić, trzeba wygenerować grafikę ponownie (`kdp-studio images`) albo zmienić parametry obróbki. Manifest zapisuje sumę kontrolną parametrów obróbki z profilu wieku, więc po zmianie `ages.yaml` przetwarza wszystkie strony ponownie.
- Nie wywołuje API, więc można go powtarzać bez kosztu, np. przy strojeniu progowania.

**Jakość grafik**
- `--image-quality low|medium|high` w `images` i `generate` nadpisuje `image_quality` z `settings.yaml`. Wartość trafia do manifestu dla każdej strony.
- Porównanie jakości (otwarte pytanie 5): krok 1 raz, potem krok 2 w dwóch kopiach katalogu, z `low` i z `medium`. Ocena po kroku 3: odsetek stron przyjętych przez QA i przegląd ręczny. Wektoryzacja (D6) i tak wygładza linie, więc `low` może wystarczyć.

### ✅ FR-12: Podgląd profili
- Komenda `profiles` wypisuje dostępne wartości `age`, `style` i `format` z krótkimi opisami z YAML.

### ✅ FR-13: Przypomnienie o ujawnieniu AI
- `manifest.json` i podsumowanie w konsoli zawierają informację, że przy publikacji w KDP trzeba zaznaczyć *AI-generated content* (obrazy).

### ✅ FR-14: Strona „This book belongs to…” (poza MVP)

Strona wstępna z miejscem na imię właściciela, narysowana w tym samym motywie i stylu co kolorowanka (np. dinozaury kawaii wokół pustej tabliczki na imię).

**Włączanie**
- Przełącznik `--belongs-to-page/--no-belongs-to-page`, domyślnie z `settings.yaml` (`belongs_to_page.enabled`, domyślnie `false`).
- Gdy przełącznik jest wyłączony, nic się nie zmienia: użytkownik robi tę stronę ręcznie w Canvie, jak w MVP.
- Strona jest już wliczona w `front_matter_pages` (domyślnie 2: strona tytułowa i ta strona), więc `pages_in_book` i marginesy (FR-02, FR-06) się nie zmieniają.

**Podział pracy: model rysuje ozdobę, program wpisuje tekst**
- Modele obrazu źle radzą sobie z tekstem (literówki, krzywe litery), a stałe ograniczenia FR-04 zabraniają go w grafikach. Model rysuje więc wyłącznie **ramkę z elementami motywu wokół pustego pola na imię**, a napis i linię na imię dokłada program.
- Prompt składa się z:
  - motywu książki (`theme`) i 2–3 elementów z zaakceptowanych pomysłów (FR-03), żeby strona pasowała do zawartości;
  - **tego samego bloku stylu** co strony (FR-04: styl, wiek, format), żeby grubość linii i charakter rysunku były spójne z resztą książki;
  - opisu kompozycji z `belongs_to_page.composition` (np. `decorative frame made of theme elements around a large empty blank plaque in the center, the plaque is completely empty`);
  - stałych ograniczeń FR-04 **bez** `no frame` (ramka jest tu celem). `no text` zostaje bez zmian.

**Pole na tekst**
- Pole tekstowe to prostokąt zdefiniowany względem obszaru treści (`belongs_to_page.text_box`, np. środkowe 70% szerokości i 35% wysokości).
- Po obróbce FR-06 program sprawdza, czy pole jest puste: udział czarnych pikseli ≤ `max_ink_ratio` (np. 0.5%). Jeśli nie, generuje stronę ponownie (maks. `max_retries`, domyślnie 2).
- Gdy próby się wyczerpią, program przechodzi na **układ zapasowy**: grafikę z motywem (bez ramki) w górnych 55% obszaru treści, a tekst i linię pod nią. Ta strona zawsze powstaje.

**Tekst i miejsce na imię**
- Program wpisuje napis `belongs_to_page.text` (domyślnie „This book belongs to:”, w języku `metadata_language`).
- Pod napisem rysuje pustą linię albo ramkę na imię wpisywane ręcznie. Każdy egzemplarz drukowanej książki jest taki sam, więc imienia nie da się wydrukować.
- Rozmiar napisu i wysokość miejsca na imię zależą od wieku: przedszkolaki piszą dużymi literami. W `ages.yaml` dochodzi blok `belongs_to` z `font_pt` i `name_line_height_in`.
- Czcionka:
  - plik z repozytorium (`assets/fonts/`) z licencją pozwalającą na komercyjne użycie w druku (np. SIL OFL), z dołączonym plikiem licencji;
  - opcjonalnie litery konturowe (`outline_text: true`), które też można pokolorować; dla najmłodszych domyślnie włączone.
- Gotowa strona przechodzi tę samą kontrolę co strony kolorowanki (NFR-07): wymiary, tryb `L`, tylko 0/255 i czarne piksele w obszarze treści.

**QA i spójność**
- Z `--qa` model z wizją ocenia stronę wg kryteriów FR-07. Kryterium `text` zamienia się na: „model nie dorysował żadnego tekstu poza napisem programu”, a `scene_mismatch` na: „elementy pasują do motywu książki”.
- Gdy dostawca obsługuje `reference_image`, pierwsza zaakceptowana strona kolorowanki jest referencją stylu. Wtedy strona „belongs to” powstaje po stronach z grafikami.

**Wynik**
- Plik `front_belongs_to.png` w katalogu głównym książki: pełna strona, ten sam format i marginesy co `page_*.png`. Nazwa stoi alfabetycznie przed `page_*`, więc po przesłaniu do Canvy plik jest pierwszy na liście.
- Archiwa jak dla stron: `svg/front_belongs_to.svg`, `raw/front_belongs_to.png`, a odrzucone próby w `rejected/`.
- `manifest.json` ma sekcję `front_matter.belongs_to` z polami jak wpis strony (prompt, status, próby, koszt, QA) oraz `layout`: `frame` albo `fallback`.
- `canva.md` wskazuje, na której stronie wstępnej umieścić plik (domyślnie druga, po stronie tytułowej).
- Koszt to jedna dodatkowa grafika plus ewentualne ponowienia; liczy się do `--max-cost` (FR-10).
- Brak strony przy włączonym przełączniku (status `failed`) daje kod wyjścia 2, jak brakująca strona kolorowanki. Kolejne `kdp-studio images` generuje ją ponownie, a krok `ideas` zapisuje jej prompt (FR-17).

Konfiguracja (szkic):

```yaml
# settings.yaml
belongs_to_page:
  enabled: false                 # --belongs-to-page / --no-belongs-to-page
  text: "This book belongs to:"
  composition: >-
    decorative frame made of theme elements around a large empty blank plaque in the center,
    the plaque is completely empty
  text_box: {x: 0.2, y: 0.37, width: 0.6, height: 0.3}   # względem obszaru treści
  max_ink_ratio: 0.005
  max_retries: 2
  font: assets/fonts/Fredoka-Variable.ttf
  font_variation: SemiBold
  fallback_art_height: 0.55      # część obszaru treści na grafikę w układzie zapasowym

# ages.yaml (dla każdego profilu)
przedszkole:
  belongs_to:
    font_pt: 48
    name_line_height_in: 1.0
    outline_text: true
```

**Implementacja (16.11.2026)**
- **Czcionka:** Fredoka (SIL OFL 1.1) w `assets/fonts/Fredoka-Variable.ttf` z licencją `assets/fonts/OFL.txt`, wariant `SemiBold` (`belongs_to_page.font_variation`). Litery konturowe rysuje program: biały środek i czarny obrys. Czcionka nie potrzebuje więc osobnej wersji konturowej. Domyślnie konturowe są dla `przedszkole` i `wczesnoszkolne`.
- **Napis:** po angielsku, „This book belongs to:”. Inny język to zmiana `belongs_to_page.text` w `settings.yaml`. Za szeroki napis program zmniejsza, najwyżej do 40% rozmiaru z profilu wieku. Jeśli i tak się nie mieści, strona dostaje błąd obróbki.
- **Elementy motywu w prompcie:** najczęstsza główna postać (`subject`) i najczęstsze przedmioty (`elements`) stron książki, liczone przez program, deterministycznie. Motyw to tytuł książki (`book.title`, w języku metadanych), bo prompt jest po angielsku.
- **Pole na tekst:** domyślnie `x: 0.2, y: 0.37, width: 0.6, height: 0.3`. Jest nieco mniejsze niż w szkicu, żeby łatwiej mieściło się w tabliczce z modelu.
- **Układ zapasowy:** grafika **pierwszej gotowej strony książki** (jej surowy plik, już po QA) w górnych 55% obszaru treści, a napis pod nią. Grafika „z motywem bez ramki” byłaby kolejnym wywołaniem API, a nieudana ramka mogła zawierać napis modelu. Strona książki jest tania, czysta i w tym samym stylu. Kosztem jest powtórzenie jednej ilustracji w książce. Bez żadnej gotowej strony (wszystkie nieudane) strona FR-14 też jest nieudana.
- **Kolejność w kroku 2:** strona FR-14 powstaje po stronach książki, bo układ zapasowy potrzebuje ich grafik. Gdy limit budżetu jest już przekroczony, strona nie startuje (kod 3). Gdy limit zostanie przekroczony w trakcie prób, program przechodzi na układ zapasowy, który nic nie kosztuje.
- **Przełącznik:** `--belongs-to-page/--no-belongs-to-page` działa w `ideas` i `generate`, które tworzą wpis w manifeście z promptem ramki. Działa też w `images`, które dodaje albo usuwa stronę w istniejącej książce. Bez flagi `images` robi to, co jest w manifeście. Usunięcie strony kasuje `front_belongs_to.png` z katalogu głównego, a surową grafikę zostawia.
- **Krok 2 generuje stronę ponownie** przy `action: regenerate` we wpisie `front_matter.belongs_to`, przy braku surowej grafiki, po nieudanej próbie i po zmianie promptu ramki (np. po zmianie pomysłów albo `composition`).
- **Krok 3 obrabia stronę ponownie**, gdy zmieni się surowa grafika, parametry obróbki, napis, pole, czcionka (suma pliku) albo profil wieku. Model nie jest wtedy wywoływany.
- **`reference_image`:** adapter OpenAI go nie obsługuje, więc strona nie używa referencji stylu. Wspólny blok stylu wystarcza do spójności.

### ✅ FR-15: Okładka (poza MVP)

Komenda `kdp-studio cover <katalog-książki>` tworzy gotową do KDP okładkę paperback: jeden jednostronicowy PDF z tyłem, grzbietem i przodem. Uruchamia się ją po `generate`, bo wymiary zależą od ostatecznej liczby stron, a przód od gotowych grafik. Okładkę można wygenerować ponownie bez ruszania wnętrza.

**Stałe założenia produkcyjne**
- Kolorowanki mają zawsze miękką okładkę (paperback), wnętrze czarno-białe i zwykły biały papier.
- Grubość papieru, spad i strefy są więc stałe i siedzą w `kdp_cover` w `settings.yaml`, a nie w parametrach CLI.
- Inna oprawa (hardcover), papier kremowy albo kolorowe wnętrze są poza zakresem. Wymagałyby innych wzorów (hardcover ma zawinięcie na tekturę i zawias) i nowych pól w konfiguracji.
- Twarda oprawa nie opłaca się w kolorowankach:
  - KDP oferuje ją tylko w kilku formatach (5.5" × 8.5", 6" × 9", 6.14" × 9.21", 7" × 10", 8.25" × 11"). Nie ma kwadratu, a najbliższy letter jest o 0.25" węższy, więc wnętrze trzeba by renderować osobno;
  - wymaga min. 75 stron;
  - koszt druku jest ok. 2.6 razy wyższy, co mocno podnosi cenę kolorowanki. Kalkulator KDP (amazon.com, 104 strony, wnętrze czarno-białe, stan na 16.11.2026):

    | Oprawa | Format | Koszt druku | Minimalna cena |
    |---|---|---|---|
    | miękka | 8.5" × 11" | $2.84 | $5.68 |
    | twarda | 8.25" × 11" | $7.49 | $12.48 |

    Źródło: https://kdp.amazon.com/en_US/royalty-calculator

**Geometria: liczona, nie odczytywana (D10)**
- Wszystkie wymiary program liczy wzorami KDP z danych w `manifest.json` (format, `pages_in_book`) i konfiguracji (`kdp_cover` w `settings.yaml`):
  - `spine_in = pages_in_book × paper_factor_in`, gdzie `paper_factor_in` = 0.002252" (biały papier, wnętrze czarno-białe);
  - szerokość = spad + tył + grzbiet + przód + spad, przy spadzie 0.125";
  - wysokość = wysokość formatu + 2 × spad;
  - piksele przy 300 DPI.
  - Przykład: letter, 30 grafik, 62 strony → grzbiet 0.1396", okładka 17.3896" × 11.25" (5217 × 3375 px).
  - Przykład sprawdzony na szablonie KDP: kwadrat 8.5", 104 strony, papier biały → grzbiet 0.234", okładka 17.484" × 8.75". Szablon podaje te same wartości, a zmierzone na nim położenie linii cięcia, zgięć, stref i pola kodu zgadza się z wyliczeniami z dokładnością do 0.003". To samo dla letter 8.5" × 11" i 104 stron: okładka 17.484" × 11.25" (`tests/fixtures/kdp_templates/`).
- Strefy wyliczane z tej samej geometrii:
  - linie cięcia i dwie linie zgięcia (tył/grzbiet, grzbiet/przód);
  - **strefa bezpieczna** („live area” w szablonie KDP): min. 0.125" od linii cięcia **i od obu linii zgięcia** na przodzie i tyle. Tytuł i kluczowe elementy trzymamy dalej, `key_margin_in` (domyślnie 0.375");
  - **grzbiet:** tekst min. 0.0625" od każdej linii zgięcia (strefa bezpieczna grzbietu w szablonie KDP);
  - **pole kodu kreskowego:** 2" × 1.2" na tylnej okładce, 0.25" od grzbietu i 0.25" od dolnej linii cięcia.
- Wymiary nie pochodzą z modelu ani z OCR: pomyłka w jednej cyfrze odrzuca plik w KDP, a wzór jest jednoznaczny i testowalny.

**Szablon KDP (opcjonalnie, `--template szablon.png`)**
- Program odczytuje szablon z kalkulatora okładek KDP deterministycznie, po kolorach pikseli, bez LLM:
  - czarna ciągła linia to cięcie;
  - niebieskie przerywane linie to zgięcia grzbietu;
  - różowy obszar to spad i margines poza strefą bezpieczną, a biały to strefa bezpieczna;
  - żółty prostokąt to pole kodu kreskowego.
- Kolory skalibrowane na prawdziwym szablonie (`template_colors` niżej). Napisy objaśniające w szablonie pomija się: pole kodu to obrys żółtych pikseli, a linie to kolumny i wiersze z długimi ciągami pikseli danego koloru.
- Szablon nie ma 300 DPI (przykładowy: 8000 × 4003 px, ok. 457.5 px/cal), a przy przesyłaniu bywa konwertowany do JPEG. Program przelicza piksele na cale przez `szerokość_px / szerokość_okładki_in`, przyjmuje PNG i JPEG, a tolerancje kolorów pokrywają artefakty kompresji.
- Program porównuje położenie linii, stref i pola kodu z wyliczoną geometrią (tolerancja 0.01"). Rozbieżność, np. szablon pobrany dla innej liczby stron, to błąd walidacji z opisem różnic.
- Nazwa pliku KDP koduje parametry (`PAPERBACK_8.500x8.500_104_BW_WHITE_en_US.png`: oprawa, format, liczba stron, atrament, papier). Jeśli nazwa pasuje do tego wzoru, program sprawdza `PAPERBACK`, `BW` i `WHITE` (stałe założenia) oraz porównuje format i liczbę stron z manifestem. Przy niezgodności kończy się błędem.
- Szablon nałożony półprzezroczyście trafia do `cover_preview.png`.

**Wybór grafik**
- `--cover-page 07` wskazuje stronę na przód. Bez parametru program **proponuje ją modelem z wizją**: dostaje on jeden arkusz kontaktowy złożony przez program (miniatury stron `ok` z numerami narysowanymi przez program) i zwraca stronę na przód, 3 strony na miniatury tyłu (różne od przodu i możliwie różnorodne) oraz uzasadnienie. To jedno wywołanie oceny, nie generowania obrazu, więc D4 go nie dotyczy.
- `--thumbnails 03,12,21` wskazuje miniatury ręcznie.
- Wybór i uzasadnienie trafiają do manifestu.

**Przód**
1. Program buduje szkic układu w wymiarach przodu ze spadem: wybrana strona (czarno-biały line art 300 DPI) w dolnej części i pusty pas u góry na tytuł.
2. Model obrazu koloruje szkic, z obrazem referencyjnym (`reference_image`): żywe kolory w stylu książki dla dzieci, tło dopełnione do krawędzi spadu, kontury na miejscu, pas tytułu jako spokojne tło (niebo, gradient), **bez tekstu**.
3. Model zwraca ok. 1.5k px, a przód ze spadem wymaga ok. 2588 × 3375 px. Program skaluje warstwę koloru i nakłada na nią ostre kontury z renderu 300 DPI (mnożenie). Przed nałożeniem sprawdza zgodność konturów modelu z oryginałem; przy przesunięciu powyżej progu używa samego powiększonego obrazu i zapisuje to w manifeście.
4. Program wpisuje tytuł i podtytuł (z metadanych FR-03, np. „Coloring Book for Kids Ages 3–5”) czcionką z repozytorium na licencji OFL, z obrysem lub cieniem dla kontrastu, w strefie `key_margin_in`. Model nigdy nie rysuje tekstu (jak w FR-14).
5. Czytelność w miniaturze: program zmniejsza przód do szerokości `thumbnail_check_px` (domyślnie 160 px, jak w wynikach Amazon) i sprawdza minimalną wysokość liter tytułu oraz kontrast tytułu z tłem.

**Tył i grzbiet: jeden obraz, dopasowany do przodu**
- Tył i grzbiet powstają **razem, jednym wywołaniem modelu**, w proporcji (tył + spad + grzbiet) : wysokość. Daje to ok. 0.78 dla letter i ok. 1.0 dla kwadratu, czyli proporcje dobrze obsługiwane przez modele. Między tyłem a grzbietem nie ma więc szwu, a grzbiet to ciąg dalszy tła tyłu.
- Spójność z przodem:
  - przód jest obrazem referencyjnym;
  - program analizuje gotowy przód modelem z wizją: zwraca wysokość **linii horyzontu** jako ułamek wysokości (albo jej brak, np. przy tle-wzorze) i kolory tła w pasach poziomych przy lewej krawędzi przodu. Program uzupełnia to próbkami pikseli z lewej krawędzi;
  - prompt narzuca horyzont na tej samej wysokości, te kolory tła i styl przodu.
- Reguły kompozycji w prompcie:
  - kluczowe elementy co najmniej `key_margin_in` od krawędzi;
  - prawy pas szerokości grzbietu plus zapas to wyłącznie tło;
  - dolny róg przy grzbiecie (pole kodu kreskowego) to spokojne tło;
  - bez tekstu.
- **Kontrola styku z przodem:** program porównuje kolory w pasach poziomych po obu stronach zgięcia grzbiet/przód (ΔE w przestrzeni Lab) i położenie horyzontu. Przekroczenie progu (`seam_max_delta_e`, `horizon_tolerance`) to ponowienie, maks. `max_retries`.
- **Wygładzenie styku:** w pasie `seam_band_in` po stronie grzbietu program płynnie przechodzi z tła tyłu w kolory lewej krawędzi przodu. Przód zostaje nienaruszony, a przesunięcie przy oprawie nie odsłania szwu.
- **Tekst na grzbiecie:** tylko gdy `pages_in_book ≥ spine_text_min_pages` (domyślnie 100; twarde minimum KDP to 79). Tytuł czytany z góry na dół, min. 0.0625" od linii zgięcia, rozmiar dopasowany do szerokości grzbietu, min. 7 pt. Gdy się nie mieści, program pomija tekst z ostrzeżeniem. Poniżej progu grzbiet to samo tło. Przy typowej książce z 30 grafikami (62 strony) grzbietu nie da się podpisać.

**Miniatury na tyle**
- Co najmniej 3 miniatury (`thumbnails`, 3–4) stron z wnętrza, czarno-białe na białym tle, z pliku `page_XX.png` 300 DPI, więc ostre.
- Każda w ramce **grubszej niż kontury zmniejszonej grafiki**, żeby było widać, że to ramka:
  - program mierzy typową grubość linii strony (np. transformata odległości);
  - mnoży ją przez skalę miniatury i ustawia ramkę na `thumbnail_frame_ratio` × ta wartość (domyślnie 2×), nie cieńszą niż `thumbnail_frame_min_pt`.
- Układ liczy program: wszystkie miniatury w strefie bezpiecznej tyłu (`key_margin_in`), z dala od linii zgięcia i **poza polem kodu kreskowego**. Pod polem kodu może biec tylko tło.
- Opcjonalnie krótki opis z metadanych (`back_text`, domyślnie wyłączony), z tymi samymi ograniczeniami.

**Kolory: PDF w CMYK**

Co mówi KDP (strona pomocy o okładce paperback, G201953020):
- obrazy okładki powinny być w CMYK, żeby okładka dobrze wyglądała w druku;
- nie należy mieszać przestrzeni barw w jednym pliku;
- nie zaleca dołączania profili kolorów do pliku, bo przed publikacją są automatycznie usuwane;
- przy druku na żądanie dopuszcza pewną tolerancję kolorów.

KDP nie podaje ani konkretnego profilu CMYK, ani limitu sumy farb. Plik RGB KDP konwertuje sam, według własnych ustawień, a jaskrawe kolory potrafią wtedy zmatowieć bez ostrzeżenia. Program konwertuje więc okładkę do CMYK sam: pod kontrolą, z podglądem skutków przed wysłaniem.

- **Praca w RGB, CMYK na końcu.** Model obrazu, skalowanie, wygładzanie styku i kontrola czytelności działają w RGB. Do CMYK trafia dopiero gotowa warstwa kolorowa, jednym przekształceniem przez profil ICC (Pillow `ImageCms`, czyli LittleCMS dołączony do kół Pillow, bez bibliotek natywnych, NFR-11).
- **Profil docelowy** z konfiguracji (`cover.cmyk.profile`). KDP żadnego nie wskazuje, więc to nasz wybór; poradniki zewnętrzne najczęściej podają U.S. Web Coated (SWOP) v2, a jako alternatywę GRACoL 2006 Coated. Profil służy tylko do konwersji i podglądu, nie trafia do PDF. Plik profilu nie trafia do repozytorium, jeśli jego licencja nie pozwala na redystrybucję: użytkownik pobiera go sam i podaje ścieżkę. Brak pliku przy włączonym CMYK to błąd walidacji z instrukcją, skąd go wziąć (kod 1).
- **Sposób konwersji** (`cover.cmyk.rendering_intent`): domyślnie `perceptual`, bo ilustracje dla dzieci mają dużo nasyconych kolorów spoza gamutu druku, a ta metoda zachowuje relacje między nimi. Alternatywa: `relative_colorimetric` z kompensacją punktu czerni. Wybór po porównaniu na prawdziwych okładkach.
- **Czarny tylko z K.** Elementy czarne program rysuje bezpośrednio w CMYK jako C0 M0 Y0 K100, z pominięciem profilu:
  - kontury przodu (warstwa 300 DPI z FR-06);
  - linie i ramki miniatur na tyle;
  - czarny tekst (tytuł, podtytuł, grzbiet).
  Po konwersji przez profil czerń byłaby mieszanką czterech farb, a przy minimalnym przesunięciu farb w druku cienkie linie i litery mają kolorowe obwódki. Kolorowe elementy tekstu (wypełnienie, obrys, cień) przechodzą przez profil jak reszta.
- **Białe tło miniatur** to C0 M0 Y0 K0 (sam papier), a nie wynik konwersji bieli.
- **Limit sumy farb** (`cover.cmyk.max_total_ink_pct`, domyślnie 300, zgodnie z SWOP v2). KDP nie podaje limitu. Inne drukarnie (IngramSpark) wymagają 240%, a zbyt dużo farby w ciemnych miejscach szkodzi laminatowi. Program mierzy sumę C+M+Y+K w każdym pikselu i w miejscach powyżej limitu zmniejsza C, M i Y proporcjonalnie, bez ruszania K. W manifeście zapisuje maksymalną sumę i odsetek poprawionych pikseli. Wartość 240 da plik gotowy też dla innych drukarni.
- **Podpowiedź dla modelu:** prompt przodu i tyłu prosi o paletę przyjazną drukowi (bez neonów i fluorescencji), żeby mniej kolorów wypadało poza gamut.

**Podgląd przed wysłaniem do KDP**
- `cover_proof.png`: okładka po konwersji CMYK, przeliczona z powrotem na RGB przez ten sam profil (symulacja druku na ekranie). Pokazuje, jak kolory zmienią się w druku, zanim plik trafi do KDP.
- `cover_gamut.png`: okładka z zaznaczonymi miejscami, gdzie różnica między oryginałem a symulacją druku przekracza `cover.cmyk.gamut_warn_delta_e` (ΔE). Program podaje odsetek powierzchni z dużą zmianą i ostrzega, gdy obejmuje ona tytuł albo przekracza `gamut_warn_area_pct`.
- Nawet przy własnej konwersji druk różni się od ekranu (papier, maszyna, nieskalibrowany monitor). Ostateczną kontrolą kolorów jest egzemplarz próbny zamówiony w KDP. `canva.md` dla okładki i podsumowanie w konsoli przypominają o tym przy pierwszej książce z nowym profilem lub nową paletą.

**Kontrole przed zapisem**
- **Wymiary:** obraz ma dokładnie wyliczone piksele, 300 DPI. Rozmiar strony PDF to wyliczone cale (dokładność 0.001").
- **Rozmieszczenie:** tytuł, podtytuł, miniatury i tekst grzbietu leżą w swoich strefach, nic z tego nie wchodzi w pole kodu kreskowego. Te elementy rozmieszcza program, więc kontrola to asercja, a nie heurystyka.
- **Tekst na grzbiecie** tylko przy spełnionym progu stron.
- **QA (z `--qa`):** model z wizją sprawdza, że model obrazu nie dorysował tekstu, że przód pokazuje wybraną stronę i że tył pasuje stylem do przodu.
- **Kolory:** cały `cover.pdf` jest w CMYK, bez żadnego obiektu RGB ani przezroczystości. Czarne kontury, ramki i czarny tekst mają wyłącznie K100. Suma farb nie przekracza limitu.

**Wynik (`cover/` w katalogu książki)**
- **`cover.pdf`**: jedna strona w dokładnym rozmiarze, obraz w `DeviceCMYK` osadzony bez stratnej kompresji (Flate, nie JPEG), z ustawionymi `TrimBox` i `BleedBox`. **Bez osadzonego profilu ICC i bez `OutputIntent`**, bo KDP i tak usuwa profile przed publikacją i tego nie zaleca. Z tego samego powodu celem nie jest PDF/X-1a, który wymaga `OutputIntent`. Użyty profil zapisuje tylko manifest. Napisy są w obrazie, więc nie ma problemu z osadzaniem czcionek.
- **`cover_proof.png`** i **`cover_gamut.png`**: podgląd druku i mapa zmian kolorów (patrz wyżej).
- **`cover.png`**: cała okładka w RGB (przed konwersją, do podglądu na ekranie).
- **`front.png`**: sam przód w RGB, np. jako miniatura do reklam i na stronę produktu.
- **`cover_preview.png`**: okładka z naniesionymi liniami cięcia i zgięcia, strefami bezpiecznymi, polem kodu i opcjonalnie szablonem KDP.
- **`raw/`**: surowe wyniki modelu.
- **Manifest:** `manifest.json` dostaje sekcję `cover` z geometrią (`pages_in_book`, `spine_in`, wymiary), wyborem stron, promptami, wynikami kontroli styku, użytym profilem CMYK (nazwa i suma kontrolna pliku), sposobem konwersji, maksymalną sumą farb, odsetkiem powierzchni ze zmianą koloru, kosztem i statusem.
- **Nieaktualna okładka:** jeśli później zmieni się `pages_in_book` książki, `cover` i `kdp-studio images` ostrzegają, że okładka jest nieaktualna.
- **Koszt:** 2 grafiki (przód, tył z grzbietem) plus 1–3 wywołania oceny (wybór stron, horyzont, QA) i ponowienia; liczy się do `--max-cost` (FR-10).
- **Kody wyjścia** jak w §9.3: brak okładki po wyczerpaniu ponowień to 2, błąd walidacji lub szablonu to 1.

**Implementacja etapami**

FR-15 powstaje w trzech PR-ach.

*Etap 1 (zrobiony): bez wywołań modelu.*
- **Geometria i strefy** (`pipeline/cover_geometry.py`) zgadzają się z obydwoma szablonami testowymi.
- **Odczyt i kontrola szablonu KDP:** nazwa pliku i pomiar po kolorach przez `cv2.inRange`. Gdy już nazwa wskazuje inną książkę, pomiaru nie ma.
- **Układ** (`pipeline/cover.py`):
  - przód jako **szkic**: czarno-biała grafika wybranej strony pod tytułem i podtytułem, które wpisuje program;
  - miniatury tyłu w ramkach (grubość z transformaty odległości) nad polem kodu;
  - tytuł na grzbiecie od 100 stron;
  - asercja rozmieszczenia i `cover_preview.png` ze strefami i szablonem.
- **CMYK** (`pipeline/cmyk.py`): warstwy `color`, `black` (K100) i `paper` (K0), konwersja przez profil ICC (ImageCms), limit sumy farb, `cover_proof.png` i `cover_gamut.png` (ΔE76).
- **`cover.pdf`** (`pipeline/pdf.py`): zapisywany ręcznie, bo Pillow zapisuje CMYK do PDF jako JPEG.
- **Sekcja `cover` w manifeście.**
- **Ostrzeżenie w `images`**, gdy strony okładki zostały wygenerowane ponownie.

*Etap 2 (zrobiony):*
- **Adapter OpenAI:** zapytanie z `reference_image` idzie do `images.edit` z `input_fidelity: high`.
- **Kolorowanie** (`pipeline/cover_front.py`):
  - szkic przodu ze spadem (kontury i pusty pas na tytuł) idzie do modelu jako referencja, rozciągnięty do najbliższych proporcji dostawcy (kwadrat → 1:1, letter → 3:4);
  - wynik wraca rozciągnięty z powrotem do przodu;
  - prompt `cover.color_prompt` z blokiem stylu książki;
  - ponowienia przy błędach niekrytycznych (`max_retries`).
- **Kontury:** program mierzy, jaka część konturów szkicu ma w pobliżu ciemny piksel modelu (`contour_search_in`, 0,02"). Przy zgodności ≥ `contour_match_min` (85%) nakłada ostre kontury K100. Przy przesunięciu używa samego obrazu modelu i ostrzega.
- **Tytuł i podtytuł:** wypełnienie w kolorze (`title_fill_rgb`, `subtitle_fill_rgb`) przez profil ICC, obrys czarny K100 (`title_outline_pt`). Wpisywane po kolorowaniu, więc model ich nie widzi.
- **Czytelność:** wysokość liter tytułu w miniaturze `thumbnail_check_px` (≥ `thumbnail_min_text_px`) i kontrast WCAG tytułu z tłem (lepszy z wypełnienia i obrysu, ≥ `title_min_contrast`). Niespełnione to ostrzeżenie.
- **`cover`:** opcje `--color/--no-color` (domyślnie `cover.colorize`), `--image-quality`, `--image-provider` i `--max-cost`. Koszt trafia do `cover.cost_usd` i do łącznego kosztu książki.
- **Kody wyjścia:** nieudane kolorowanie to kod 2 (`cover.status: failed`, poprzednie pliki zostają), przekroczony limit to kod 3, błąd krytyczny to kod 4.
- **Pliki prób:** `cover/raw/front_sketch.png` i `cover/raw/front_color_tryN.png`.
- **Ograniczenie:** `Usage` nie rozróżnia tokenów obrazu wejściowego (cennik OpenAI: $8 za 1M wobec $5 za tekst), więc koszt wejścia referencji jest nieco zaniżony. Wyjście, które dominuje w koszcie, liczy się dokładnie.

*Etap 3 (zrobiony):*
- **Wybór stron** (`pipeline/cover_vision.py`): bez `--cover-page` i `--thumbnails` program składa arkusz kontaktowy (`cover/raw/contact_sheet.png`, numery rysuje program) i pyta model z wizją o przód, miniatury i uzasadnienie (`cover.selection: vision`, `selection_info` w manifeście). Numery spoza arkusza, powtórki albo przód wśród miniatur program zastępuje wyborem domyślnym z ostrzeżeniem. Strony podane ręcznie zostają: przy samym `--cover-page` model wybiera tylko miniatury, przy samym `--thumbnails` tylko przód (miniatur nie ma wtedy na arkuszu). Niekrytyczny błąd modelu to wybór domyślny z ostrzeżeniem. `--no-select-pages` (`cover.select_pages`) wyłącza propozycję.
- **Tył i grzbiet** (`pipeline/cover_back.py`), tylko przy pokolorowanym przodzie:
  - model z wizją podaje horyzont i kolory tła przy lewej krawędzi przodu; program dodaje próbki pikseli i własny pomiar horyzontu (wiersz największej zmiany koloru w pionie, ΔE ≥ 15), które zastępują ocenę modelu, gdy ta się nie uda;
  - prompt `cover.back_prompt` z polami `{horizon}`, `{colors}`, `{spine_pct}` (grzbiet z zapasem 0.25"), `{margin_pct}`; nieznane pole to błąd konfiguracji;
  - kontrola styku: mediany kolorów w `seam_bands` pasach (domyślnie 8) po obu stronach zgięcia grzbiet/przód, ΔE w Lab. Wiersze w odległości `horizon_tolerance` od wykrytego horyzontu są pominięte, bo przesunięcie w granicach tolerancji zamieniłoby w pasie niebo na ziemię; położenie horyzontu sprawdza osobny warunek (tylko gdy widać go po obu stronach);
  - po `max_retries` nieudanych kontrolach program bierze próbę z najmniejszym ΔE i ostrzega; wygładzenie styku i tak działa;
  - pliki prób: `cover/raw/back_tryN.png`; manifest: `cover.back` (prompt, ocena przodu, próbki krawędzi, wynik kontroli każdej próby, użyta próba).
- **Opis na tyle** (`--back-text`, `cover.back_text`): najwięcej pełnych zdań opisu z metadanych, które mieszczą się w `back_text_max_height` (30%) strefy tyłu, w rozmiarze od `back_text_pt` (16 pt) do `back_text_min_pt` (10 pt); litery jak tytuł (kolor z czarnym obrysem K100). Miniatury przesuwają się pod opis. Gdy nie mieści się nawet jedno zdanie, tył jest bez opisu z ostrzeżeniem.
- **QA** (`--qa`, `cover.qa`): jedna ocena całej okładki (zmniejszonej do 2048 px) według kryteriów `text` (tekst inny niż napisy programu), `front_mismatch` (przód nie pokazuje sceny wybranej strony), `style_mismatch` (tył nie pasuje do przodu albo widać szew) i `other`. Wynik w `cover.qa` jak przy stronach (`{pass, issues}`).
- **Decyzja:** odrzucenie przez QA nie ponawia generowania (nie wiadomo, którą część poprawić, a każda próba to płatna grafika). Pliki się zapisują, `cover.status` to `qa_failed`, a kod wyjścia 2, żeby użytkownik obejrzał `cover.png` przed wysłaniem. Tak samo przy błędzie QA (krytyczny: kod 4) i przekroczonym limicie przed QA (kod 3).
- **Koszt:** wszystkie oceny modelem z wizją liczą się jako `qa`, grafiki jako `images`, razem w `cover.cost_usd` i limicie `--max-cost`.

**Decyzje etapu 1**
- **Czcionka tytułu:** Fredoka w wariancie `Bold` (`cover.title_font_variation`), ta sama rodzina co napis FR-14 (otwarte pytanie 7).
- **Tytuł:** zmniejszany do szerokości strefy, a gdy w jednej linii wyszedłby za mały, dzielony na dwie linie. Podział po dwukropku dostaje premię. Tytuł, którego nie da się zmieścić w 35% rozmiaru (`title_font_pt`), to błąd (kod 1).
- **Wybór stron bez modelu:**
  - przód: pierwsza gotowa strona;
  - miniatury: strony rozłożone równo po książce;
  - `selection: default` w manifeście;
  - na okładkę trafiają tylko strony `ok` z plikiem PNG.
- **Profil CMYK** domyślnie nie jest ustawiony (`cover.cmyk.profile: null`). `cover` kończy się wtedy kodem 1 z instrukcją, skąd wziąć SWOP v2 (na macOS do prób jest `Generic CMYK Profile.icc`).
- **Ostrzeżenie o tytule:** gdy kolor zmienia się (ΔE > `gamut_warn_delta_e`) na ponad 1% jego powierzchni.
- **`front.png`:** przód po przycięciu (bez spadu).

**Wymagania wobec dostawców**
- Adapter obrazu musi obsługiwać `reference_image` (OpenAI: endpoint edycji obrazu). Kontrakt już to przewiduje (§8.2).
- Maska (dorysowanie tyłu na podstawie przodu) nie jest potrzebna w tym podejściu. Zostaje jako możliwe usprawnienie, gdyby kontrola styku zbyt często wymagała ponowień.

Konfiguracja (szkic):

```yaml
# settings.yaml
kdp_cover:                      # wartości KDP, zmienia się je tylko gdy KDP zmieni zasady
  bleed_in: 0.125
  paper_factor_in: 0.002252     # paperback, wnętrze czarno-białe, biały papier (stałe założenie)
  safe_in: 0.125                # min. odległość tekstu od linii cięcia
  spine_safe_in: 0.0625         # min. odległość tekstu grzbietu od linii zgięcia
  spine_text_kdp_min_pages: 79
  barcode: {width_in: 2.0, height_in: 1.2, from_spine_in: 0.25, from_bottom_in: 0.25}

cover:                          # nasze ustawienia
  key_margin_in: 0.375
  spine_text_min_pages: 100
  thumbnails: 3                 # 3–4
  thumbnail_frame_ratio: 2.0
  thumbnail_frame_min_pt: 2
  thumbnail_check_px: 160
  seam_band_in: 0.1
  seam_max_delta_e: 12
  horizon_tolerance: 0.03       # ułamek wysokości
  max_retries: 2
  back_text: false
  title_font: assets/fonts/<czcionka-tytułowa-OFL>.ttf
  cmyk:
    profile: ~/icc/USWebCoatedSWOP.icc   # plik pobiera użytkownik (licencja profilu)
    rendering_intent: perceptual          # albo relative_colorimetric
    black_point_compensation: true
    max_total_ink_pct: 300                # 240 dla drukarni z takim wymaganiem
    gamut_warn_delta_e: 10
    gamut_warn_area_pct: 5
  template_colors:              # skalibrowane na szablonie KDP (tests/fixtures/kdp_templates/)
    live_bleed_pink: {rgb: [255, 175, 176], tolerance: 40}
    barcode_yellow: {rgb: [255, 255, 0], tolerance: 60}
    fold_blue: {rgb: [18, 6, 220], tolerance: 60}
    trim_black: {rgb: [0, 0, 0], tolerance: 80}
  template_tolerance_in: 0.01
```

### ⬜ FR-16: Koszt druku, cena minimalna i tantiemy (poza MVP)

Program liczy koszt druku, cenę minimalną i tantiemy z tabel KDP i podpowiada cenę. Pomaga to już przy wyborze liczby grafik, przed generowaniem.

**Dane: tabele KDP w konfiguracji**
- `config/kdp_pricing.yaml` przepisuje dwie strony pomocy KDP. Każdy rynek ma źródło i datę sprawdzenia (`checked`):
  - **koszt druku** paperback, czarny atrament, papier biały: dla formatu regularnego i dużego, dla każdego rynku: koszt stały dla krótkich książek (24–110 stron, na Amazon.com.au 24–108) oraz koszt stały + koszt za stronę powyżej tego progu;
  - **progi tantiemy:** stawka 50% do ceny progowej włącznie, 60% od następnej ceny, plus cena maksymalna.
- Format jest **duży**, gdy ma ponad 6.12" szerokości albo ponad 9" wysokości. Oba nasze formaty (letter i kwadrat 8.5") są duże.
- Program nie pobiera tych stron automatycznie. Gdy dane mają ponad `stale_after_days` dni (domyślnie 180), pokazuje ostrzeżenie z linkami do aktualizacji.

**Obliczenia**
- `printing_cost = fixed_only`, gdy `pages_in_book ≤ próg_stron`, w przeciwnym razie `fixed + pages_in_book × per_page`.
  - Sprawdzone z kalkulatorem KDP: letter, 104 strony, Amazon.com → $2.84.
- `royalty(cena) = stawka(cena) × cena − printing_cost`. Stawka zależy od progu rynku (np. Amazon.com: 50% do 9.98 USD, 60% od 9.99 USD).
- **Cena minimalna** (wzór KDP: koszt druku / stawka):
  - jeśli `printing_cost / 0.5 ≤ próg_50%`, to `printing_cost / 0.5`;
  - w przeciwnym razie `max(printing_cost / 0.6, cena_od_60%)`.
  - Zaokrąglenie do pełnego centa jak w kalkulatorze KDP, czyli do najbliższego, nie w górę (twarda oprawa: 7.49 / 0.6 = 12.483 → $12.48).
  - **Cenę minimalną liczy się z niezaokrąglonego kosztu druku**, a zaokrągla dopiero wynik. Potwierdzone w kalkulatorze KDP: 202 strony → koszt $4.434 (wyświetlany jako $4.43) → 4.434 / 0.5 = 8.868 → **$8.87**. Z zaokrąglonego kosztu wyszłoby $8.86. Podobnie 402 strony: 7.834 / 0.6 → $13.06, a nie $13.05.
  - **Arytmetyka na `Decimal`**, z wartościami z YAML wczytanymi jako tekst, nigdy na `float`. `round()` na `float` daje niespójne wyniki dla połówek centa (`round(2.955, 2)` = 2.96, ale `round(3.125, 2)` = 3.12).
  - **Zaokrąglanie połówek: `ROUND_HALF_UP`**, potwierdzone w kalkulatorze KDP 16.11.2026. Połówka centa pojawia się tylko przy nieparzystej liczbie stron: koszt za stronę razy parzysta liczba stron daje parzystą liczbę tysięcznych, a dzielenie przez 0.5 i 0.6 nie daje połówki. Kalkulator przyjmuje jednak nieparzyste liczby stron, a `front_matter_pages` może być nieparzyste.
  - **Tantiemę też liczy się z niezaokrąglonego kosztu druku**, a zaokrągla dopiero wynik (`ROUND_HALF_UP`).
  - Przypadki testowe (letter, Amazon.com, cena $14.00, stawka 60%), potwierdzone w kalkulatorze KDP:

    | Strony | Koszt dokładny | Koszt wyświetlany | Tantiema dokładna | Tantiema | Rozstrzyga |
    |---|---|---|---|---|---|
    | 115 | 2.955 | **$2.96** | 8.40 − 2.955 = 5.445 | **$5.45** | tantiema 5.445 (parzysta druga cyfra) idzie w górę, więc nie bankierskie; z zaokrąglonego kosztu wyszłoby $5.44 |
    | 125 | 3.125 | **$3.13** | 8.40 − 3.125 = 5.275 | **$5.28** | koszt 3.125 (parzysta druga cyfra) idzie w górę, więc nie bankierskie ani obcięcie; z zaokrąglonego kosztu wyszłoby $5.27 |
  - **Przypadek graniczny** (potwierdzony w kalkulatorze KDP 16.11.2026: letter, 258 stron → cena minimalna $9.99, stawka 60%): gdy `printing_cost / 0.5` przekracza próg 50%, a `printing_cost / 0.6` wypada poniżej ceny progowej 60%, ceną minimalną jest sama cena progowa. Cena niższa wpadłaby w stawkę 50%, przy której tantiema nie pokryłaby kosztu druku. Na Amazon.com dotyczy to kosztów druku od ok. $4.99 do $5.99.
  - Przypadki testowe (letter, Amazon.com), wszystkie potwierdzone w kalkulatorze KDP 16.11.2026:

    | Strony | Koszt druku | Koszt / 0.5 | Koszt / 0.6 | Oczekiwana cena minimalna |
    |---|---|---|---|---|
    | 202 | $4.43 | $8.87 | – | $8.87, stawka 50% |
    | 258 | $5.39 | $10.77 | $8.98 | $9.99, stawka 60% (przypadek graniczny) |
    | 402 | $7.83 | $15.67 | $13.06 | $13.06, stawka 60% |
- **Ceny tuż pod progiem:** w strefie 50% tantiema jest zawsze niższa niż przy cenie progowej 60%. Na Amazon.com, żeby przy stawce 50% zarobić tyle co przy $9.99, cena musiałaby wynosić $11.99, czyli przekroczyć próg. Program pokazuje to wprost: między ceną minimalną a progiem tantiema jest niższa niż przy cenie progowej, a różnica rośnie im bliżej progu.
- **Strony bez dodatkowego kosztu:** do progu stron koszt druku jest stały. Przy druku jednostronnym i 2 stronach wstępnych do progu 110 stron mieści się 54 grafiki: tyle samo kosztuje druk 30 i 54 grafik. Powyżej każda grafika dodaje 2 strony × `per_page` (Amazon.com, duży format: $0.034).

Przykład (Amazon.com, letter albo kwadrat):

| Grafiki | Strony książki | Koszt druku | Cena minimalna | Tantiema przy $9.99 | Tantiema przy $12.99 |
|---|---|---|---|---|---|
| 30 | 62 | $2.84 | $5.68 | $3.15 | $4.95 |
| 54 | 110 | $2.84 | $5.68 | $3.15 | $4.95 |
| 60 | 122 | $3.07 | $6.15 | $2.92 | $4.72 |
| 100 | 202 | $4.43 | $8.87 | $1.56 | $3.36 |

**Interfejs**
- Komenda `kdp-studio price`:
  - dla gotowej książki: `kdp-studio price <katalog-książki>` (format i `pages_in_book` z manifestu);
  - przed generowaniem: `kdp-studio price --format letter --pages 30` (liczba stron jak w FR-02).
  - Opcje: `--market US,UK,DE,PL` (domyślnie `pricing.markets` z `settings.yaml`, np. `[US]`) i `--price 9.99` (konkretna cena do sprawdzenia, w walucie rynku).
- Wynik dla każdego rynku:
  - koszt druku i cena minimalna;
  - tabela tantiem dla ceny minimalnej, kilku cen z `pricing.candidate_prices` (np. 6.99, 7.99, 8.99, ostatnia cena przed progiem, cena progowa, 12.99, 14.99) i ceny z `--price`;
  - ostrzeżenie o cenach tuż pod progiem;
  - informacja, ile grafik zmieści się jeszcze bez wzrostu kosztu druku.
- `--price` poniżej ceny minimalnej albo powyżej maksymalnej to błąd walidacji (kod 1).
- `generate` po zakończeniu wypisuje jedną linię dla domyślnego rynku: koszt druku, cenę minimalną i tantiemę przy cenie progowej. `manifest.json` dostaje sekcję `pricing` z tymi wartościami i datą danych (`checked`).

**Zastrzeżenia**
- To szacunek z tabel; wiążący jest kalkulator KDP, a wynik zawiera link do niego.
- **Cena w KDP to cena netto.** Na rynkach z VAT Amazon dolicza podatek do ceny wpisanej w KDP, a klient widzi cenę z VAT. Tantiema liczy się od ceny wpisanej przez wydawcę, czyli bez VAT. Program operuje więc wyłącznie cenami netto, a w wyniku dla rynków z VAT zaznacza, że klient zapłaci więcej.
- **Promocje Amazona nie obniżają tantiemy.** Gdy Amazon sam obniża cenę (np. z okazji Black Friday), tantiema nadal liczy się od ceny wpisanej w KDP. Program liczy tylko na tej cenie i nie modeluje promocji.
- Kolorowanki nie są przyjmowane do Expanded Distribution, więc program liczy tylko sprzedaż na Amazonie.
- Twarda oprawa jest poza zakresem (FR-15), więc tabele obejmują tylko paperback.

Konfiguracja (szkic, wartości z KDP sprawdzone 16.11.2026):

```yaml
# config/kdp_pricing.yaml
sources:
  printing_cost: https://kdp.amazon.com/en_US/help/topic/G201834340
  royalty: https://kdp.amazon.com/en_US/help/topic/G201834330
  calculator: https://kdp.amazon.com/en_US/royalty-calculator
checked: 2026-11-16
large_trim: {width_over_in: 6.12, height_over_in: 9.0}
markets:
  US:
    currency: USD
    printing_cost:            # czarny atrament, papier biały
      fixed_only_max_pages: 110
      regular: {fixed_only: 2.30, fixed: 1.00, per_page: 0.012}
      large:   {fixed_only: 2.84, fixed: 1.00, per_page: 0.017}
    royalty: {rate_50_max_price: 9.98, rate_60_min_price: 9.99, max_price: 250}
  UK:
    currency: GBP
    printing_cost:
      fixed_only_max_pages: 110
      regular: {fixed_only: 1.93, fixed: 0.85, per_page: 0.010}
      large:   {fixed_only: 2.15, fixed: 0.85, per_page: 0.012}
    royalty: {rate_50_max_price: 7.98, rate_60_min_price: 7.99, max_price: 250}
  EU:                         # DE, FR, ES, IT, NL, IE, BE
    currency: EUR
    printing_cost:
      fixed_only_max_pages: 110
      regular: {fixed_only: 2.05, fixed: 0.75, per_page: 0.012}
      large:   {fixed_only: 2.48, fixed: 0.75, per_page: 0.016}
    royalty: {rate_50_max_price: 9.98, rate_60_min_price: 9.99, max_price: 250}
  PL:
    currency: PLN
    printing_cost:
      fixed_only_max_pages: 110
      regular: {fixed_only: 9.58, fixed: 3.51, per_page: 0.056}
      large:   {fixed_only: 11.61, fixed: 3.51, per_page: 0.075}
    royalty: {rate_50_max_price: 39, rate_60_min_price: 40, max_price: 1200}
  # CA, AU, SE, JP – analogicznie, z tych samych stron KDP

# settings.yaml
pricing:
  markets: [US]
  candidate_prices: {US: [6.99, 7.99, 8.99, 9.98, 9.99, 12.99, 14.99]}
  stale_after_days: 180
```

### ⬜ FR-18: Lokalne generowanie grafik przez ComfyUI (poza MVP)

Adapter `ComfyUIImageProvider` generuje grafiki na serwerze ComfyUI w sieci lokalnej, zamiast w chmurze. Grafiki nic nie kosztują, a model i workflow wybiera użytkownik. Ograniczenie sprzętowe: **generowanie maksymalnie 512 × 512 px albo 768 × 512 px**.

**Włączanie**
- `--image-provider comfyui` albo `providers.image: comfyui` w `settings.yaml`.
- Adres serwera w `settings.yaml` (`comfyui.url`, np. `http://192.168.1.50:8188`) albo w zmiennej `COMFYUI_URL`, która ma pierwszeństwo.
- Zgodnie z NFR-02: nowy plik `providers/comfyui_image.py` i wpis w rejestrze; `pipeline/` pozostaje bez zmian, poza rozszerzeniem kontraktu `ImageRequest` opisanym niżej.

**Workflow**
- Użytkownik przygotowuje w ComfyUI workflow, który daje dobry line art, i eksportuje go w formacie API (*File → Export (API)*). Plik trafia do `config/comfyui/` i jest wskazany w `comfyui.workflow`.
- W wartościach węzłów workflow użytkownik wpisuje znaczniki, które adapter podmienia przed wysłaniem:
  - `{{positive}}` i `{{negative}}`: prompt pozytywny i negatywny;
  - `{{seed}}`: ziarno;
  - `{{width}}` i `{{height}}`: rozmiar generowania.
  Znaczniki liczbowe są podmieniane na liczby, nie na tekst.
- Walidacja przy starcie: plik jest w formacie API (węzły z `class_type` i `inputs`), zawiera wszystkie wymagane znaczniki, a `comfyui.output_node` wskazuje istniejący węzeł zapisu obrazu. Błąd to kod 1, przed pierwszym wywołaniem.

**Rozmiar generowania**
- Rozmiary z konfiguracji, dla każdej proporcji osobno, z twardym limitem `comfyui.max_size` (dłuższy bok ≤ 768 px, krótszy ≤ 512 px):
  - `1:1` (kwadrat) → 512 × 512;
  - `3:4` (letter) → 512 × 768 (pion; proporcja 2:3, różnicę wyrównuje biały margines w FR-06, jak w adapterze OpenAI).
- `supported_aspects()` zwraca tylko proporcje z konfiguracji, więc nieobsługiwany format jest wykrywany przed pierwszym wywołaniem (jak dziś).
- Rozmiar wyniku może być większy niż rozmiar generowania, jeśli workflow ma węzeł powiększania (np. model 2–4× po wygenerowaniu). Limit dotyczy generowania, a adapter zapisuje rzeczywiste wymiary pliku w `ImageResult`.

**Niska rozdzielczość a wiek odbiorcy**
- Przy 512 px wektoryzacja (D6) musi powiększyć grafikę ok. 4–5 razy. Grube linie dla młodszych dzieci to wytrzymują, ale drobne wzory dla nastolatków i dorosłych tracą szczegóły.
- W `ages.yaml` dochodzi `min_source_px`: najkrótszy bok surowej grafiki, przy którym profil daje dobre strony (szkic: przedszkole i wczesnoszkolne 512, szkolne 768, nastolatki i dorośli 1024).
- Walidacja (FR-01) ostrzega, gdy rozmiar wyniku dostawcy jest mniejszy niż `min_source_px` wybranego wieku, i podpowiada węzeł powiększania w workflow. Z `--strict` to błąd.

**Prompt: pozytywny i negatywny osobno**
- Modele Stable Diffusion źle rozumieją zakazy w prompcie pozytywnym („no text” potrafi dodać tekst), a koder CLIP czyta tylko ok. 77 tokenów, więc długi blok stylu z FR-04 zostałby obcięty.
- Kontrakt `ImageRequest` dostaje strukturę promptu obok gotowego tekstu: `scene`, części bloku stylu i listę zakazów (`negative`).
  - Adapter OpenAI składa z tego dokładnie ten sam prompt co dziś (test przypinający FR-04 bez zmian).
  - Adapter ComfyUI buduje krótki prompt pozytywny z szablonu `comfyui.positive_template` (np. słowo-klucz modelu lub LoRA + `{scene}` + `{style_keywords}`) i prompt negatywny z `comfyui.negative` (np. `text, watermark, grid, panels, collage, shading, grayscale, color`).
- Szablony są w konfiguracji, bo zależą od modelu w workflow (SD 1.5, SDXL, Flux mają różne potrzeby).

**Model docelowy: Stable Diffusion 1.5** (`v1-5-pruned-emaonly`, wagi tylko do generowania)
- Model był trenowany na 512 × 512, więc to jego naturalny rozmiar. Pion 512 × 768 działa, ale częściej powtarza elementy (np. dwie głowy jednej postaci), co wyłapuje kontrola jakości.
- Bazowy SD 1.5 słabo trzyma się złożonych opisów i ma skłonność do cieniowania i szarości. Domyślne ustawienia są więc pod niego dobrane:
  - prompt pozytywny w stylu tagów, krótki, z najważniejszym na początku (scena przed stylem);
  - rozbudowany prompt negatywny, obejmujący też typowe wady SD 1.5 (`blurry, lowres, deformed, extra limbs`);
  - sceny z 1–3 postaciami. Przy złożonych scenach dla starszych wieków trzeba się liczyć z większą liczbą odrzuceń w QA.
- Czysty line art zwykle wymaga dodatkowego modelu w workflow: LoRA albo checkpointu wytrenowanego na kolorowankach (wybór po próbach, §14 pytanie 8).
- **Licencja:** SD 1.5 jest na licencji CreativeML OpenRAIL-M, która dopuszcza użycie komercyjne z ograniczeniami użycia. Każda dodana LoRA lub checkpoint ma własną licencję i musi dopuszczać sprzedaż wygenerowanych obrazów. Manifest zapisuje nazwy plików modeli z workflow, żeby dało się to sprawdzić dla każdej książki.

**Komunikacja z serwerem**
- Przed pierwszą stroną: `GET /system_stats`. Brak odpowiedzi to błąd krytyczny („serwer ComfyUI niedostępny”, kod 4), zanim program wywoła cokolwiek płatnego.
- Strona:
  1. `POST /prompt` z workflow po podmianie znaczników → `prompt_id`. Odpowiedź z `node_errors` to błąd krytyczny (zły workflow).
  2. Czekanie na wynik przez odpytywanie `GET /history/{prompt_id}` co `comfyui.poll_interval_s`, z limitem `comfyui.timeout_s` (domyślnie 300 s). Przekroczenie czasu to `POST /interrupt` i niekrytyczny błąd strony.
  3. Pobranie obrazu przez `GET /view?filename=…&subfolder=…&type=output` z węzła `output_node`.
- Błąd wykonania na serwerze (np. brak pamięci GPU) to błąd krytyczny z podpowiedzią zmniejszenia rozmiaru, bo kolejne strony skończyłyby się tak samo.
- Równoległość: serwer ComfyUI ma jedną kolejkę na jedno GPU, więc liczba równoczesnych stron to `min(--concurrency, comfyui.max_concurrency)`, domyślnie 1.

**Ziarno i koszt**
- Każda strona dostaje losowe ziarno, chyba że podano `--seed`. Ziarno trafia do manifestu (NFR-08), więc stronę da się odtworzyć tym samym workflow i modelem. Manifest zapisuje też nazwę pliku workflow i jego sumę kontrolną.
- Koszt grafiki to 0 USD (FR-10), albo `comfyui.cost_per_image_usd`, jeśli ktoś chce liczyć np. prąd. Limit budżetu dotyczy wtedy tylko wywołań tekstowych i kontroli jakości.

**Obraz referencyjny**
- `reference_image` (np. kolorowanie przodu okładki w FR-15) wymaga osobnego workflow z węzłem wczytującym obraz i znacznikiem `{{reference_image}}`. Adapter wysyła obraz przez `POST /upload/image`, a w workflow podmienia znacznik na nazwę pliku. Bez skonfigurowanego `comfyui.reference_workflow` adapter zgłasza, że referencja jest nieobsługiwana.

**Bezpieczeństwo i sieć**
- Serwer ComfyUI domyślnie nie ma uwierzytelniania, więc ma być dostępny tylko w sieci lokalnej. Program nie wymusza HTTPS dla adresów prywatnych (192.168.x.x, 10.x.x.x, `.local`), a dla innych adresów ostrzega.
- Dla serwera za reverse proxy opcjonalny token w zmiennej `COMFYUI_TOKEN` (nagłówek `Authorization: Bearer …`). Token nie trafia do logów ani manifestu (NFR-10).

**Testy**
- Bez prawdziwego serwera: fałszywy transport HTTP odpowiada na `/system_stats`, `/prompt`, `/history` i `/view`. Testy obejmują podmianę znaczników, walidację workflow, przekroczenie czasu, `node_errors` i brak serwera.

Generowanie pomysłów i kontrola jakości nadal korzystają z modeli w chmurze. Pełna praca offline wymagałaby lokalnego modelu tekstowego i modelu z wizją, co jest poza tym wymaganiem.

Konfiguracja (szkic):

```yaml
# settings.yaml
comfyui:
  url: http://192.168.1.50:8188      # COMFYUI_URL nadpisuje
  workflow: config/comfyui/lineart_sd15.json   # checkpoint: v1-5-pruned-emaonly (+ LoRA do line artu)
  output_node: "9"                   # id węzła SaveImage w pliku workflow
  reference_workflow: null           # opcjonalnie, dla reference_image
  max_size: {long: 768, short: 512}  # limit sprzętowy generowania
  sizes:
    "1:1": [512, 512]
    "3:4": [512, 768]
  positive_template: "{scene}, coloring book page, black and white line art, thick clean outlines, white background, {style_keywords}"
  negative: "text, letters, watermark, signature, grid, multiple panels, collage, frame, shading, grayscale, color, gradient, blurry, lowres, deformed, extra limbs"
  max_concurrency: 1
  poll_interval_s: 2
  timeout_s: 300
  cost_per_image_usd: 0
```

## 7. Profile (konfiguracja YAML)

Profile są danymi, nie kodem: strojenie jakości nie może wymagać zmian w Pythonie.

### 7.1 Profile wieku: `config/ages.yaml`

| Klucz | Linia | Obiekty | Tło | Wypełnienia | Fragment promptu (szkic) |
|---|---|---|---|---|---|
| `przedszkole` | bardzo gruba | 1 duży, proste kształty | brak | duże, zamknięte pola | `very thick bold outlines, one large simple subject, minimal details, no background, large closed areas, the whole drawing fits inside the image with white space on every side, for toddlers` |
| `wczesnoszkolne` | gruba | 1–3 | proste | średnie | `thick clean outlines, simple scene with 1-3 subjects, simple background, the whole scene fits inside the image with white space on every side, nothing cut off by the edges, for kids 6-8` |
| `szkolne` | średnia | pełna scena | tak | więcej detali | `medium outlines, full scene, moderate detail, background lines such as floor, walls or horizon may run to the edges but no object is cut off, for kids 9-12` |
| `nastolatki` | cienka | scena, stylizacja | pełne | wzory | `fine clean lines, detailed scene, decorative patterns, detailed background may extend to the edges of the image, for teens` |
| `dorosli` | bardzo cienka | wzory, mandale, zentangle | gęste | drobne pola | `fine intricate line work, highly detailed patterns, many small areas to color, background and patterns may extend to the edges of the image, for adults` |

Każdy profil ma też minimalny udział stron z kilkoma postaciami (`multi_subject_share`, FR-03b) oraz parametry obróbki (np. `min_speck_area`, wygładzanie potrace). Parametry obróbki różnią się, bo cienkie linie dla dorosłych wymagają innego progowania niż grube linie dla przedszkolaków. Fragment promptu określa też, co może dotykać krawędzi grafiki: dla najmłodszych cała scena mieści się w kadrze z białym marginesem, a w szczegółowych scenach dla starszych tło może sięgać krawędzi. Główny motyw nigdy nie jest ucięty (wskazówka kompozycji formatu, §7.3).

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
  composition_hint: "vertical composition, main subjects fill most of the portrait frame, fully inside the image, not cut off by the edges"
square:            # 8.5" × 8.5"
  trim_in: [8.5, 8.5]
  dpi: 300
  page_px: [2550, 2550]
  aspect: "1:1"
  safe_margin_in: 0.5
  composition_hint: "centered composition, one clear focal point (a character, a small group or a concentric design), main subjects fully inside the image, not cut off by the edges"
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
      ├─ IdeaGenerator ── TextProvider ──► pomysły               (FR-03)
      ├─ IdeaReviewer  ── TextProvider ──► ideas.json            (FR-03a, FR-03b)
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
    #   + struktura promptu (scene, części stylu, negative) dla dostawców z osobnym promptem negatywnym (FR-18)
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

### 8.5 Adapter lokalny: ComfyUI
- Serwer ComfyUI w sieci lokalnej, workflow użytkownika w formacie API, generowanie maks. 512 × 512 albo 768 × 512 px. Szczegóły w FR-18.

## 9. Interfejs CLI

### 9.1 Komendy

```bash
# Generowanie książki: wszystkie trzy kroki po kolei (FR-17)
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
  [--image-quality low|medium|high] \
  [--no-review-ideas] \
  [--belongs-to-page] \
  [--strict] \
  [--image-provider openai|comfyui] \
  [--seed 1234] \
  [--log-level info|debug]

# Generowanie krokowe (FR-17)
kdp-studio ideas --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30 \
  [--output-dir ./output] [--no-review-ideas] [--strict] [--belongs-to-page] [--max-cost 5.00]
kdp-studio ideas ./output/dinozaury_przedszkole_kawaii_square --redo idea_07,idea_19
kdp-studio images ./output/dinozaury_przedszkole_kawaii_square \
  [--qa] [--image-quality low|medium|high] [--concurrency 4] [--max-cost 5.00] \
  [--belongs-to-page|--no-belongs-to-page]
kdp-studio finalize ./output/dinozaury_przedszkole_kawaii_square
# Każdy krok przyjmuje też --log-level info|debug (NFR-09)
# Wznowienie przerwanego kroku = ponowne uruchomienie tej samej komendy

# Lista dostępnych profili
kdp-studio profiles [age|style|format]

# Okładka do gotowej książki (FR-15, poza MVP)
kdp-studio cover ./output/dinozaury_przedszkole_kawaii_square \
  [--cover-page 07] \
  [--thumbnails 03,12,21] \
  [--template kdp_template.png] \
  [--color|--no-color] [--image-quality low|medium|high] \
  [--select-pages|--no-select-pages] [--back-text] \
  [--qa] \
  [--max-cost 1.00]

# Koszt druku, cena minimalna i tantiemy (FR-16, poza MVP)
kdp-studio price ./output/dinozaury_przedszkole_kawaii_square [--market US,UK,DE,PL] [--price 9.99]
kdp-studio price --format letter --pages 30 [--market US]
```

### 9.2 Konfiguracja i sekrety
- Sekrety wyłącznie w zmiennych środowiskowych lub `.env` (w `.gitignore`): `OPENAI_API_KEY`, później `GEMINI_API_KEY`, a dla ComfyUI opcjonalnie `COMFYUI_URL` i `COMFYUI_TOKEN` (FR-18).
- Ustawienia domyślne w `config/settings.yaml` (dostawcy, modele, cenniki, `reserve_ratio`, `front_matter_pages`, `review_ideas`, limity różnorodności `diversity` (FR-03b), `qa`, `qa_max_retries`, domyślna równoległość, poziom logu `log_level` (NFR-09), cennik API `api_pricing` i limit kosztu `max_cost_usd` (FR-10)). Flagi CLI nadpisują `settings.yaml`.

### 9.3 Kody wyjścia

| Kod | Znaczenie |
|---|---|
| 0 | Sukces: wszystkie strony `ok` |
| 1 | Błąd walidacji wejścia lub konfiguracji |
| 2 | Zakończono częściowo: brakuje stron `ok` (failed lub QA) |
| 3 | Przekroczony budżet (`--max-cost`, FR-10): status `budget_exceeded` |
| 4 | Błąd dostawcy API po wyczerpaniu ponowień |

## 10. Struktura katalogu wyjściowego

```
output/dinozaury_przedszkole_kawaii_square/
├── manifest.json
├── ideas.json
├── canva.md                        # instrukcja składania w Canvie (sekcja 10.1)
├── front_belongs_to.png            # tylko z --belongs-to-page (FR-14, poza MVP)
├── page_01.png … page_30.png      # pełne strony do importu w Canvie, 300 DPI
├── svg/page_01.svg …               # archiwum wektorowe (nie do Canvy)
├── raw/page_01.png …               # surowe wyniki z modelu
├── rejected/page_07_try1.png …     # surowe grafiki odrzucone przez QA (powód w manifeście)
├── kdp-studio.log                  # logi strukturalne wszystkich kroków, wiersze JSON (NFR-09)
├── .kdp-studio.lock                # tylko w trakcie kroku (FR-17)
└── cover/                          # tylko po `kdp-studio cover` (FR-15, poza MVP)
    ├── cover.pdf                   # gotowy plik okładki do KDP, CMYK
    ├── cover_proof.png, cover_gamut.png   # symulacja druku i mapa zmian kolorów
    ├── cover.png, front.png
    ├── cover_preview.png           # z liniami cięcia, strefami i polem kodu
    └── raw/                        # front_sketch, front_color_tryN, back_tryN, contact_sheet
```

Przykład wpisu strony w `manifest.json`:

```json
{
  "page": 7,
  "idea_id": "idea_07",
  "status": "ok",
  "action": null,
  "edited_by_user": false,
  "attempts": 2,
  "provider": "openai",
  "model": "gpt-image-2.5-flare",
  "quality": "medium",
  "prompt": "…",
  "prompt_sha256": "…",
  "raw_sha256": "…",
  "final": {"raw_sha256": "…", "postprocess_sha256": "…"},
  "qa": {"pass": true, "issues": []},
  "cost_usd": 0.08,
  "duration_s": 14.2,
  "files": {"png": "page_07.png", "svg": "svg/page_07.svg", "raw": "raw/page_07.png"}
}
```

### 10.1 Składanie książki w Canvie

Treść `canva.md` (wartości w nawiasach wypełnia program):

1. Utwórz projekt o wymiarach własnych `[trim_in]` cali (np. 8.5 × 11 in).
2. Strony wstępne: `[front_matter_pages]` (domyślnie strona tytułowa i „This book belongs to…”). Jeśli książka powstała z `--belongs-to-page` (FR-14), wstaw `front_belongs_to.png` na drugą stronę i rozciągnij na całą stronę, jak grafiki. W przeciwnym razie zaprojektuj tę stronę w Canvie.
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
| NFR-09 | Obserwowalność | Logi strukturalne (poziomy INFO/DEBUG), pasek postępu w konsoli, podsumowanie kosztów i czasu na końcu. Logi to wiersze JSON w `kdp-studio.log` w katalogu książki, dopisywane przez każdy krok. `info` zapisuje kroki, strony, ostrzeżenia i błędy z czasami, `debug` dodatkowo każde wywołanie API (czas, tokeny, prompt grafiki). Do pliku trafiają tylko logi programu, nie bibliotek dostawców (NFR-10). Każdy krok podaje w konsoli swój czas, a `generate` na końcu czasy kroków i całości. |
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
| 1. MVP CLI | FR-01–FR-13 i FR-17 (generowanie krokowe) z dostawcą OpenAI | Kompletna 30-stronicowa książka w katalogu, złożona w Canvie według `canva.md` i przyjęta przez kreator KDP bez błędów |
| 1a. Strona „This book belongs to…” | FR-14: ramka w motywie książki z modelu obrazu, napis i miejsce na imię dokładane przez program, przełącznik `--belongs-to-page` | Na 3 tematach × 5 wiekach strona pasuje stylem do grafik, a pole na imię jest puste bez ręcznych poprawek w ≥ 80% przypadków (reszta przez układ zapasowy) |
| 1b. Okładka | FR-15: komenda `cover`, geometria z wzorów KDP, przód z pokolorowanej strony z tytułem, tył z grzbietem dopasowany do przodu, miniatury w ramkach, PDF | Na 3 książkach (letter i kwadrat, różna liczba stron) PDF przechodzi kreator KDP bez błędów, a podgląd KDP nie pokazuje szwu na grzbiecie ani elementów w polu kodu |
| 1c. Cena i tantiemy | FR-16: tabele kosztów druku i progów tantiem KDP w konfiguracji, komenda `price`, podsumowanie w `generate` i manifeście | Koszt druku i cena minimalna zgadzają się z kalkulatorem KDP dla letter i kwadratu przy 30, 54 i 100 grafikach na rynkach US, UK, DE i PL |
| 2. PDF w skrypcie (opcjonalnie) | Automatyczne składanie wnętrza (strony wstępne, puste strony po grafikach) zamiast ręcznego w Canvie | Uruchamiamy, gdy ręczne składanie w Canvie zacznie spowalniać wydawanie kolejnych książek |
| 3. Gemini | Adapter `GeminiImageProvider` i porównanie jakości z OpenAI | Przełączenie przez `--image-provider gemini` |
| 3a. ComfyUI lokalnie | FR-18: adapter `ComfyUIImageProvider`, workflow użytkownika w formacie API, osobny prompt negatywny, limit 512 × 512 / 768 × 512 px | Książka dla wieku przedszkolnego i wczesnoszkolnego (letter i kwadrat) przechodzi `finalize` i QA na poziomie zbliżonym do OpenAI; dla starszych wieków z węzłem powiększania w workflow |
| 4. UI | Streamlit albo Gradio (React dopiero przy produkcie dla innych) | Generowanie bez terminala |

Stan na 17.11.2026 (sekcja 0): zakres etapu 1 jest zrobiony, a jego kryterium wyjścia (książka przyjęta przez kreator KDP) czeka na pierwsze złożenie w Canvie. Etap 1a (FR-14) ma kod; jego kryterium wyjścia wymaga prób na prawdziwych tematach. Etap 1b (FR-15) ma kod wszystkich trzech etapów; jego kryterium wyjścia wymaga próby w kreatorze KDP. Etap 1c ma gotową specyfikację.

## 14. Otwarte pytania

1. Startowa lista stylów i dozwolone połączenia wiek × styl.
2. Język metadanych książki (`title`, `description`, `keywords`): angielski (rynek US) czy parametr `--lang`?
3. Czy QA ma być domyślnie włączone po etapie 0, gdy znany będzie jego koszt i skuteczność?
4. Czy używać pierwszej zaakceptowanej strony jako referencji stylu dla kolejnych (spójność kontra koszt i czas)?
5. Wybór modelu tekstowego i domyślnej jakości (`quality`) modelu obrazu. Jakość sprawdzić porównaniem `low` i `medium` na tych samych pomysłach (FR-17).
6. ~~FR-14: wybór czcionki z licencją OFL i wariant polski napisu.~~ Rozstrzygnięte 16.11.2026: Fredoka, napis po angielsku, inny język przez `belongs_to_page.text`.
7. FR-15: ~~wybór czcionki tytułowej (OFL)~~ Fredoka Bold (16.11.2026). Kolory szablonu KDP są skalibrowane na szablonach kwadratu i letter. Profil CMYK (SWOP v2 czy GRACoL 2006) i sposób konwersji (`perceptual` czy `relative_colorimetric`) do wyboru po porównaniu `cover_proof.png` z egzemplarzem próbnym z KDP.
8. FR-18: model bazowy to SD 1.5 (`v1-5-pruned-emaonly`), a pion 512 × 768 jest przyjęty jako dozwolony. Do ustalenia po próbach: LoRA lub checkpoint do line artu (z licencją dopuszczającą sprzedaż) i węzeł powiększania dla starszych wieków.

## 14a. Pomysły na rozwój

Kierunki do rozważenia po MVP, jeszcze bez wymagań.

**`--humanize/--no-humanize`: uczłowieczone zwierzęta**
- Zwierzęta stoją na tylnych łapkach, noszą ubranka pasujące do sceny, używają łapek jak rąk i robią ludzkie rzeczy (pieczenie, łyżwy, ubieranie choinki).
- Reguła trafia do generatora pomysłów (FR-03), do weryfikacji pomysłów (FR-03a), do kontroli jakości (FR-07) i jako linia `Characters: …` do wspólnego bloku stylu (FR-04), więc obowiązuje jednakowo na każdej stronie. Jedna wartość na całą książkę, bo mieszanie zwierząt naturalnych i uczłowieczonych wygląda niespójnie.
- Wartość domyślna w profilu stylu (`humanize` w `styles.yaml`), flaga ją nadpisuje.

**`--character`: opis bohaterów**
- Tekst albo plik (`--character @bohaterowie/lisek.md`), flaga powtarzalna: jedno wystąpienie to jeden bohater. Przykłady: konkretny bohater dla nastolatków, maskotka serii, postacie z własnych opowiadań.
- Opis ma dwie warstwy. Wygląd (sylwetka, ubranie, znaki szczególne) trafia do każdego promptu obrazu. Imię i charakter trafiają tylko do generatora pomysłów, nigdy do promptu obrazu, bo model mógłby próbować napisać imię.
- Generator umieszcza bohaterów na większości stron, a weryfikacja pomysłów sprawdza zgodność z opisem.
- Ograniczenie: opis tekstowy zapewnia ten sam strój i znaki szczególne, ale twarz i proporcje różnią się między stronami. Pełną spójność dałaby karta postaci generowana raz i podawana jako `reference_image` do każdej strony.
- Opis nie może odwoływać się do postaci chronionych prawem autorskim ani do prawdziwych osób.

**`--scenes`: własne sceny zamiast wymyślonych**
- Plik z listą scen podanych przez użytkownika zastępuje generowanie pomysłów (FR-03). Weryfikacja, prompty i dalsze kroki działają bez zmian.
- Zastosowanie: zbiór własnych opowiadań, w którym część stron to kolorowanki z wybranych scen, razem z `--character` dla bohaterów opowiadań.

## 15. Źródła i referencje
- KDP: rozmiary stron (trim sizes), wymagania druku i ujawnianie treści AI: https://kdp.amazon.com/help/topic/GVBQ3CMEQW3W2VL6
- OpenAI Image API: https://developers.openai.com/api/docs/guides/image-generation
- Gemini API (Nano Banana), cennik: https://ai.google.dev/gemini-api/docs/pricing
- ComfyUI: API serwera (`/prompt`, `/history`, `/view`, `/upload/image`, format API workflow): https://docs.comfy.org/development/comfyui-server/comms_routes
- Adobe: kredyty generatywne (zakres użycia): https://helpx.adobe.com/firefly/using/generative-credits-faq.html
- Canva: formaty i limity przesyłanych plików (PNG, SVG): https://www.canva.com/help/upload-formats-requirements/
- KDP: wymagania dla plików do druku (300 DPI, spłaszczanie przezroczystości): https://kdp.amazon.com/help/topic/G202145060
- KDP: okładka paperback (CMYK zalecany, bez mieszania przestrzeni barw, profile kolorów usuwane przed publikacją, brak wskazanego profilu i limitu farb): https://kdp.amazon.com/en_US/help/topic/G201953020
- Poradniki zewnętrzne o CMYK dla okładek (profile SWOP v2 / GRACoL; limit farb 240% w IngramSpark): https://www.ebookpbook.com/2026/04/30/rgb-vs-cmyk-book-covers/, https://www.kdpeasy.com/guides/kdp-cover-requirements
