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
| FR-07 | ✅ | #14, #49 | Kryterium `theme_unclear` i ponowienie tego samego pomysłu przed rezerwą (`qa_max_ideas`). |
| FR-08 | ✅ | #13, #23 | |
| FR-09 | ↪ FR-17 | #23 | |
| FR-10 | ✅ | #29, #50 | Cennik `api_pricing` w `settings.yaml`. Limit na całą książkę, razem z poprawkami (zmiana z 17.11.2026; wcześniej na jedno uruchomienie komendy). |
| FR-11 | ↪ FR-17 | #23 | |
| FR-12 | ✅ | #7 | |
| FR-13 | ✅ | #13 | |
| FR-14 | ✅ | #30, #46 | Poza MVP. Specyfikacja: #16. Czcionka Fredoka (OFL), układ zapasowy z grafiką pierwszej strony. Polecenie `belongs-to` i krok `generate --belongs-to-page` między `images` a `finalize` (zmiana z 17.11). |
| FR-15 | ✅ | #31, #32, #39, #40, #41, #47 | Poza MVP. Specyfikacja: #17. Trzy etapy zrobione: geometria, szablon, układ, CMYK i PDF; kolorowy przód z modelu; tył z grzbietem z modelu z kontrolą styku, wybór stron i QA modelem z wizją, opis na tyle. `generate --cover` jako ostatni krok generowania. Planowane: opcjonalny pas na grzbiecie zamiast wygładzenia styku (#67). Kryterium wyjścia etapu 1b (plik przyjęty przez KDP) czeka na próbę. |
| FR-16 | ✅ | #65 | Poza MVP. Specyfikacja: #18. Polecenie `price` (gotowa książka albo `--format`/`--pages`), sekcja `pricing` w manifeście i linia z ceną po kroku 3. Dane cenowe w `config/markets.yaml` (FR-19). |
| FR-17 | ✅ | #23, #24 | |
| FR-18 | ⬜ | | Poza MVP. Specyfikacja: #25. |
| FR-19 | ✅ | #56 | Poza MVP. Specyfikacja: #42. Rynek docelowy Amazona (`--market`), dane rynków w `config/markets.yaml`. Rynki poza US i UK piszą napisy czcionką Baloo 2 (Fredoka nie ma polskich liter); JP czeka na czcionkę z japońskimi znakami. |
| FR-20 | ✅ | #61 | Poza MVP. Specyfikacja: #44. Plik parametrów książki `--config-file`, flagi mają pierwszeństwo. |
| FR-21 | ⬜ | | Specyfikacja: #51. Chronione nazwy w temacie jako inspiracja, kontrola tekstów w kodzie (`config/protected_names.yaml`) i kryterium QA. Uzupełnia FR-03, FR-03a, FR-07 i NFR-12. |
| FR-22 | ✅ | #59 | Poza MVP (etap 2 roadmapy). Specyfikacja: #53. `interior.pdf` składany przez program w `finalize`, druk jednostronny jako opcja (domyślnie włączony). |
| FR-23 | ✅ | #58 | Poza MVP. Specyfikacja: #53. Strony wstępne: tytułowa do kolorowania albo FR-14, prawa autorskie w języku rynku, instrukcja z postacią z książki; polecenie `front-matter`. Zrobione przed FR-22: strony jako PNG, `interior.pdf` dochodzi z FR-22. |
| FR-24 | ✅ | #76, #77 | Poza MVP. Zgłoszenie: #71. A+ Content: polecenie `aplus`, grafiki modułów składane przez program (wachlarz okładek, kolumny, nakładka z faktami), teksty z kontrolą zakazanych sformułowań, podgląd `aplus.html`. Alt text każdej grafiki. Kolumny z grafikami z modelu (motywy w profilu wieku): ⬜ #80. |
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
| D8 | **Druk jednostronny** (grafika, potem pusta strona), od FR-22 domyślny, z opcją dwustronnego | Standard w kolorowankach, bo kredki i flamastry nie przebijają na następną grafikę. Wpływa na liczenie stron (FR-02). |
| D9 | **PDF wnętrza składa program** (FR-22); wcześniej Canva | W MVP wnętrze składało się ręcznie w Canvie z pełnych stron PNG (Canva przyjmuje SVG tylko do 3 MB, 150–200 px szerokości i w profilu SVG 1.1, a gęsty line art z potrace przekracza te limity, więc dostaje PNG). Od FR-22 program pisze gotowy `interior.pdf` ze stronami wstępnymi (FR-23) i pustymi stronami. Strony PNG i `canva.md` zostają jako ręczna droga. |
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

Parametry techniczne opisuje sekcja 9. Wszystkie parametry można też podać w pliku `--config-file` (FR-20, poza MVP); flaga ma wtedy pierwszeństwo przed plikiem.

## 6. Wymagania funkcjonalne

### ✅ FR-01: Walidacja wejścia
- Wszystkie parametry są walidowane przed pierwszym wywołaniem API.
- Nieznany `--age`, `--style` albo `--format` kończy program błędem z listą dozwolonych wartości.
- `--pages` musi być w zakresie 1–200.

### ✅ FR-02: Walidacja liczby stron względem KDP
- Program liczy `pages_in_book = pages * 2 + front_matter_pages` (od FR-22: `front_matter_pages + pages × 2` przy druku jednostronnym albo `× 1` przy dwustronnym, zaokrąglone w górę do parzystej, a `front_matter_pages` wynika z FR-23; dotąd druk jednostronny, `front_matter_pages` z konfiguracji, domyślnie 2: strona tytułowa i „This book belongs to…”).
- Jeśli `pages_in_book < 24` (minimum KDP dla paperbacka), program pokazuje ostrzeżenie z minimalną poprawną liczbą grafik. Z flagą `--strict` kończy się błędem.
- Jeśli `pages_in_book` przekracza ostatni próg tabeli marginesów KDP (sekcja 7.4), program kończy się błędem walidacji.

### ✅ FR-03: Generowanie pomysłów i metadanych książki
- **Jedno** wywołanie LLM ze strukturyzowanym wyjściem (JSON Schema lub structured outputs).
- Wejście promptu: temat, profil wieku, profil stylu, format, liczba stron.
- Wyjście (`ideas.json`):
  - `book`: `title`, `subtitle`, `keywords` (do 7) i części opisu `headline`, `about`, `benefits`, `closing` (opis do KDP składa z nich program, niżej); `description` to ich zwykły tekst;
  - `pages`: lista `pages + ceil(pages * reserve_ratio)` pomysłów (`reserve_ratio` domyślnie 0.2), każdy z polami `id`, `title`, `scene` (opis sceny po angielsku, gotowy do promptu), `elements` (lista obiektów).
- Pomysły muszą:
  - wyraźnie pasować do tematu: główny motyw, czynność albo dobrze widoczny przedmiot jest typowy dla tematu i jest na liście `elements`. Motywy zwyczajowo kojarzone z tematem się liczą (dla świąt także bałwan, sanki, śnieg). Ogólne słowa („holiday”, „festive”) nie wystarczą, a scena, która wyglądałaby tak samo w każdy inny dzień (tort urodzinowy z koroną, herbatka, kosz z praniem), potrzebuje konkretnego elementu tematu (dla świąt: pierniczki, choinka, skarpety na prezenty);
  - być unikalne w obrębie książki (różne sceny, nie tylko inne sformułowania);
  - pasować do formatu: `square` to centralny obiekt lub kompozycja koncentryczna, `letter` to postać lub scena w pionie;
  - pasować do wieku: liczba obiektów i złożoność sceny zgodne z profilem wieku.
- Treści nie mogą zawierać postaci chronionych prawem autorskim ani znaków towarowych. LLM dostaje to jako twarde ograniczenie, a temat z chronioną nazwą i kontrolę tekstów w kodzie opisuje FR-21.
- **Tytuł, podtytuł i słowa kluczowe** (zmiana z 18.11.2026). Wyszukiwarka Amazona waży najbardziej tytuł i podtytuł, potem słowa kluczowe. Tytuł i podtytuł są też na okładce (FR-15), więc muszą się tam dobrze czytać. Prompt mówi to modelowi wprost i opisuje rolę każdego pola:
  - **tytuł:** temat słowami, których szukają kupujący, z „Coloring Book” rynku (FR-19), gdy pasuje; krótki, cel do 60 znaków (KDP: dłuższe tytuły kupujący przeskakują);
  - **podtytuł:** jedna grupa odbiorców dokładnie frazą rynku (np. „for Kids Ages 6–8”), opcjonalnie krótko, co jest w środku; jako zwykłe zdanie, bez listy grup rozdzielonych `|` albo przecinkami; cel do 80 znaków, czyli jeden lub dwa wiersze na okładce;
  - **słowa kluczowe:** dokładnie 7 fraz, które wpisują kupujący, rozplanowanych: 2–3 na inne grupy odbiorców (zakresy wieku nachodzące na docelowy, np. „kids ages 5-8” albo „ages 4-8” dla 6–8, dziewczynki i chłopcy, przedszkole; dla dorosłych np. nastolatki i dorośli, seniorzy), 1–2 na okazje i zastosowania (prezent, święto, podróż, relaks), reszta na inne słowa tematu. Każda fraza dodaje co najmniej jedno słowo spoza tytułu i podtytułu; bez wariantów różniących się pisownią, interpunkcją, wielkością liter, kolejnością słów lub liczbą mnogą; bez znaków towarowych, ocen („best”), słów czasowych („new”) i nazw programów Amazona.
- Kontrola w kodzie, bez dodatkowego wywołania: tytuł z podtytułem dłuższe niż 200 znaków (limit KDP) to ponowienie wywołania jak przy błędnych metadanych, a po wyczerpaniu prób kod 4. Tak samo części opisu, które ze znacznikami i miejscem na fakty przekroczyłyby 4000 znaków. Niedozwolony HTML w częściach opisu daje jedno ponowienie, a potem program usuwa znaczniki (tekst zostaje) z ostrzeżeniem. Ostrzeżenia (metadane zostają bez zmian, poprawia je użytkownik w `ideas.json` albo w KDP): podtytuł bez frazy odbiorców rynku, tytuł albo podtytuł dłuższy niż cel dla okładki, słowo kluczowe złożone tylko ze słów tytułu i podtytułu, wariant innego słowa kluczowego, treści opisu niezgodne z zasadami KDP (emoji, adres, cena, słowa sprzedażowe, prośba o recenzję; wykrywanie przybliżone).
- **Opis do KDP** (zmiana z 20.11.2026). Opis zawsze ma te same części, a strukturę i fakty dokłada program, nie model:
  1. pogrubiony tytuł książki (`<b>`);
  2. hasło (`<h4>`): jedno zdanie, które przyciąga uwagę i mówi, czym książka się wyróżnia (model, do 120 znaków);
  3. akapit o zawartości: motywy, postacie, zajęcia (model, 2–3 zdania, do 500 znaków);
  4. lista faktów (`<ul>`) z manifestu: liczba kolorowanek i druk jednostronny („flamaster nie przebije na następny obrazek”) albo dwustronny, format strony, strona tytułowa do kolorowania albo „This book belongs to” i strona z poradami (FR-23), jeśli książka je ma;
  5. nagłówek (`<h5>`, „Why kids and parents love it” albo dla dorosłych „Why you'll love it”) i 3–5 korzyści (model, każda do 100 znaków): co dziecko lubi albo ćwiczy i dlaczego to lubi rodzic (spokojny czas bez ekranu, prezent), dla dorosłych relaks i kreatywność;
  6. zdanie na koniec z powodem do zakupu, np. pomysł na prezent (model, do 150 znaków).

  Model zwraca te części jako osobne pola (`headline`, `about`, `benefits`, `closing` w `ideas.json`) i może w nich używać tylko `<b>`, `<i>`, `<u>`, oszczędnie i bez atrybutów. Pozostałe znaczniki KDP (`<p>`, `<br>`, `<ul>`, `<ol>`, `<li>`, `<h4>`–`<h6>`) wstawia program; `<h1>`–`<h3>` KDP nie obsługuje. Zdania faktów i nagłówki są w `texts` → `listing` w `config/markets.yaml` (pl, en, de; pisownia rynku jak w FR-19), z wstawkami `{pages}`, `{trim_in}` i `{trim_cm}`. Rynek bez tych tekstów dostaje opis bez listy faktów i bez nagłówka korzyści, z ostrzeżeniem.
  Zasady KDP dla opisu (prompt i ostrzeżenia w kodzie): bez emoji, adresów stron i e-maili, cen, słów „free” czy „sale”, próśb o recenzje, „buy now” ani haseł typu „bestseller”, bez list słów kluczowych i bez wzmianki o AI. Odsyłanie do innych książek autora należy do A+ Content (sekcja 14a), nie do opisu.
- `description` w `ideas.json` zostaje zwykłym tekstem (hasło i akapit bez znaczników), np. dla tyłu okładki (FR-15). Stare pliki bez części opisu dostają w HTML swój `description` jako akapit.
- Opis składa program w kroku 1 i jeszcze raz w `finalize` (fakty mogą się zmienić, np. tryb druku, FR-22) do `description.html` w katalogu książki, gotowego do wklejenia w KDP, a manifest zapisuje `description` (`chars`, `sha256`, `language`). KDP liczy do limitu 4000 znaków także znaczniki, więc program mierzy złożony HTML: powyżej 4000 ostrzeżenie, powyżej 2000 ostrzeżenie, że kupujący czyta zwykle początek (cel 1000–1500).

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
- Każdy prompt zawiera stałe ograniczenia: `black and white line art, coloring book page, single illustration, one scene, pure white background, closed outlines, no shading, no grayscale, no text, no grid, no multiple panels, no collage, no frame`. Po FR-21 lista kończy się `no logos, no brand marks`.
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
- Kryteria odrzucenia: kilka paneli, siatka lub kolaż; cieniowanie lub szarości; tekst lub litery; otwarte kontury uniemożliwiające kolorowanie; poziom szczegółowości niezgodny z profilem wieku; elementy niezgodne z opisem sceny; **temat książki niewidoczny w samym rysunku** (`theme_unclear`, zmiana z 17.11.2026); po FR-21 także **podobieństwo do znanej postaci, maskotki, zabawki lub logo** (`protected_character`).
- `theme_unclear`: z czarno-białego rysunku, bez kolorów, dziecko ma się domyślić tematu kolorowanki. Na okładce zimowej książki z kucykami strona „snowy shore, winter waves, ice” bez kolorów wyglądała jak letnia plaża, i tak ją pokolorował model. Model z wizją dostaje temat po angielsku: tytuł z metadanych i słowa kluczowe tematu (`theme_anchors`, FR-03b). Wystarczy jedna wyraźnie narysowana wskazówka (płatki śniegu, sople, śnieg na ziemi, szaliki w zimowej książce); kryterium nie dotyczy strony FR-14, gdzie temat sprawdza `scene_mismatch`.
- Odrzucona strona jest generowana ponownie **z tego samego pomysłu**, bez rozróżniania powodu (wada rysunku albo niewidoczny temat): model obrazu za każdym razem rysuje inaczej. Maks. `qa_max_retries` (domyślnie 2) ponowień na pomysł. Gdy żadna próba nie przejdzie, pozycja bierze **zapasowy pomysł** i znów ma `qa_max_retries` ponowień; łącznie najwyżej `qa_max_ideas` (domyślnie 2) pomysłów na pozycję, potem strona dostaje status `failed` w manifeście. Najgorszy przypadek to `qa_max_ideas × (1 + qa_max_retries)` grafik na stronę (domyślnie 6, ok. 0,27 USD przy `medium`). Do 17.11 każde odrzucenie od razu brało zapasowy pomysł.
- Program kończy się sukcesem, jeśli jest co najmniej `--pages` stron ze statusem `ok`. W przeciwnym razie zwraca kod wyjścia 2 (sekcja 9.3).
- Zapasowe pomysły to wspólna pula dla całej książki, wydawana po kolei stronom odrzuconym przez QA. Gdy pula się skończy, odrzucona strona dostaje status `failed`.
- Odrzucona strona trafia do `rejected/page_XX_tryN.png`, a manifest zapisuje dla niej numer próby, id pomysłu, plik i powody (`rejected`). Wpis strony pokazuje pomysł i prompt ostatniej próby.
- Błąd samej oceny (np. odmowa modelu) oznacza stronę jako `failed`; błąd krytyczny dostawcy (klucz, brak środków) przerywa przebieg jak w FR-05.

### ✅ FR-08: Struktura wyjścia i manifest
- Katalog wyjściowy: `<output-dir>/<slug-tematu>_<age>_<style>_<format>/` (np. `output/dinozaury_przedszkole_kawaii_square/`), z przyrostkiem `_<rynek>` dla rynku innego niż US (FR-19, np. `…_square_uk`).
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
- `--max-cost <USD>` (domyślnie 5.00): limit kosztu **całej książki**. Po przekroczeniu program kończy bieżące zadania, nie startuje nowych i zapisuje manifest (status `budget_exceeded`).
- Na końcu program wypisuje podsumowanie: liczbę stron ok/failed, łączny koszt i czas.

**Szczegóły**
- **Cennik:** `api_pricing` w `settings.yaml`, przepisany ze strony dostawcy, z adresem źródła i datą sprawdzenia (`source`, `checked`). Dla każdego modelu podaje cenę w USD za milion tokenów wejścia i wyjścia. Koszt wywołania liczy się z tokenów, które zwraca API. Tokeny z pamięci podręcznej program liczy po pełnej cenie, więc koszt jest raczej zawyżony.
- **Model bez ceny** w cenniku to błąd konfiguracji (kod 1) przed pierwszym wywołaniem API, bo bez ceny program nie pilnowałby limitu.
- **Zakres limitu** (zmiana z 17.11.2026): limit dotyczy całej książki, razem z poprawkami w kolejnych uruchomieniach. Polecenia na istniejącej książce (`images`, `belongs-to`, `cover`, `ideas --redo`) zaczynają liczenie od łącznego kosztu z manifestu (`cost_usd`), a nie od zera; `generate` i `ideas` dla nowej książki zaczynają od zera. Książka, która już wydała limit, nie startuje kolejnego polecenia (kod 3, przed pierwszym wywołaniem API, z prośbą o wyższy limit). Wcześniej limit dotyczył jednego uruchomienia, więc poprawki go omijały. Łączny koszt książki służy też do policzenia, ile egzemplarzy go zwróci (FR-16). Domyślna wartość to `max_cost_usd` w `settings.yaml`, a `--max-cost` ją nadpisuje.
- **Sprawdzanie limitu:** program sprawdza limit przed każdą nową stroną i przed każdą grafiką z zapasowego pomysłu po odrzuceniu przez QA. Koszt strony dolicza się zaraz po jej zakończeniu, zanim wątek weźmie następną. Strony w innych wątkach mogą jeszcze trwać, więc limit może zostać przekroczony najwyżej o grafiki w toku.
- **Po przekroczeniu w `images`:** strona, której QA odrzuciło grafikę, nie dostaje zapasowego pomysłu i jest oznaczona jako nieudana. Manifest dostaje status `budget_exceeded` z opisem w `error`, a program kończy się kodem 3. Kolejne `kdp-studio images` z wyższym limitem dokańcza brakujące strony.
- **Po przekroczeniu w `generate`:** krok 3 (`finalize`) czeka, aż kroki 1 i 2 zostaną dokończone. Jeśli limit zużyją już pomysły, grafiki nie startują.
- **Manifest:** strona ma `cost_usd` z grafik i QA, sumowany przez wszystkie uruchomienia (ponowne wygenerowanie dolicza się do poprzedniego kosztu). `ideas.cost_usd` obejmuje pomysły, weryfikację i `--redo`. Pole `cost_usd` w katalogu głównym manifestu to łączny koszt książki.
- **Konsola:** limit książki z tym, co już wydała (`Limit kosztu książki: $5.00 (wydano dotąd $1.42).`), koszt pomysłów, koszt każdej strony, koszt każdego kroku (`Czas kroku (grafiki): 6 min 12 s, koszt $2.27.`); komunikat o przekroczeniu podaje koszt książki i tego uruchomienia. `generate` kończy się podsumowaniem: liczba gotowych i nieudanych stron, koszt według rodzaju (pomysły, grafiki, QA) z limitem oraz czasy kroków.
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

**Polecenie i krok w `generate`** (zmiana z 17.11.2026, zrobiona)
- Stronę tworzy osobne polecenie `kdp-studio belongs-to <katalog-książki>`. Jego uruchomienie jest decyzją, więc nie potrzebuje żadnej flagi. Dzięki temu stronę można dodać do książki, która jest już gotowa, bez generowania czegokolwiek od nowa.
- Polecenie robi całą stronę: ramkę z modelu, obróbkę jak w FR-06, kontrolę pustego pola, wpisanie tekstu i kontrolę druku (NFR-07).
- Wymaga kroku 2 (FR-17): gotowych surowych stron książki, bo układ zapasowy używa grafiki pierwszej gotowej strony. Bez nich kończy się błędem walidacji (kod 1). W `generate` bez żadnej gotowej strony krok jest pominięty z ostrzeżeniem.
- `generate --belongs-to-page` uruchamia to polecenie jako dodatkowy krok: `ideas` → `images` → `belongs-to` → `finalize`. Krok `finalize` pisze wtedy `canva.md` już z tą stroną. Wartość domyślna flagi pochodzi z `settings.yaml` (`belongs_to_page.enabled`, domyślnie `false`). Flaga występuje tylko w `generate`.
- Samodzielne `belongs-to` na książce po kroku 3 odświeża `canva.md`, który powstaje z manifestu i nie wymaga wywołań API.
- Opcje: `--qa`, `--image-quality`, `--max-cost` (jak w `images`) oraz `--remove`, które usuwa stronę z książki: kasuje `front_belongs_to.png` z katalogu głównego i wpis z manifestu, a surową grafikę zostawia.
- Bez tej strony nic się nie zmienia: użytkownik robi ją ręcznie w Canvie, jak w MVP.
- Strona jest już wliczona w `front_matter_pages` (domyślnie 2: strona tytułowa i ta strona), więc `pages_in_book` i marginesy (FR-02, FR-06) się nie zmieniają. Od FR-23 jest to jeden z dwóch wariantów strony 1, a liczbę stron wstępnych liczy FR-23.

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
- Program wpisuje napis `belongs_to_page.text` (domyślnie „This book belongs to:”; po FR-19 z `terms` rynku książki).
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
- Nieudana strona (status `failed`) daje kod wyjścia 2, jak brakująca strona kolorowanki. Kolejne `kdp-studio belongs-to` próbuje ponownie.

Konfiguracja (szkic):

```yaml
# settings.yaml
belongs_to_page:
  enabled: false                 # domyślna wartość generate --belongs-to-page
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
- **Czcionka:** Fredoka (SIL OFL 1.1) w `assets/fonts/Fredoka-Variable.ttf` z licencją `assets/fonts/OFL.txt`, wariant `SemiBold` (`belongs_to_page.font_variation`). Litery konturowe rysuje program: biały środek i czarny obrys. Czcionka nie potrzebuje więc osobnej wersji konturowej. Domyślnie konturowe są dla `przedszkole` i `wczesnoszkolne`. Na rynkach innych niż US i UK napis używa Baloo 2 (`assets/fonts/Baloo2-Variable.ttf`, licencja `OFL-Baloo2.txt`), bo Fredoka nie ma polskich liter (FR-19).
- **Napis:** po angielsku, „This book belongs to:”. Inny język to zmiana `belongs_to_page.text` w `settings.yaml`. Za szeroki napis program zmniejsza, najwyżej do 40% rozmiaru z profilu wieku. Jeśli i tak się nie mieści, strona dostaje błąd obróbki.
- **Elementy motywu w prompcie:** najczęstsza główna postać (`subject`) i najczęstsze przedmioty (`elements`) stron książki, liczone przez program, deterministycznie. Motyw to tytuł książki (`book.title`, w języku metadanych), bo prompt jest po angielsku.
- **Pole na tekst:** domyślnie `x: 0.2, y: 0.37, width: 0.6, height: 0.3`. Jest nieco mniejsze niż w szkicu, żeby łatwiej mieściło się w tabliczce z modelu.
- **Układ zapasowy:** grafika **pierwszej gotowej strony książki** (jej surowy plik, już po QA) w górnych 55% obszaru treści, a napis pod nią. Grafika „z motywem bez ramki” byłaby kolejnym wywołaniem API, a nieudana ramka mogła zawierać napis modelu. Strona książki jest tania, czysta i w tym samym stylu. Kosztem jest powtórzenie jednej ilustracji w książce. Bez żadnej gotowej strony (wszystkie nieudane) strona FR-14 też jest nieudana.
- **Kolejność:** strona FR-14 powstaje po stronach książki, bo układ zapasowy potrzebuje ich grafik. Do 17.11 robił to krok 2 (`images`); teraz robi to polecenie `belongs-to`. Gdy limit budżetu jest już przekroczony, strona nie startuje (kod 3). Gdy limit zostanie przekroczony w trakcie prób, program przechodzi na układ zapasowy, który nic nie kosztuje.
- **Przełącznik:** `--belongs-to-page/--no-belongs-to-page` jest tylko w `generate` (w #30 był też w `ideas` i `images`). Wpis w manifeście tworzy polecenie `belongs-to`, a usuwa `belongs-to --remove`. `images` nie rusza strony FR-14, ale ostrzega, gdy wygenerował ponownie stronę, której grafika jest w układzie zapasowym. `finalize` jej nie obrabia, tylko przypomina o `belongs-to`, gdy strony brakuje albo nie odpowiada obecnym ustawieniom.
- **Nowa ramka z modelu** (w `belongs-to`) przy `action: regenerate` we wpisie `front_matter.belongs_to`, przy braku surowej grafiki, po nieudanej próbie i po zmianie promptu ramki (np. po zmianie pomysłów albo `composition`). Nieudany napis przy aktualnej surowej grafice (np. za długi tekst) nie daje nowej ramki, bo ta by go nie naprawiła: strona zostaje `failed`, dopóki nie zmienią się ustawienia napisu.
- **Ponowna obróbka bez modelu** (w `belongs-to`, bez wywołań API), gdy zmieni się surowa grafika, parametry obróbki, napis, pole, czcionka (suma pliku) albo profil wieku. Dzięki temu zmiana napisu lub czcionki nie kosztuje nowej grafiki.
- **`reference_image`:** adapter OpenAI go nie obsługuje, więc strona nie używa referencji stylu. Wspólny blok stylu wystarcza do spójności.

### ✅ FR-15: Okładka (poza MVP)

Komenda `kdp-studio cover <katalog-książki>` tworzy gotową do KDP okładkę paperback: jeden jednostronicowy PDF z tyłem, grzbietem i przodem. Uruchamia się ją po `generate`, bo wymiary zależą od ostatecznej liczby stron, a przód od gotowych grafik. Okładkę można wygenerować ponownie bez ruszania wnętrza.

**`generate --cover`** (zmiana z 17.11.2026, zrobiona)
- `generate --cover` uruchamia `cover` jako ostatni krok, po `finalize`: `ideas` → `images` → (`belongs-to`) → `finalize` → `cover`. Jedno polecenie daje wtedy cały pakiet do KDP: strony do Canvy i gotowy PDF okładki.
- Działa jak `cover` **bez wskazania stron**: stronę na przód i miniatury tyłu proponuje model z wizją (patrz „Wybór grafik”). Kolor, wybór stron, QA, opis na tyle i jakość grafik okładki pochodzą z `settings.yaml` (`cover.colorize`, `cover.select_pages`, `cover.qa`, `cover.back_text`, `image_quality`); `--image-quality` z `generate` dotyczy tylko stron. Kontroli szablonu KDP nie ma, bo szablon zależy od liczby stron: `--template` zostaje w `cover`.
- Okładka startuje tylko wtedy, gdy wszystkie strony książki są `ok`. W przeciwnym razie `generate` pomija ją z komunikatem i kończy się kodem 2 jak dotąd; okładkę robi się potem samodzielnym `cover`.
- `generate` tworzy wszystkich dostawców, także model z wizją do wyboru stron, przed pierwszym wywołaniem API. Koszt okładki liczy się do tego samego `--max-cost` co reszta uruchomienia (FR-10).
- Wartość domyślna flagi: `cover.in_generate` w `settings.yaml` (domyślnie `false`); `--no-cover` ją wyłącza.
- Przed pierwszym wywołaniem API `generate --cover` sprawdza też czcionkę tytułu, profil CMYK i liczbę stron: okładka potrzebuje co najmniej `cover.thumbnails + 1` stron (przód i miniatury), inaczej kod 1.
- Okładka powstaje pod tą samą blokadą książki co pozostałe kroki. `cover.cost_usd` to tylko jej część wydatków uruchomienia, a `cost_usd` książki obejmuje wszystko. Kod wyjścia to najgorszy z kroków (np. 3, gdy limit skończy się na okładce); podsumowanie `generate` (strony, koszt, czas z krokiem „okładka”) wypisuje się także po błędzie okładki.


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
- **Dorysowanie do przodu** (zmiana z 17.11.2026, domyślne, `cover.outpaint`): tył nie powstaje jako nowy, podobny obraz, tylko jako ciąg dalszy przodu. Program składa płótno w proporcjach obsługiwanych przez model: po prawej lewy pas gotowego przodu (bez tytułu), po lewej puste miejsce na tył z grzbietem. Model dostaje je razem z maską, która jest przezroczysta tylko na pustym miejscu, i promptem `cover.outpaint_prompt` („przedłuż obraz w lewo”, z tymi samymi regułami kompozycji). Listwa, deski czy śnieg ciągną się wtedy dalej zamiast powstawać od nowa: na próbach z 17.11 nowy, podobny obraz miał cieńszą listwę i inny układ desek. Program wybiera proporcje z najwęższym pasem przodu, który ma co najmniej `outpaint_overlap_min` (0.2) jego szerokości (kwadrat: 4:3, ok. 1/3 przodu). Maska jest „miękka”: model przerysowuje też znany pas przodu, lekko przesunięty i przeskalowany (pierwsza próba 17.11: listwa ciągła, ΔE 3,5, ale pas przesunięty o ~30 px i pomniejszony o 3%, więc deski rozjeżdżały się na styku). Program nakłada więc pas z modelu na prawdziwy przód przekształceniem afinicznym (`cv2.findTransformECC`, na obrazie zmniejszonym 4×; zgodność co najmniej 0.5, skala ±15%, przesunięcie do 10% wysokości) i to samo przekształcenie stosuje do całego płótna. Dopiero potem bierze z niego część tył + grzbiet; przód na okładce zostaje programowy. Zarejestrowany tył nie przechodzi już dopasowania DTW (nieliniowe odkształcenie tylko by go popsuło) ani warunku horyzontu w kontroli styku, bo wiersz największej zmiany koloru potrafi wskazać po obu stronach różne krawędzie tej samej listwy (druga próba z 17.11 odpadła tak przy ΔE 5,5 i zgodności 0,97); decyduje wtedy sam ΔE. DTW i warunek horyzontu działają, gdy rejestracja się nie uda. Manifest zapisuje zgodność w `seams[].register_cc`. Opis przodu modelem z wizją nie jest wtedy potrzebny. Gdy żadne proporcje nie pasują albo `outpaint: false`, tył powstaje jak niżej, z przodem jako referencją.
- Spójność z przodem bez dorysowania:
  - przód jest obrazem referencyjnym;
  - program analizuje gotowy przód modelem z wizją: zwraca wysokość **linii horyzontu** jako ułamek wysokości (albo jej brak, np. przy tle-wzorze) i kolory tła w pasach poziomych przy lewej krawędzi przodu. Program uzupełnia to próbkami pikseli z lewej krawędzi;
  - prompt narzuca horyzont na tej samej wysokości, te kolory tła i styl przodu.
- Reguły kompozycji w prompcie:
  - kluczowe elementy co najmniej `key_margin_in` od krawędzi;
  - prawy pas szerokości grzbietu plus zapas to wyłącznie tło;
  - dolny róg przy grzbiecie (pole kodu kreskowego) to spokojne tło;
  - bez tekstu.
- **Dopasowanie tyłu do przodu:** model nie trzyma się podanej wysokości horyzontu (na próbach z 17.11 listwa podłogi wyszła o 14% wyżej i była cieńsza niż na przodzie, a linia śniegu przesunęła się o 0,7%). Dlatego przed kontrolą styku program dopasowuje tył w pionie do przodu: pionowy profil kolorów pasa przy grzbiecie wyrównuje do profilu lewej krawędzi przodu (DTW z nachyleniem 1/2–2 i karą za odkształcenie, przesunięcie najwyżej `seam_align_max` wysokości). Tę samą, wygładzoną mapę wierszy stosuje do całej szerokości tyłu, więc listwa czy linia śniegu zostają proste. Tył przesuwa się tylko w pionie; obiekty na nim mogą się nieco rozciągnąć albo ścisnąć.
- **Kontrola styku z przodem:** program porównuje kolory w pasach poziomych po obu stronach zgięcia grzbiet/przód (ΔE w przestrzeni Lab) i położenie horyzontu. Przekroczenie progu (`seam_max_delta_e`, `horizon_tolerance`) to ponowienie, maks. `max_retries`.
- **Wygładzenie styku:** w pasie `seam_band_in` po stronie grzbietu program płynnie przechodzi z tła tyłu w kolory lewej krawędzi przodu. Przód zostaje nienaruszony, a przesunięcie przy oprawie nie odsłania szwu.
- **⬜ Pas na grzbiecie (opcja, planowane, #67):** gdy po `max_retries` żadna próba nie przejdzie kontroli styku, a opcja jest włączona, program zamiast wygładzenia rysuje jednolity pas na całym grzbiecie. Przy dużej różnicy kolorów wygładzenie nie ukrywa szwu, a pas wygląda na celowy element projektu.
  - **Geometria:** pas zachodzi równo na tył i przód, `overlap_in` (domyślnie 0.125") za każdą linią zgięcia, więc ma szerokość grzbiet + 2 × `overlap_in`. Rozrzut zgięcia w drukarni wypada na pasie: nie odsłania szwu i nie zostawia paska tła na grzbiecie ani koloru na tyle. Na przodzie pas kończy się na granicy strefy bezpiecznej tekstu (`safe_in`), więc zasłania tylko wąski pas ilustracji, nie tytuł; na tyle nie dotyka pola kodu kreskowego (0.25" od grzbietu). Tekst grzbietu leży na pasie, a kontrola czytelności liczy kontrast z jego kolorem.
  - **Kolor (w kodzie, bez modelu):** kolor różny od tła, ale już obecny na okładce.
    1. Paleta z pokolorowanego przodu, kolory grupowane w Lab. Kandydat musi zajmować co najmniej `min_share` okładki.
    2. ΔE do barw przy krawędziach pasa (prawa krawędź tyłu, lewa krawędź przodu) co najmniej `min_delta_e`.
    3. Wśród pozostałych wygrywa odcień najbliższy `hue` (domyślnie czerwony, np. czerwień już obecna na świątecznej okładce) przy wystarczającym nasyceniu, a bez takiego koloru najbardziej nasycony kandydat.
    4. Kolor nie może mocno zmieniać się po przeliczeniu na CMYK (kontrola gamutu).
    5. `color_rgb` w konfiguracji nadpisuje wybór. Bez żadnego kandydata pas nie powstaje: zostaje wygładzenie i ostrzeżenie.
  - **Włączanie:** domyślnie wyłączone, domyślnym wyjściem awaryjnym zostaje wygładzenie. Włącza ustawienie `cover.spine_band.enabled` albo flaga `--spine-band/--no-spine-band` w `cover` i `generate --cover` (flaga nadpisuje ustawienie; w pliku książki FR-20 klucz w sekcji `cover`).
  - **Manifest:** `cover.spine_band` z kolorem (`rgb`), udziałem na okładce, ΔE, szerokością, zakładką i źródłem koloru (`palette` albo `config`). Ostrzeżenie: „styk niezgodny po N próbach: grzbiet zakryty pasem w kolorze …”.
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
- **Profil docelowy** z konfiguracji (`cover.cmyk.profile`). KDP żadnego nie wskazuje, więc to nasz wybór; poradniki zewnętrzne najczęściej podają U.S. Web Coated (SWOP) v2, a jako alternatywę GRACoL 2006 Coated. Profil służy tylko do konwersji i podglądu, nie trafia do PDF. Domyślny jest SWOP 2013 (`assets/icc/SWOP2013C3_CRPC5.icc`, CRPC5, TAC 300%) z rejestru ICC, dołączony do repozytorium, bo jego licencja (IDEAlliance) pozwala go udostępniać bez zmian; test pilnuje, że plik jest niezmieniony (Profile ID z rejestru). Profilu, którego licencja nie pozwala na redystrybucję (np. Adobe U.S. Web Coated (SWOP) v2), nie ma w repozytorium: `.gitignore` pomija wszystkie `*.icc` poza domyślnym, a ścieżkę do własnego profilu podaje zmienna `KDP_STUDIO_CMYK_PROFILE` w `.env`, która ma pierwszeństwo przed `cover.cmyk.profile` (zmiana z 18.11.2026). Brak pliku przy włączonym CMYK to błąd walidacji z instrukcją, skąd go wziąć (kod 1).
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
- **Adapter OpenAI:** zapytanie z `reference_image` idzie do `images.edit` z `input_fidelity: high`, a z `mask` (dorysowanie tyłu) także z maską. Model, który któregoś z tych parametrów nie obsługuje (HTTP 400, np. `gpt-image-2.6-flare` i `input_fidelity`), dostaje od razu to samo zapytanie bez niego; adapter zapamiętuje to do końca uruchomienia. Bez maski model dostaje samo płótno z pustym białym miejscem, które prompt każe wypełnić. Odrzucone zapytanie nie zwraca zużycia tokenów, więc nie liczy się do `--max-cost`.
- **Kolorowanie** (`pipeline/cover_front.py`):
  - szkic przodu ze spadem (kontury i pusty pas na tytuł) idzie do modelu jako referencja, rozciągnięty do najbliższych proporcji dostawcy (kwadrat → 1:1, letter → 3:4);
  - wynik wraca rozciągnięty z powrotem do przodu;
  - prompt `cover.color_prompt` z blokiem stylu książki i sceną strony wybranej na przód z `ideas.json` (po angielsku), dopisaną przez program po wyborze stron. Same kontury nie mówią, czy to śnieg, czy piasek: bez sceny model pokolorował zimową stronę „snowy shore, winter waves, ice” (17.11) jak letnią plażę. Tytułu książki prompt nie zawiera: z linią `Book title: …` model wpisał tytuł w pas nad rysunkiem, mimo zakazu tekstu, i pomniejszył rysunek. Prompty tyłu dostają zamiast tytułu słowa kluczowe tematu (`theme_anchors`, np. „unicorns, ponies, winter”) z prośbą o tę samą porę roku i miejsce;
  - kontrola pasa tytułu: pas nad rysunkiem szkicu ma zostać spokojnym tłem. Program liczy w nim krawędzie (Canny) na obrazie modelu; powyżej `title_band_max_edges` (1% pikseli) to napis albo obiekt z modelu i ponowienie kolorowania (napis modelu dawał 7%, gładkie niebo 0,2%). Po `max_retries` program bierze najczystszą próbę i ostrzega. Manifest: `cover.front.title_band_edges`;
  - ponowienia przy błędach niekrytycznych (`max_retries`).
- **Kontury:** program mierzy, jaka część konturów szkicu ma w pobliżu ciemny piksel modelu (`contour_search_in`, 0,02"). Model przerysowuje cały szkic, lekko przesunięty i przeskalowany (próba z 17.11: ~4% wysokości i 2%, zgodność tylko 46%). Dlatego program najpierw dopasowuje obraz modelu do szkicu przekształceniem afinicznym (`pipeline/registration.py`, OpenCV ECC na rozmytych maskach konturów, te same granice co przy tyle) i zostawia dopasowanie tylko wtedy, gdy podnosi zgodność (na tej próbie do 99,7%). Dopasowanie idzie w dwóch krokach, dla przodu i tyłu: najpierw samo przesunięcie na mocno rozmytym obrazie (1% szerokości), potem pełne przekształcenie afiniczne. Trzecia próba z 17.11 przesunęła przód o ~6% wysokości i powiększyła o 3,5%; ECC startujące od tożsamości utknęło wtedy przy zgodności 0,44 (kontury odrzucone, 43%), a dwa kroki dają 99%. Manifest zapisuje zgodność dopasowania w `cover.front.register_cc`. Przy zgodności ≥ `contour_match_min` (85%) nakłada ostre kontury K100. Przy przesunięciu, którego dopasowanie nie naprawia, używa samego obrazu modelu i ostrzega.
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
  - dopasowanie w pionie (`align_to_front()`): profile Lab 256 wierszy po obu stronach zgięcia, DTW w pasie `seam_align_max` (domyślnie 0.2, 0 wyłącza), mapa wierszy wygładzona w oknie 3% wysokości i zastosowana do całego tyłu (`cv2.remap`); przesunięcie poniżej piksela zostawia tył bez zmian, a największe przesunięcie trafia do manifestu (`seams[].align_shift`);
  - kontrola styku (po dopasowaniu): mediany kolorów w `seam_bands` pasach (domyślnie 8) po obu stronach zgięcia grzbiet/przód, ΔE w Lab. Wiersze w odległości `horizon_tolerance` od wykrytego horyzontu są pominięte, bo przesunięcie w granicach tolerancji zamieniłoby w pasie niebo na ziemię; położenie horyzontu sprawdza osobny warunek (tylko gdy widać go po obu stronach);
  - po `max_retries` nieudanych kontrolach program bierze próbę z najmniejszym ΔE i ostrzega; wygładzenie styku i tak działa, a z włączonym pasem na grzbiecie (planowane, #67) pas zastępuje wygładzenie;
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
- **Profil CMYK** domyślnie to dołączony SWOP 2013 (`assets/icc/SWOP2013C3_CRPC5.icc`); `KDP_STUDIO_CMYK_PROFILE` w `.env` wskazuje inny. Gdy pliku nie ma, `cover` kończy się kodem 1 z instrukcją, skąd wziąć profil (na macOS do prób jest `Generic CMYK Profile.icc`).
- **Ostrzeżenie o tytule:** gdy kolor zmienia się (ΔE > `gamut_warn_delta_e`) na ponad 1% jego powierzchni.
- **`front.png`:** przód po przycięciu (bez spadu).

**Wymagania wobec dostawców**
- Adapter obrazu musi obsługiwać `reference_image` (OpenAI: endpoint edycji obrazu). Kontrakt już to przewiduje (§8.2).
- Maska (dorysowanie tyłu na podstawie przodu) jest od 17.11.2026 domyślnym sposobem malowania tyłu (`ImageRequest.mask`), bo sam prompt i referencja nie dawały ciągłej listwy ani desek.

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
  seam_align_max: 0.2           # największe przesunięcie wierszy tyłu przy dopasowaniu do przodu
  outpaint: true                # tył jako dorysowanie przodu (płótno z pasem przodu + maska)
  outpaint_overlap_min: 0.2     # najwęższy pas przodu na płótnie (część jego szerokości)
  outpaint_prompt: >-           # pola {area_pct}, {spine_pct}, {margin_pct}
    Extend this picture to the left. …
  max_retries: 2
  back_text: false
  title_font: assets/fonts/<czcionka-tytułowa-OFL>.ttf
  spine_band:                   # planowane (#67): pas na grzbiecie po nieudanych kontrolach styku
    enabled: false              # --spine-band/--no-spine-band
    overlap_in: 0.125           # zakładka na tył i na przód, równa po obu stronach
    hue: red                    # preferowany odcień z palety przodu
    min_delta_e: 25             # różnica od barw przy krawędziach pasa
    min_share: 0.01             # kolor musi zajmować tyle okładki
    color_rgb: null             # ręczny kolor zamiast wyboru z palety
  cmyk:
    profile: assets/icc/SWOP2013C3_CRPC5.icc   # dołączony; własny: KDP_STUDIO_CMYK_PROFILE w .env
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

### ✅ FR-16: Koszt druku, cena minimalna i tantiemy (poza MVP)

Program liczy koszt druku, cenę minimalną i tantiemy z tabel KDP i podpowiada cenę. Pomaga to już przy wyborze liczby grafik, przed generowaniem.

**Dane: tabele KDP w konfiguracji**
- Dane rynków są w `config/markets.yaml` (FR-19), który przepisuje dwie strony pomocy KDP. Każdy rynek ma źródło i datę sprawdzenia (`checked`):
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
- **Zwrot kosztu generowania:** liczba egzemplarzy, po której tantiemy pokryją koszt książki: `ceil(cost_usd / royalty)`, gdzie `cost_usd` to łączny koszt z manifestu, ze wszystkimi poprawkami (FR-10).
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
  - Opcje: `--market US,UK,DE,PL` (domyślnie rynek książki z manifestu, FR-19, a przed generowaniem `default_market`) i `--price 9.99` (konkretna cena do sprawdzenia, w walucie rynku).
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

**Implementacja (23.11.2026)**
- **Obliczenia:** `pipeline/pricing.py`, bez wywołań API, na `Decimal` z `ROUND_HALF_UP`. Wszystkie przypadki z kalkulatora KDP powyżej i tabela przykładu są testami (`tests/test_pricing.py`). Waluta bez groszy (JPY) zaokrągla się do pełnej jednostki.
- **Dane:** `config/markets.yaml` (FR-19) dostał `stale_after_days` (domyślnie 180) oraz dla rynku albo grupy cenowej `candidate_prices` (ceny netto do tabeli tantiem w walucie rynku) i `vat: true` (UK, strefa EU, PL, SE). AU, CA, JP i US nie mają tej uwagi.
- **`kdp-studio price`:** dla gotowej książki liczba grafik, strony wstępne i tryb druku są z manifestu, więc `--format`, `--pages`, `--single-sided/--double-sided` i `--instructions` to wtedy błąd (kod 1). Przed generowaniem domyślnie `DEFAULT_FORMAT` i 30 grafik, strony wstępne i tryb druku z `settings.yaml` albo z tych flag, a liczba stron przechodzi kontrolę FR-02. `--market` przyjmuje listę po przecinku. `--price` w walucie każdego wybranego rynku. Tabela tantiem zawiera cenę minimalną, `candidate_prices`, ostatnią cenę przed progiem, cenę progową i `--price`, bez cen spoza przedziału od minimalnej do maksymalnej.
- **Cena progowa** w wyniku i w manifeście to najniższa dozwolona cena ze stawką 60%: próg rynku albo cena minimalna, gdy jest wyższa (np. 402 strony: $13.06).
- **Cena między progami:** w PLN (39 i 40) KDP nie podaje stawki dla cen między progami; program liczy je ostrożnie ze stawką 50%.
- **Zwrot kosztu generowania** liczy się tylko dla rynków w USD, bo koszt API jest w USD, a program nie przelicza walut. Podstawą jest tantiema przy `--price` albo przy cenie progowej.
- **Sekcja `pricing` w manifeście i linia z ceną** powstają po kroku 3 (`finalize`, więc też na końcu `generate`), dla rynku książki. Liczba stron jest wtedy pewna, także po zmianie trybu druku w `finalize`.

Konfiguracja (szkic, wartości z KDP sprawdzone 16.11.2026; po FR-19 te dane są częścią `config/markets.yaml`):

```yaml
# config/kdp_pricing.yaml → config/markets.yaml (FR-19)
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

### ✅ FR-19: Rynek docelowy Amazona (poza MVP)

Książka powstaje dla konkretnego rynku Amazona, a nie tylko dla języka. USA, Wielka Brytania i Australia mówią po angielsku, ale inaczej: „Coloring Book” i „Colouring Book”, „color” i „colour”, inne słowa w wyszukiwarce. Słowa kluczowe KDP działają tylko wtedy, gdy zgadzają się z tym, jak szukają klienci na danym rynku.

**Parametr**
- `--market US|UK|DE|FR|ES|IT|NL|PL|SE|JP|CA|AU` w `ideas` i `generate`. Domyślnie `default_market: US` z `settings.yaml`.
- Rynek trafia do manifestu (`input.market`); kolejne kroki (`images`, `finalize`, `belongs-to`, `cover`, `price`) czytają go stamtąd. Stara książka bez tego pola to `US`.
- Nieznany rynek to błąd walidacji z listą dostępnych (kod 1). `kdp-studio profiles market` wypisuje rynki z `config/markets.yaml`.

**Jedno źródło danych: `config/markets.yaml`**
- Dla każdego rynku: domena Amazona, `locale` (np. `en-US`, `en-GB`, `en-AU`, `de-DE`, `pl-PL`), nazwa odmiany języka do promptu (np. „British English”), waluta, oraz:
  - **dane cenowe FR-16:** koszt druku, progi tantiem i cena maksymalna. Zastępują osobny `config/kdp_pricing.yaml`. Rynki o wspólnych tabelach KDP (strefa euro: DE, FR, ES, IT, NL, IE, BE) wskazują wspólną grupę (`pricing_group: EU`), żeby nie powielać liczb;
  - **stałe teksty rysowane przez program** (`terms`): napis strony FR-14 („This book belongs to:”, „Ta książka należy do:”), nazwa gatunku do podtytułu okładki („Coloring Book”, „Colouring Book”, „Malbuch”, „Kolorowanka”) i wzór wieku („for Kids Ages {min}–{max}”). Teksty są w konfiguracji, a nie z modelu, bo program musi je wpisać bez literówek.
- Każdy wpis ma `source` i `checked` jak w FR-16. Przy dodawaniu rynku trzeba sprawdzić, czy KDP przyjmuje paperbacki w jego języku.

**Na co wpływa rynek**
- **Metadane (FR-03):** tytuł, podtytuł, opis i słowa kluczowe powstają w odmianie języka rynku, z jej pisownią i słowami, których używają tam kupujący. To zastępuje ustawienie `metadata_language`.
- **Weryfikacja pomysłów (FR-03a):** sprawdza też spójność języka i pisowni metadanych z rynkiem (np. brak „color” w książce na UK).
- **Prompty obrazów i opisy scen zostają po angielsku**, niezależnie od rynku, bo w tym języku modele działają najlepiej.
- **Strona FR-14:** napis z `terms` rynku, chyba że `belongs_to_page.text` jest ustawione ręcznie.
- **Okładka FR-15:** podtytuł i opis na tyle w języku rynku.
- **Ceny FR-16:** `price` domyślnie liczy dla rynku książki, w jego walucie. `--market` w `price` nadal pozwala porównać inne rynki.

**Czcionki**
- Program sprawdza, czy czcionki stron FR-14 i okładki mają wszystkie znaki potrzebne dla tekstów rynku i tytułu (np. polskie ą, ę; niemieckie ß; szwedzkie å). Brak znaku to błąd przed pierwszym wywołaniem API (kod 1), a nie dziura w druku.
- Rynek JP wymaga czcionki z japońskimi znakami. Dopóki jej nie ma w `assets/fonts/`, wybór JP przy teście znaków kończy się błędem z wyjaśnieniem.

**Jedna książka, jeden rynek**
- Tytuł w KDP ma jeden język i jeden zestaw metadanych, a do innych rynków trafia tylko z inną ceną. Ta sama kolorowanka w innej odmianie języka to w KDP osobna książka, więc u nas osobne uruchomienie `ideas` z innym `--market`.
- Możliwe rozszerzenie: nowa książka na innym rynku korzystająca z gotowych stron istniejącej (np. `ideas --from <katalog>`), bo grafiki nie zawierają tekstu. Na razie poza tym wymaganiem.

**Implementacja (18.11.2026)**
- **`config/markets.yaml`:** 12 rynków z listy parametru, grupa cenowa `EU` dla DE, FR, ES, IT i NL (KDP ma w niej też IE i BE), `large_trim`, `sources` i wspólne `checked`. Ceny CA, AU, SE i JP przepisane 18.11.2026 z tych samych stron pomocy KDP co w FR-16 (US, UK, EU i PL zgadzają się z FR-16). Na Amazon.com.au koszt stały obejmuje 24–108 stron.
- **Pola rynku:** `name`, `domain`, `locale`, `language`, ceny (`currency`, `printing_cost`, `royalty`) albo `pricing_group`, `terms` (`coloring_book`, `belongs_to`, `ages` z polami `{min}` i `{max}`, `adults`), `spelling` i `alphabet`. Zakres wieku do wzoru `ages` daje nowe pole profilu wieku `age_range` (`dorosli` go nie ma, więc dostaje `adults`). Złe pole we wzorze, nieznana grupa albo grupa razem z własnymi cenami to błąd konfiguracji.
- **Ceny FR-16** wczytuje `MarketsConfig.pricing(rynek)` (kwoty jako `Decimal`); samo polecenie `price` to dalej FR-16.
- **`--market`** w `ideas` i `generate`, domyślnie `default_market` z `settings.yaml` (zastępuje `metadata_language`; stary klucz w `settings.yaml` to błąd konfiguracji). `ideas <katalog> --redo` nie przyjmuje `--market`, bo rynek jest w manifeście. Katalog książki dostaje przyrostek `_<rynek>` dla rynku innego niż US (np. `…_square_uk`), żeby ta sama kolorowanka na drugi rynek nie trafiała do katalogu pierwszej; książki US mają nazwy jak dotąd.
- **Metadane:** prompt pomysłów podaje domenę, `locale` i odmianę języka, każe nazwać książkę słowem z `terms.coloring_book` i zapisać wiek jak w `terms.ages`. Pisownię odmiany sprawdza i poprawia kod, nie model: mapa `spelling` (np. na UK, CA i AU `color → colour`, `favorite → favourite`, na US odwrotnie) zamienia te słowa w tytule, podtytule, opisie i słowach kluczowych z zachowaniem wielkości liter i zgłasza ostrzeżenie z listą zmian. To kontrola z FR-03a, ale bez wywołania API i niezależnie od `--review-ideas`.
- **Strona FR-14:** `belongs_to_page.text: null` w `settings.yaml` oznacza napis z `terms.belongs_to` rynku książki; tekst wpisany tam ręcznie ma pierwszeństwo. Okładka nie ma osobnych tekstów rynku: tytuł, podtytuł i opis na tyle pochodzą z metadanych, które już są w języku rynku.
- **Czcionki:** program czyta mapę znaków czcionki (`fonttools`), bo Pillow rysuje brakujący znak jako pusty prostokąt bez ostrzeżenia. Wymagane znaki to teksty `terms` i `alphabet` rynku, a dla okładki także tytuł, podtytuł i (z `--back-text`) opis z `ideas.json`. `generate --belongs-to-page` i `generate --cover` sprawdzają czcionki na starcie (kod 1 przed pierwszym wywołaniem API); `belongs-to` i `cover` przed swoimi wywołaniami, `generate --cover` dodatkowo tytuł po kroku pomysłów. `ideas` i `generate` bez tych kroków tylko ostrzegają, bo strony do Canvy nie mają napisów.
- **Czcionka rynku:** Fredoka nie ma polskich liter ą, ć, ę, ń, ś, ź, ż (ma ł i ó), co wykazała ta kontrola. Rynek może więc mieć własną czcionkę napisów (`font` w `markets.yaml`), która zastępuje `belongs_to_page.font` i `cover.title_font`; warianty grubości (`SemiBold`, `Bold`) zostają z `settings.yaml`. Rynki inne niż US i UK używają Baloo 2 (SIL OFL, Google Fonts, `assets/fonts/Baloo2-Variable.ttf`, pobrana 18.11.2026), która ma wszystkie znaki tych rynków. Japońskich znaków nie ma żadna z dwóch czcionek, więc JP nadal kończy się czytelnym błędem przy stronie FR-14 i okładce. `AppConfig.for_market()` daje konfigurację z napisem i czcionkami rynku; używają jej `generate`, `belongs-to` i `cover`.

Konfiguracja (szkic):

```yaml
# config/markets.yaml
pricing_groups:
  EU:                              # DE, FR, ES, IT, NL, IE, BE – wspólne tabele KDP
    currency: EUR
    printing_cost:
      fixed_only_max_pages: 110
      regular: {fixed_only: 2.05, fixed: 0.75, per_page: 0.012}
      large:   {fixed_only: 2.48, fixed: 0.75, per_page: 0.016}
    royalty: {rate_50_max_price: 9.98, rate_60_min_price: 9.99, max_price: 250}
markets:
  US:
    domain: amazon.com
    locale: en-US
    language: American English
    currency: USD
    printing_cost:
      fixed_only_max_pages: 110
      regular: {fixed_only: 2.30, fixed: 1.00, per_page: 0.012}
      large:   {fixed_only: 2.84, fixed: 1.00, per_page: 0.017}
    royalty: {rate_50_max_price: 9.98, rate_60_min_price: 9.99, max_price: 250}
    terms:
      coloring_book: Coloring Book
      belongs_to: "This book belongs to:"
      ages: "for Kids Ages {min}–{max}"
  UK:
    domain: amazon.co.uk
    locale: en-GB
    language: British English
    currency: GBP
    # printing_cost, royalty: jak w FR-16
    terms:
      coloring_book: Colouring Book
      belongs_to: "This book belongs to:"
      ages: "for Kids Ages {min}–{max}"
  DE:
    domain: amazon.de
    locale: de-DE
    language: German
    pricing_group: EU
    terms:
      coloring_book: Malbuch
      belongs_to: "Dieses Buch gehört:"
      ages: "für Kinder von {min} bis {max} Jahren"
  PL:
    domain: amazon.pl
    locale: pl-PL
    language: Polish
    currency: PLN
    # printing_cost, royalty: jak w FR-16
    terms:
      coloring_book: Kolorowanka
      belongs_to: "Ta książka należy do:"
      ages: "dla dzieci w wieku {min}–{max} lat"
  # AU (en-AU), CA (en-CA), FR, ES, IT, NL, SE, JP – analogicznie
sources:
  printing_cost: https://kdp.amazon.com/en_US/help/topic/G201834340
  royalty: https://kdp.amazon.com/en_US/help/topic/G201834330
checked: 2026-11-16

# settings.yaml
default_market: US
```

### ✅ FR-20: Plik parametrów książki `--config-file` (poza MVP)

Cel: krótsze wywołanie i powtarzalne ustawienia. Zamiast kilkunastu flag użytkownik podaje jeden plik YAML z parametrami książki, a flagi w wierszu poleceń nadpisują pojedyncze wartości. Plik przydaje się też tam, gdzie flaga jest za ciasna: przy liście bohaterów i scen (sekcja 14a).

```bash
kdp-studio generate --config-file ksiazki/kotki.yaml
kdp-studio generate --config-file ksiazki/kotki.yaml --pages 40 --no-qa    # flagi wygrywają
kdp-studio generate --config-file output/swiateczne_kotki_wczesnoszkolne_cozy_square/manifest.json --theme "Kotki w ogrodzie"
```

Plik nie jest konfiguracją programu (`config/`, `KDP_STUDIO_CONFIG_DIR`, §7). Opisuje jedną książkę i jej uruchomienie, więc pomoc flagi mówi o „pliku parametrów książki”.

**Struktura pliku**
- Jeden schemat (`BookInput`, Pydantic, `extra="forbid"`) dla pliku i dla sekcji `input` w `manifest.json`. Klucze najwyższego poziomu to nazwy flag `generate` bez `--`, z podkreśleniem zamiast myślnika (`image_quality`, `max_cost`, `review_ideas`). Ustawienia stron wstępnych i okładki mają własne sekcje, bo te same nazwy (`qa`, `image_quality`, `max_cost`) znaczą tam co innego niż dla stron.
- `belongs_to.enabled` odpowiada `generate --belongs-to-page`, a `cover.enabled` odpowiada `generate --cover`. Skrót `cover: true` znaczy `cover: {enabled: true}`.
- Pozostałe klucze sekcji `cover` to flagi polecenia `cover` (`page`, `thumbnails`, `template`, `color`, `select_pages`, `back_text`, `qa`, `image_quality`, `max_cost`). `generate --cover` działa bez wskazanej strony (FR-15), więc `page` i `thumbnails` czyta tylko polecenie `cover`.
- Gdy pomysły z sekcji 14a staną się wymaganiami, dochodzą klucze `humanize`, `characters` i `scenes`. W pliku bohater ma osobne pola na wygląd (do promptu obrazu) oraz imię i charakter (tylko do generatora pomysłów), czego jeden napis we fladze `--character` nie oddaje.

```yaml
# ksiazki/kotki.yaml
theme: Świąteczne kotki
age: wczesnoszkolne
style: cozy
format: square
pages: 30
market: US                  # FR-19
review_ideas: true
qa: true
image_quality: medium
concurrency: 4
max_cost: 6.00
belongs_to:
  enabled: true
  qa: true
cover:
  enabled: true
  back_text: true
  qa: true
  max_cost: 1.00
# po przyjęciu pomysłów z sekcji 14a:
# humanize: true
# characters:
#   - name: Feliks
#     look: small ginger kitten with a striped scarf and a bell on the collar
#     personality: ciekawski, trochę niezdarny
#   - file: bohaterowie/mruczka.yaml
# scenes: sceny.yaml
```

**Pierwszeństwo**
- Flaga w wierszu poleceń > plik > profil (np. przyszłe `humanize` w `styles.yaml`) > `config/settings.yaml` > wartość domyślna w kodzie.
- Lista z flagi zastępuje całą listę z pliku, bez łączenia (np. powtarzana `--character` zastępuje `characters`).
- Brakujące wymagane parametry (`theme`, `age`, `style`) i błędne wartości wychodzą po scaleniu źródeł, jednym raportem jak w FR-01 (kod 1). Komunikat podaje źródło wartości: `kotki.yaml: pages: 300 poza zakresem 1–200` albo `--pages: …`.

**Odczyt i walidacja**
- YAML w UTF-8. Plik JSON też jest przyjmowany, bo YAML go obejmuje. Gdy plik ma sekcję `input` (jak `manifest.json`), program bierze tylko ją, więc `manifest.json` istniejącej książki służy za wzór nowej.
- Nieznany klucz, zły typ albo zła wartość wyliczeniowa kończą się kodem 1 przed pierwszym wywołaniem API, ze ścieżką klucza (`cover.thumbnails[1]`). Literówka nie może zostać po cichu pominięta.
- Ścieżki względne w pliku (`characters[].file`, `scenes`, `cover.template`, `output_dir`) liczą się od katalogu pliku, nie od katalogu roboczego. Ścieżki z flag liczą się jak dziś od katalogu roboczego.
- Plik nie przyjmuje sekretów: kluczy API, tokenów ani adresów z tokenem (§9.2, NFR-10). Schemat nie ma na nie pól.

**Polecenia**
- `ideas` i `generate`: plik opisuje nową książkę. `ideas` bierze klucze potrzebne w kroku 1 i nie zgłasza pozostałych, bo ten sam plik służy kolejnym krokom.
- `images`, `belongs-to` i `cover` przyjmują ten sam plik razem z katalogiem książki i biorą z niego ustawienia swojego kroku. Klucze opisujące książkę (`theme`, `age`, `style`, `format`, `pages`, `market`, `front_matter_pages`, a w przyszłości `humanize`, `characters`, `scenes`) muszą wtedy zgadzać się z `input` w manifeście. Różnica kończy się kodem 1 z listą różnic, bo plik opisuje inną książkę, a zmiana tych wartości wymaga nowej książki albo `ideas --redo`.
- `finalize` i `price` nie przyjmują pliku.

**Manifest**
- `input` w manifeście zapisuje skuteczne wartości wszystkich kluczy schematu po scaleniu, a nie tylko te, które podał użytkownik. Dzięki temu manifest jest kompletnym plikiem parametrów (NFR-08), a stare manifesty bez nowych pól wczytują się z wartościami domyślnymi.
- `input.config_file` zapisuje ścieżkę i `sha256` użytego pliku, a `input.overrides` nazwy kluczy nadpisanych flagami. Wartości sekretne nigdy tam nie trafiają, bo plik ich nie zawiera.

**Uwagi do implementacji**
- Opcje typer w `ideas`, `generate`, `images`, `belongs-to` i `cover` mają domyślnie `None`, żeby dało się odróżnić flagę niepodaną od podanej. Dziś `--format`, `--pages`, `--strict` i `--output-dir` mają domyślne wartości w sygnaturze `generate` i `ideas`; przenoszą się do kroku scalania.
- Scalanie w jednej funkcji (np. `resolve_input(cli, file, config)`), która zwraca `BookInput` i mapę źródeł każdej wartości, użytą w komunikatach błędów i w `input.overrides`.
- Testy: tabela pierwszeństwa (flaga, plik, settings), nieznany klucz, ścieżki względne od katalogu pliku, `manifest.json` jako plik wejściowy, niezgodność pliku z manifestem w `images`, brak sekretów w manifeście.

**Implementacja (18.11.2026)**
- **Schemat:** `BookInput` w `src/kdp_studio/book_input.py`; `ManifestInput` w manifeście dziedziczy po nim (pola wymagane i domyślne dla starych manifestów) i dodaje `front_matter_pages`, `config_file` i `overrides`. Klucze najwyższego poziomu: `theme`, `age`, `style`, `format`, `pages`, `market`, `strict`, `output_dir`, `single_sided` (FR-22), `review_ideas`, `qa`, `image_provider`, `image_quality`, `concurrency`, `max_cost`, `log_level` oraz klucze stron wstępnych FR-23 `first_page`, `instructions`, `copyright`, `copyright_owner`.
- **Sekcje:** `front_matter` (`enabled` = `generate --front-matter`; `qa`, `image_quality`, `max_cost` polecenia `front-matter`), `belongs_to` (`enabled` = `generate --belongs-to-page`; `qa`, `image_quality`, `max_cost` polecenia `belongs-to`) i `cover` (jak w specyfikacji, `cover: true` to skrót). Strony wstępne FR-23 powstały po tej specyfikacji, stąd sekcja `front_matter`. W `generate --cover` sekcja `cover` daje też `color`, `select_pages`, `qa`, `back_text` i `image_quality` kroku okładki; `page`, `thumbnails`, `template` i `max_cost` czyta tylko polecenie `cover`. Sekcje nie dziedziczą wartości z najwyższego poziomu pliku.
- **Scalanie:** `resolve_input()` układa warstwy `settings.yaml` (z wartościami domyślnymi z kodu: `letter`, 30 stron, `output`), plik i flagi, i zwraca skuteczne `BookInput` z mapą źródeł. Flagi nie są walidowane przy scalaniu, bo sprawdzają je polecenia z dotychczasowymi komunikatami; plik jest walidowany przy wczytaniu. Błędy FR-01/FR-02 z wartością z pliku mają prefiks pliku (`kotki.yaml: pages: …`), z flagi zostają przy nazwie flagi. Profil w kolejności pierwszeństwa nie ma jeszcze żadnego klucza (dojdzie z `humanize`).
- **Opcje typer:** `--format`, `--pages`, `--strict` (teraz `--strict/--no-strict`) i `--output-dir` mają domyślnie `None`; wartości domyślne są w kroku scalania.
- **Polecenia:** `--config-file` w `ideas`, `generate`, `images`, `belongs-to`, `front-matter` i `cover`; `ideas --redo` go nie przyjmuje. `front-matter` zachowuje swoje pierwszeństwo z FR-23: flaga albo plik, potem wartość z manifestu, potem `settings.yaml`. Niezgodność kluczy `theme`, `age`, `style`, `format`, `pages` i `market` z manifestem to kod 1 z listą różnic; `front_matter_pages` nie jest kluczem pliku (wynika z `instructions`).
- **Manifest:** `input` zapisuje skuteczne wartości wszystkich kluczy; `output_dir` i `cover.template` jako ścieżki bezwzględne, żeby `manifest.json` użyty jako plik parametrów wskazywał te same miejsca. Plik z sekcją `input` jest czytany bez `front_matter_pages`, `config_file` i `overrides`. `overrides` to klucze podane flagami, gdy był plik.

### ⬜ FR-21: Chronione postacie, marki i produkty

Cel: temat może zawierać chronioną nazwę („Lego”, „Barbie”, „Grinch na święta”, „Kubuś Puchatek”). Wtedy program traktuje ją jako inspirację dla ogólnego tematu i pilnuje, żeby nazwa nie trafiła ani do metadanych, ani do opisów scen i promptów obrazu.

Dziś zakaz z FR-03 jest tylko zdaniem w prompcie. Reguła tematu (FR-03) każe jednocześnie trzymać się tematu, więc przy temacie „Grinch” model dostaje sprzeczne polecenia i nazwa może trafić do tytułu, słów kluczowych i scen. KDP traktuje cudze znaki towarowe i nazwy w tytule, opisie i słowach kluczowych jako mylące metadane, za co grozi zdjęcie książki, a przy powtórkach blokada konta.

**Zasada inspiracji**
- Z chronionej nazwy zostaje tylko ogólna kategoria: rodzaj zabawki, gatunek zwierzęcia, święto, nastrój, typ zabawy.
- Nie zostaje nic, co wskazuje na konkretny utwór lub produkt: nazwa i imiona postaci, charakterystyczny wygląd (kolor futra, strój, znaki szczególne, kształt figurki, logo), fabuła, cytaty ani miejsca z utworu.
- Wyjątek dla postaci z domeny publicznej jest możliwy tylko jawnie, dla wybranych rynków i stylów (niżej).

| Temat | Rozpoznana nazwa | Temat ogólny (przykład) | Czego nie rysować |
|---|---|---|---|
| Lego | LEGO | budowanie z klocków: domy, pojazdy, roboty z klocków | figurek o kształcie ludzików LEGO, logo na wypustkach |
| Barbie | Barbie | lalki i moda: przebieranki, sukienki, fryzury | charakterystycznej lalki, różowego logo, domku marki |
| Grinch na święta | Grinch | święta z humorem: psotne stworki, zimowe figle | zielonego futrzaka, kradzieży prezentów, psa z porożem, miasteczka z bajki |
| Kubuś Puchatek | Winnie-the-Pooh | misie i leśne zwierzątka, piknik, miód | czerwonej koszulki, prosiaczka, tygryska i osiołka, Stumilowego Lasu |

**Wyjątek: postać z domeny publicznej**
- Domyślnie każda nazwa z listy jest zablokowana. Wpis może dostać sekcję `public_domain`, którą dopisuje użytkownik po sprawdzeniu stanu prawnego, ze źródłem i datą. Lista startowa nie włącza jej dla żadnej postaci.
- Ten sam bohater bywa wolny w jednym kraju, a chroniony w innym. Książkowy Kubuś Puchatek z 1926 roku jest w USA w domenie publicznej od 2022 roku, ale jego wersja z filmów Disneya (czerwona koszulka, wygląd z kreskówek) i znaki towarowe nadal są chronione. W Wielkiej Brytanii tekst Milne’a będzie wolny od 1.01.2027, a ilustracje Sheparda (zm. 1976) są tam i w UE chronione jeszcze przez ok. 20 lat. Dlatego wyjątek dotyczy tylko rynków z listy `markets` (FR-19; do tego czasu rynku US).
- Wyjątek dotyczy tylko stylów z listy `styles`. To lista dozwolonych, nie zakazanych stylów: nowy styl dopisany do `styles.yaml` jest dla tej postaci zablokowany, dopóki ktoś go świadomie nie doda. Styl, który ciągnie rysunek w stronę chronionej wersji (np. `cartoon` przy Kubusiu, bo kreskówkowy Kubuś to wersja Disneya), zostaje poza listą.
- Poza dozwolonym rynkiem albo stylem postać jest tylko inspiracją, jak w zasadzie wyżej. Konsola podaje powód, np. `Kubuś Puchatek: styl cartoon nie jest dozwolony dla postaci z domeny publicznej (dozwolone: cozy, chibi); książka powstanie dla tematu ogólnego`.
- Co wyjątek zmienia: generator pomysłów może budować książkę wokół świata i postaci oryginału (`characters`), a imiona mogą stać w tytułach stron w `ideas.json`.
- Czego wyjątek nie zmienia:
  - **Metadane:** nazwa nadal nie trafia do tytułu, podtytułu, opisu ani słów kluczowych, bo znak towarowy nie wygasa razem z prawem autorskim.
  - **Opisy scen i prompty obrazu:** nie zawierają imion. Model obrazu zna te postacie głównie z wersji filmowej i narysuje ją niezależnie od stylu, więc zamiast imienia scena dostaje opis wyglądu z oryginału (`look`), a kontrola z kodu sprawdza `scene` i `elements` jak dotąd.
  - **Cechy wersji chronionej (`avoid`):** trafiają do QA jako kryterium `protected_character`, a nie do promptu, bo nazwana cecha przyciąga model.
- `ideas.json` → `theme_check` zapisuje tryb (`generic` albo `public_domain`), rynek, styl oraz `source` i `checked` z wpisu.

**Sprawdzenie tematu (przed pomysłami)**
- Kod szuka chronionych nazw w temacie, zanim cokolwiek wyśle do modelu (lista z `config/protected_names.yaml`, niżej).
- Wywołanie pomysłów (FR-03, nadal jedno, D5) dostaje regułę: jeśli temat zawiera chronioną nazwę, model wypisuje ją w `protected_terms`, pisze temat ogólny w `generic_theme` i planuje całą książkę od tematu ogólnego. Reguła tematu z FR-03 dotyczy wtedy tematu ogólnego. Nazwy znalezione przez kod trafiają do promptu jako podpowiedź, razem z polem `generic` z listy.
- Konsola pokazuje ostrzeżenie po polsku: `Temat zawiera chronioną nazwę: Grinch. Książka powstanie dla tematu ogólnego: „…”`. `ideas.json` → `theme_check` zapisuje `protected_terms`, `generic_theme` i źródło każdej nazwy (`list` albo `model`).
- `--strict` zamienia ostrzeżenie w błąd: nazwa z listy w temacie kończy się kodem 1 przed pierwszym wywołaniem API.
- Katalog książki dalej bierze nazwę z tematu podanego przez użytkownika (FR-08). To nazwa lokalna, nigdy nie trafia do KDP.

**Kontrola tekstów w kodzie**
- Lista nazw do sprawdzenia dla książki to `config/protected_names.yaml` plus `protected_terms` od modelu. Nazwy od modelu sprawdzane są tylko jako całe słowa.
- Kod sprawdza tytuł, podtytuł, opis, słowa kluczowe, `theme_anchors`, tytuły stron, `scene` i `elements` każdego pomysłu, prompty obrazu, teksty strony z FR-14 i okładki z FR-15 (tytuł, podtytuł, tekst na tyle) oraz opisy bohaterów z sekcji 14a, gdy powstaną.
- Dopasowanie bez wielkości liter i polskich znaków (to samo składanie co `slugify`), tylko całe słowa, plus odmiany z pola `forms`. Fragment słowa się nie liczy: „Lego” nie łapie „legowiska”. Samo imię „Kubuś” też nie, bo to zwykłe imię; złapie je dopiero forma z listy („Kubuś Puchatek”, „Kubusia Puchatka”).
- Nazwa w metadanych: jedno ponowienie wywołania z informacją, które pole zawiera którą nazwę. Gdy to nie pomoże, `ProviderError` (kod 4), jak przy błędnych metadanych w FR-03.
- Nazwa w pomyśle: kod daje mu werdykt `reject` z powodem `chroniona nazwa: Grinch`, bez wywołania LLM, i pomysł jest zastępowany jak w FR-03a. Bez weryfikacji pomysłów (`--no-review-ideas`) taki pomysł trafia na koniec rezerwy i nie dostaje strony.
- Ręcznie poprawiony `ideas.json` (FR-17): `images` sprawdza go przed pierwszą grafiką i przy trafieniu kończy się kodem 1 z listą pól.
- `PromptBuilder` sprawdza gotowy prompt jeszcze raz, bo fragmenty profili i opisy bohaterów pochodzą od użytkownika.

**Grafiki**
- Do `FIXED_CONSTRAINTS` (FR-04) dochodzi `no logos, no brand marks`. Promptu nie uzupełnia się nazwami do unikania, np. `not Grinch`, bo nazwa w prompcie przyciąga model do tej postaci.
- QA (FR-07) dostaje kryterium `protected_character`: strona przypomina znaną postać, maskotkę, zabawkę albo logo. Model z wizją podaje w szczegółach po polsku, co przypomina; strona wraca do ponownego generowania jak przy innych kryteriach. To samo kryterium dostaje QA strony z FR-14 i okładki z FR-15.
- Gdy `theme_check` znalazł chronioną nazwę, a QA jest wyłączone, konsola zaleca `--qa`. Bez QA podobieństwo rysunku do postaci nie jest sprawdzane.

**Konfiguracja: `config/protected_names.yaml`**

```yaml
# FR-21: nazwy, których nie może zawierać żaden tekst książki ani prompt.
# Dopasowanie: całe słowa, bez wielkości liter i polskich znaków.
names:
  - name: LEGO
    forms: [Legos]
    generic: building bricks
  - name: Barbie
    generic: fashion dolls and dress-up
  - name: Grinch
    forms: [Grincha, Grinchem, Grinchu, Grinchowi]
    generic: mischievous holiday creatures
  - name: Winnie-the-Pooh
    forms: [Winnie the Pooh, Pooh, Kubuś Puchatek, Kubusia Puchatka, Kubusiem Puchatkiem, Puchatek, Puchatka]
    generic: teddy bears and woodland animals
    # public_domain:                       # dopisuje użytkownik po sprawdzeniu stanu prawnego
    #   markets: [US]                      # książka z 1926 r.; w UK tekst od 2027, ilustracje dłużej
    #   styles: [cozy, chibi]              # bez cartoon: za blisko wersji filmowej
    #   characters: [Pooh, Piglet, Eeyore, Owl, Rabbit, Kanga, Roo]
    #   look:
    #     Pooh: small round teddy bear with short limbs, wearing no clothes
    #     Piglet: very small piglet in a striped knitted jumper
    #   avoid: [red shirt, animated film character design]
    #   source: https://web.law.duke.edu/cspd/publicdomainday/2022/bcvpd/
    #   checked: 2026-11-17
```

- Lista startowa obejmuje popularne w kolorowankach marki zabawek, postacie z filmów, seriali, gier i książek oraz ligi sportowe, z polskimi tytułami i odmianami. Rozwija ją użytkownik. Brak w liście nie oznacza, że nazwa jest wolna.
- Walidacja konfiguracji (§7): pusta nazwa albo zdublowana forma kończy się kodem 1. W `public_domain` klucze `styles` muszą istnieć w `styles.yaml`, `markets` w `markets.yaml` (FR-19), każda postać z `characters` musi mieć `look`, a `source` i `checked` są wymagane. Po FR-19 formy obejmują pisownię każdego rynku.

**Ograniczenia**
- Ani lista, ani model nie znają wszystkich chronionych nazw, a „inspiracja” może wyjść zbyt podobna. Program zmniejsza ryzyko, ale nie zastępuje porady prawnej. Ostateczną decyzję przed publikacją podejmuje użytkownik.
- Podsumowanie `generate` i `canva.md` przypominają, gdy temat zawierał chronioną nazwę: przed publikacją sprawdź tytuł, słowa kluczowe i okładkę.

**Uwagi do implementacji**
- Moduł `pipeline/protected.py`: `ProtectedNames` z konfiguracji, `find(text) -> list[Hit]` i wspólna funkcja składania znaków z `slugify`.
- Pola `protected_terms` i `generic_theme` w `_LLMIdeas` (opcjonalne przy wczytywaniu, żeby stare `ideas.json` działały). Werdykt kodu dla pomysłu przechodzi przez `IdeaReviewer._apply()`.
- Testy: odmiany polskie, „legowisko” bez trafienia, samo „Kubuś” bez trafienia, ponowienie z informacją zwrotną, nazwa w ręcznie poprawionym `ideas.json` (kod 1), `--strict` (kod 1 bez wywołań API), kryterium QA w `FakeVisionProvider`, wyjątek `public_domain` (dozwolony styl i rynek: imiona tylko w tytułach stron; styl spoza listy albo inny rynek: temat ogólny z powodem w konsoli; nowy styl domyślnie zablokowany).
### ✅ FR-22: Wnętrze książki jako PDF i druk jednostronny (poza MVP)

Cel: program składa gotowy plik wnętrza `interior.pdf` do wgrania w KDP, zamiast ręcznego składania w Canvie (D9). Strony wstępne opisuje FR-23.

**Druk jednostronny jako opcja**
- Flaga `--single-sided/--double-sided` w `ideas` i `generate`, domyślnie z `settings.yaml` (`interior.single_sided: true`). Przy druku jednostronnym każda kolorowanka stoi na stronie nieparzystej (prawej), a jej tył jest pusty. Przy dwustronnym kolorowanki idą jedna po drugiej.
- Wartość należy do książki: zapisuje ją `input.single_sided` w manifeście (stare książki: `true`, jak w D8), a FR-20 dodaje klucz `single_sided`.
- `finalize --single-sided/--double-sided` może ją zmienić później. Zmiana liczby stron może zmienić margines od grzbietu (§7.4), więc `finalize` przelicza wtedy strony, którym zmieniła się geometria (hash obróbki, FR-17). Okładka z inną liczbą stron jest nieaktualna: `finalize` to ostrzega, a `cover` liczy grzbiet od nowa.

**Kolejność stron**
- Strony wstępne (FR-23) zajmują parzystą liczbę stron, więc pierwsza kolorowanka zawsze trafia na stronę nieparzystą (prawą). Bez instrukcji: strona 1 i prawa autorskie (2 strony). Z instrukcją: dodatkowo instrukcja i pusta strona za nią (4 strony).
- Jednostronnie: `[1] pierwsza strona, [2] prawa autorskie, [3] instrukcja, [4] pusta, [5] page_01, [6] pusta, [7] page_02, …, page_N, pusta`.
- Dwustronnie: `[1] pierwsza strona, [2] prawa autorskie, [3] instrukcja, [4] pusta, [5] page_01, [6] page_02, …`. Na końcu program dodaje pustą stronę, jeśli liczba stron jest nieparzysta. KDP i tak zaokrągla liczbę stron w górę do parzystej, a ta liczba wpływa na grzbiet okładki, więc lepiej, żeby plik miał ją od razu.
- FR-02 liczy odtąd `pages_in_book = front_matter_pages + pages × (2 przy druku jednostronnym, 1 przy dwustronnym)`, zaokrąglone w górę do parzystej. `front_matter_pages` wynika z FR-23 (2 albo 4) i przestaje być ustawieniem w `settings.yaml`. Stare manifesty zachowują zapisaną wartość.
- KDP przyjmuje najwyżej 4 puste strony z rzędu na początku i w środku pliku oraz 10 na końcu. Ten układ ma najwyżej jedną pustą stronę z rzędu, ale program i tak to sprawdza.

**Plik `interior.pdf`**
- Powstaje w kroku 3 (`finalize`), bez wywołań API, gdy wszystkie strony mają status `ok`. W przeciwnym razie `finalize` go nie pisze i podaje brakujące strony. Wyłącza go `interior.pdf: false` w `settings.yaml`.
- Każda strona PDF ma wymiary formatu (MediaBox i TrimBox), bez spadu. Zawiera całą stronę PNG z katalogu książki (FR-06, FR-23) w 300 DPI, bez skalowania. Pusta strona nie ma żadnej treści.
- Tekst stron wstępnych program rysuje w obrazie strony (jak w FR-14), więc PDF zawiera tylko obrazy i nie trzeba osadzać czcionek. Strony mają tylko wartości 0 i 255, więc zapisuje je jako 1-bitowe DeviceGray z kompresją Flate. Plik pozostaje mały i nie ma szarości od kompresji JPEG.
- PDF nie zawiera adnotacji, zakładek, komentarzy, znaczników cięcia ani metadanych. KDP wymienia te elementy wśród powodów odrzucenia pliku. Zapis rozszerza `pipeline/pdf.py` (dziś jednostronicowy PDF okładki w CMYK), bez nowej zależności.
- Kontrola po zapisie (jak NFR-07): liczba stron parzysta, ≥ 24 i równa `pages_in_book` z manifestu; wymiary każdej strony; pierwsza kolorowanka na stronie nieparzystej; limity pustych stron.
- Manifest → `interior`: ścieżka, liczba stron, `sha256`, tryb druku i mapa „strona PDF → plik” (pusta strona jako `null`). `cover` bierze liczbę stron do grzbietu z tego wpisu i ostrzega, gdy okładkę zrobiono dla innej liczby stron.

**Canva**
- D9 się zmienia: wnętrze składa program. Strony PNG i `canva.md` zostają jako ręczna droga na wypadek, gdyby ktoś chciał coś poprawić w Canvie. `canva.md` wskazuje najpierw `interior.pdf` i opisuje strony wstępne według kolejności z tego wymagania.

**Uwagi do implementacji**
- `pipeline/interior.py`: `interior_layout(manifest) -> list[str | None]` (czysta funkcja, łatwa do testów obu trybów) i zapis przez `pipeline/pdf.py`.
- Testy: kolejność stron w obu trybach, z instrukcją i bez; wyrównanie do parzystej; zmiana trybu w `finalize` (przeliczenie stron przy zmianie marginesu, ostrzeżenie o okładce); brak PDF przy niegotowych stronach; kontrola po zapisie.

**Implementacja (18.11.2026)**
- **Tryb druku:** `--single-sided/--double-sided` w `ideas`, `generate` i `finalize`, domyślnie `interior.single_sided` z `settings.yaml`; `input.single_sided` w manifeście (stare książki: `true`). `ideas <katalog> --redo` go nie przyjmuje. `finalize` ze zmianą trybu sprawdza liczbę stron jak FR-02 (ponad tabelę marginesów: kod 1, poniżej 24: ostrzeżenie), zapisuje nowy tryb i przelicza geometrię; strony, którym zmienił się margines, obrabia ponownie przez hash obróbki (FR-17), razem ze stronami wstępnymi. Gdy `manifest.cover` jest dla innej liczby stron, `finalize` ostrzeża i podaje `kdp-studio cover`.
- **Liczenie stron:** `models.pages_in_book(pages, front_matter_pages, single_sided)` zaokrągla w górę do parzystej; ostrzeżenie FR-02 podaje mnożnik i tryb druku, a `min_pages_for_kdp()` liczy minimum dla obu trybów.
- **`pipeline/interior.py`:** `interior_layout()` (czysta funkcja manifestu; `front_matter_files()` przeniesione z `canva.py`), `blank_run_problems()` (najwyżej 4 puste z rzędu, 10 na końcu), `layout_problems()` (parzysta, ≥ 24, równa `layout.pages_in_book`, pierwsza kolorowanka na stronie nieparzystej), `write_interior()` i `verify_interior()` (czyta zapisany plik: liczba stron, wymiary, puste strony tam, gdzie w układzie).
- **`pipeline/pdf.py`:** `bilevel_pdf()` przyjmuje generator stron, więc w pamięci jest naraz jedna strona; strona z obrazem ma `MediaBox` = `TrimBox` formatu i obraz 1-bit DeviceGray Flate, pusta nie ma `/Contents`. Bez `/Info`, adnotacji i zakładek. Wspólny zapis xref z `cover.pdf`. 102 strony kwadratowe 300 DPI: 2,5 MB, około 7 s.
- **Kiedy powstaje:** tylko w książce ze stronami wstępnymi FR-23 (z właścicielem praw); starsza dostaje komunikat, jak je dodać (`front-matter --copyright-owner`). Brakujące strony, zły układ albo nieudana kontrola to ostrzeżenie (kod wyjścia bez zmian) i usunięcie nieaktualnego `interior.pdf` oraz wpisu w manifeście, żeby nie wgrać do KDP starego wnętrza. Te same strony (hash kolejności i plików `inputs_sha256`) nie zapisują pliku od nowa.
- **Manifest → `interior`:** `file`, `pages`, `single_sided`, `sha256`, `inputs_sha256`, `order`, `created_at`. `cover` liczy grzbiet z `interior.pages`, jeśli PDF powstał.
- **`canva.md`:** najpierw wskazuje `interior.pdf` (albo mówi, że jeszcze nie powstał), tryb druku w opisie i w kroku 5, tabela kolejności z `interior_layout()`.
- **Bez zmian:** FR-20 (`--config-file`) nie istnieje, więc klucz `single_sided` w pliku książki dojdzie z nim.

### ✅ FR-23: Strony wstępne: pierwsza strona, prawa autorskie, instrukcja (poza MVP)

Cel: komplet stron przed kolorowankami w `interior.pdf` (FR-22). Strona 1 to tytułowa do kolorowania albo „This book belongs to…” (FR-14), strona 2 to informacja o prawach autorskich w języku rynku, a opcjonalna strona 3 to instrukcja z przykładową kolorowanką z postacią z książki.

**Polecenie**
- `kdp-studio front-matter <katalog-książki>` robi strony, które wymagają modelu obrazu: stronę 1 i ilustrację instrukcji. Opcje: `--first-page title|belongs-to`, `--instructions/--no-instructions`, `--qa`, `--image-quality`, `--max-cost`. Wymaga kroku 2 (gotowych surowych stron), jak FR-14.
- `generate` uruchamia je jako krok między `images` a `finalize` z tymi samymi flagami. Wartości domyślne pochodzą z `settings.yaml`: `front_matter.first_page` (domyślnie `belongs-to`) i `front_matter.instructions` (domyślnie `true`). `--belongs-to-page` zostaje jako skrót dla `--first-page belongs-to`, a `kdp-studio belongs-to` jako skrót dla `front-matter --first-page belongs-to`.
- Strona z prawami autorskimi nie wymaga modelu, więc powstaje w `finalize`. Gdy `front-matter` nie zostało uruchomione, `finalize` robi stronę 1 bez modelu: tytuł książki konturowymi literami na środku strony. Wtedy `interior.pdf` i tak powstaje, a konsola podaje ostrzeżenie.
- Wybór instrukcji zmienia liczbę stron wstępnych (2 albo 4), więc może zmienić margines od grzbietu. `front-matter` zapisuje nowy wybór w manifeście, a `finalize` przelicza strony jak w FR-22.

**Strona 1: tytułowa do kolorowania (`--first-page title`)**
- Działa jak FR-14. Model rysuje scenę z motywem książki z pustym polem w górnej części, a program sprawdza, czy pole jest puste, i wpisuje tytuł książki konturowymi literami do pokolorowania. Pole zapisuje `title_page.text_box`, a opis kompozycji `title_page.composition` w `settings.yaml`.
- Tytuł pochodzi z metadanych (FR-03; po FR-19 w języku rynku). Kontrola chronionych nazw (FR-21) obejmuje także ten tekst.
- Układ zapasowy, gdy pole nie jest puste po `max_retries`: tytuł w górnej części, a pod nim grafika pierwszej gotowej strony. Plik to `front_title.png`.
- `--first-page belongs-to` daje stronę z FR-14 bez zmian (`front_belongs_to.png`).

**Strona 2: prawa autorskie**
- Treść pochodzi z tłumaczeń w `config/markets.yaml` (FR-19), w sekcji `texts` według języka. Na start są wersje `pl`, `en` i `de`, które przygotował użytkownik, każda w trzech wariantach: `minimal` (jedno zdanie), `short` (z zakazem kopiowania) i `full` (rozbudowany). Wariant wybiera `--copyright minimal|short|full` w `ideas`, `generate` i `front-matter`, domyślnie `front_matter.copyright: short` w `settings.yaml`; wybór zapisuje manifest. Rynek wybiera tłumaczenie przez swój `locale` (np. `en-GB`), a jeśli go nie ma, przez sam język (`en`). Dopóki FR-19 nie działa, książka ma rynek US, czyli wersję `en`.
- Wstawki w tekście: `{year}` (rok z daty utworzenia książki w manifeście, więc ponowne `finalize` w styczniu go nie zmienia) i `{owner}`, czyli właściciel praw. Właściciel nie musi być autorem z KDP (pseudonim, firma), więc ma osobną wartość: `--copyright-owner` w `ideas` i `generate` albo `publisher.copyright_owner` w `settings.yaml`. Manifest go zapisuje. Brak tłumaczenia dla rynku książki albo brak właściciela praw kończy się kodem 1 przed pierwszym wywołaniem API.
- Każdy wiersz tekstu w konfiguracji to osobny akapit, a program zawija go do szerokości obszaru treści i zostawia między akapitami odstęp pół wiersza. Pierwsze zdanie (`© … Wszelkie prawa zastrzeżone.`) jest więc zawsze osobnym akapitem, jak we wzorze.
- Wygląd: zwykła, prosta czcionka bezszeryfowa (`front_matter.text_font`, czcionka OFL dołączona do repozytorium, z polskimi i niemieckimi znakami; kontrola znaków jak w FR-19), rozmiar `copyright_pt` (domyślnie 12 pt), wyrównanie do lewej. Blok tekstu stoi na dole obszaru treści, czyli tuż nad dolnym marginesem. Gdy się nie mieści, program zmniejsza czcionkę do `copyright_min_pt` (domyślnie 9 pt), a dalej kończy się kodem 1.
- Plik `front_copyright.png`, kontrola druku jak NFR-07.

**Strona 3: instrukcja (`--instructions`, domyślnie włączona)**
- Wzór to strona „Before you start”. U góry nagłówek grubą czcionką (Fredoka Bold), pod nim podziękowanie, śródtytuł i akapit o teście kredek i podkładaniu grubszej kartki. Teksty są w `texts` w `markets.yaml`, jak prawa autorskie. Wszystkie wpisuje program.
- Pod tekstem jest ilustracja z modelu: **główna postać książki** (najczęstszy `subject` stron, jak w FR-14) podkłada kartkę grubszego papieru pod stronę otwartej kolorowanki, ze strzałkami. Prompt dostaje blok stylu stron (FR-04), więc ilustracja pasuje do książki i sama nadaje się do kolorowania. Ograniczenia FR-04 zostają, z `no text` włącznie.
- Ilustracja trafia do pola `instructions.art_box` pod tekstem. QA (gdy włączone) sprawdza kryteria `text` i `scene_mismatch`. Po `max_retries` program bierze grafikę zapasową bez postaci: otwarta książka z kartką i strzałkami jako plik SVG w `assets/`, narysowany raz na potrzeby projektu.
- Za instrukcją jest zawsze pusta strona, także przy druku dwustronnym. Na instrukcji można testować kredki, a pusty tył chroni pierwszą kolorowankę.
- Plik `front_instructions.png`, surowa ilustracja w `raw/front_instructions.png`, odrzucone próby w `rejected/`.

**Teksty w `config/markets.yaml`**

```yaml
texts:
  en:
    copyright:
      minimal: "© {year} {owner}. All rights reserved."
      short: |
        © {year} {owner}. All rights reserved.
        No part of this publication may be reproduced or distributed without prior written permission from the copyright owner, except as permitted by law.
      full: |
        © {year} {owner}. All rights reserved.
        No part of this publication may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, including electronic, mechanical, photocopying, or recording, without prior written permission from the copyright owner, except as permitted by applicable law.
    instructions:
      heading: BEFORE YOU START
      intro: "Thank you so much for buying my book! I appreciate your support. Before starting your coloring journey, please read:"
      section: Paper Quality
      body: "For the best results, test your coloring supplies first. To help prevent bleed-through and protect the next page, place a blank sheet of thicker paper behind the page you are coloring."
  en-GB:                                  # tylko różnice względem en
    instructions:
      intro: "Thank you so much for buying my book! I appreciate your support. Before starting your colouring journey, please read:"
      body: "For the best results, test your colouring supplies first. To help prevent bleed-through and protect the next page, place a blank sheet of thicker paper behind the page you are colouring."
  pl:
    copyright:
      minimal: "© {year} {owner}. Wszelkie prawa zastrzeżone."
      short: |
        © {year} {owner}. Wszelkie prawa zastrzeżone.
        Żadna część tej publikacji nie może być kopiowana ani rozpowszechniana bez uprzedniej pisemnej zgody właściciela praw, z wyjątkiem przypadków dozwolonych przez prawo.
      full: |
        © {year} {owner}. Wszelkie prawa zastrzeżone.
        Bez uprzedniej pisemnej zgody właściciela praw żadna część tej publikacji nie może być powielana, przechowywana w systemach wyszukiwania informacji ani przekazywana w jakiejkolwiek formie lub za pomocą jakichkolwiek środków, w tym elektronicznych, mechanicznych, poprzez fotokopiowanie lub nagrywanie. Wyjątek stanowią przypadki dozwolone przez obowiązujące prawo.
    instructions:
      heading: ZANIM ZACZNIESZ
      intro: "Dziękuję za zakup tej książki! Bardzo doceniam Twoje wsparcie. Zanim zaczniesz kolorować, przeczytaj:"
      section: Jakość papieru
      body: "Najpierw wypróbuj swoje kredki i flamastry. Żeby kolor nie przebił na następną stronę, podłóż pod kolorowaną stronę czystą kartkę grubszego papieru."
  de:
    copyright:
      minimal: "© {year} {owner}. Alle Rechte vorbehalten."
      short: |
        © {year} {owner}. Alle Rechte vorbehalten.
        Kein Teil dieser Publikation darf ohne vorherige schriftliche Genehmigung des Rechteinhabers vervielfältigt oder verbreitet werden, soweit dies nicht gesetzlich erlaubt ist.
      full: |
        © {year} {owner}. Alle Rechte vorbehalten.
        Kein Teil dieser Publikation darf ohne vorherige schriftliche Genehmigung des Rechteinhabers in irgendeiner Form oder mit irgendwelchen Mitteln vervielfältigt, in einem Informationsabrufsystem gespeichert oder übertragen werden. Dies umfasst insbesondere elektronische und mechanische Verfahren sowie Fotokopien und Aufzeichnungen. Gesetzlich erlaubte Nutzungen bleiben unberührt.
    instructions:
      heading: BEVOR DU LOSLEGST
      intro: "Vielen Dank, dass du mein Buch gekauft hast! Ich freue mich sehr über deine Unterstützung. Bevor du mit dem Ausmalen beginnst, lies bitte:"
      section: Papierqualität
      body: "Teste deine Stifte am besten zuerst. Damit die Farbe nicht auf die nächste Seite durchdrückt, lege ein leeres Blatt dickeres Papier hinter die Seite, die du gerade ausmalst."
```

- Walidacja (§7): każdy język ma komplet kluczy, z trzema wariantami praw autorskich (po scaleniu `en-GB` z `en`), a wstawki są tylko z listy (`{year}`, `{owner}`). Wersja `en-GB` nie potrzebuje własnych praw autorskich, bo angielski tekst nie ma różnic w pisowni.

**Manifest i `canva.md`**
- `front_matter` w manifeście ma wpisy `first_page` (rodzaj, układ, pliki jak w FR-14), `copyright` (język, hash tekstu) i `instructions`. Zmiana tekstu, czcionki albo autora przelicza stronę w `finalize` bez wywołań API, jak przy FR-14.
- `canva.md` wymienia strony wstępne w kolejności z FR-22.

**Uwagi do implementacji**
- Wspólna logika ramki z pustym polem i układu zapasowego z FR-14 (`BelongsToMaker`, `BelongsToRenderer`) obsługuje rodzaje `belongs_to`, `title` i `instructions`.
- Testy: wybór tłumaczenia (`en-GB` → `en`) i wariantu (`minimal`, `short`, `full`), brak tłumaczenia lub właściciela praw (kod 1 bez API), blok praw autorskich nad dolnym marginesem i zmniejszanie czcionki, strona 1 bez `front-matter` (sam tytuł), układ zapasowy instrukcji, zmiana `--no-instructions` (2 strony wstępne zamiast 4).

**Implementacja (18.11.2026)**
- **Kolejność:** FR-23 przed FR-22. Strony wstępne powstają jako pliki PNG (dla Canvy i dla `interior.pdf` z FR-22).
- **Polecenie `front-matter`:** opcje ze specyfikacji oraz `--copyright` i `--copyright-owner`, żeby dało się dodać strony wstępne do książki zrobionej przed FR-23. `generate` ma krok „strony wstępne” między `images` a `finalize`, włączany `--front-matter/--no-front-matter` (`front_matter.in_generate`, domyślnie tak); `--first-page`, `--instructions/--no-instructions`, `--copyright`, `--copyright-owner` jak w spec. `--belongs-to-page` to skrót dla `--first-page belongs-to`, a `--no-belongs-to-page` dla `--first-page title`. `belongs-to` w książce FR-23 ustawia stronę 1 i usuwa tytułową.
- **Ustawienia:** `front_matter` (`first_page`, `instructions`, `copyright`, `in_generate`, `text_font`, `copyright_pt`, `copyright_min_pt`), `publisher.copyright_owner`, `title_page`, `instructions`. `front_matter_pages` przestaje być ustawieniem (2 albo 4 z `instructions`), a `belongs_to_page.enabled` znika. Manifest: `input.copyright`, `input.copyright_owner`, `input.first_page`, `input.instructions`; `front_matter.title`, `front_matter.instructions` (wpisy jak FR-14, układy `frame`, `fallback`, a dla strony 1 bez modelu `text_only`) i `front_matter.copyright` (język, wariant, właściciel, rok, hash tekstu).
- **Czcionki:** zwykły tekst Noto Sans (SIL OFL, `assets/fonts/NotoSans-Variable.ttf`, pobrana 18.11.2026; polskie i niemieckie znaki), nagłówek instrukcji i tytuł strony 1 czcionką napisów rynku (Fredoka albo Baloo 2, FR-19) w wariancie `Bold`. Kontrola znaków jak w FR-19, także dla właściciela praw i tytułu.
- **Teksty:** `texts` w `markets.yaml` z wersjami `en`, `en-GB`, `pl` i `de` ze specyfikacji. Na teksty rynku program nakłada też mapę pisowni (FR-19), więc CA i AU dostają „colouring” bez osobnej wersji `en-CA`. Rynki bez tłumaczenia (FR, ES, IT, NL, SE, JP) kończą `ideas` i `generate` kodem 1, jak w spec.
- **Właściciel praw** jest wymagany od nowej książki: bez `--copyright-owner` i `publisher.copyright_owner` (domyślnie `null`) `ideas` i `generate` kończą się kodem 1. Książki sprzed FR-23 (bez właściciela w manifeście) `finalize` zostawia bez stron FR-23.
- **Strona 1 bez `front-matter`:** `finalize` robi `front_title.png` z samym tytułem i wypisuje, jak dostać stronę z modelu. Instrukcja bez `front-matter` (gdy jest włączona) dostaje w `finalize` grafikę zapasową SVG, bez API. Obie informacje to zwykłe komunikaty, nie ostrzeżenia: strona jest poprawna.
- **Prawa autorskie:** akapity zawijane do szerokości obszaru treści, wysokość wiersza z metryk czcionki (Noto Sans ma duży zapas na wydłużenia liter), litery z ujemnym odstępem przesunięte do marginesu. Za długi tekst zmniejsza się co 0,5 pt do `copyright_min_pt`, dalej kod 1.
- **Instrukcja:** ilustrację rysuje model wg `instructions.composition` z `{subject}` (najczęstszy `subject` stron), z blokiem stylu stron. Bez kontroli pustego pola (tekst stoi nad ilustracją, w osobnej części strony); QA sprawdza `text` (tylko teksty programu) i `scene_mismatch`. Grafika zapasowa: `assets/front_matter/instructions.svg` (otwarta kolorowanka, kartka wsuwana pod stronę, strzałki).
- **`canva.md`:** strony wstępne w kolejności druku. Nazwy plików (`front_belongs_to`, `front_copyright`, `front_instructions`, `front_title`) nie układają się alfabetycznie w tej kolejności, więc instrukcja każe wstawiać je według tabeli.

### ✅ FR-24: A+ Content: grafiki i teksty modułów (poza MVP)

Zgłoszenie: #71. Wymaganie powstało z pomysłu w sekcji 14a.

Cel: grafiki i teksty modułów A+ Content (obrazki i teksty pod opisem na stronie Amazona) gotowe do wgrania i wklejenia w edytor A+ w KDP. Program ma wszystko, czego potrzeba: okładkę (FR-15), strony, temat, wiek i fakty o książce z manifestu. Zasady A+ (https://kdp.amazon.com/en_US/help/topic/G4WB7VPPEAREHAAD, sprawdzone 24.11.2026) są ostrzejsze niż zasady opisu.

**Moduły (edytor A+, sprawdzone 24.11.2026)**

Na stronie mieści się najwyżej 5 modułów. Limity znaków odczytano w edytorze.

| Moduł | Układ | Obraz | Teksty |
|---|---|---|---|
| Standard Company Logo | sam obraz | 600 × 180 | – |
| Standard Image Header With Text | nagłówek, obraz, nagłówek, tekst | 970 × 600 | nagłówki do 200 znaków, tekst do 6000 |
| Standard Three Images & Text | nagłówek modułu, potem 3 kolumny: obraz, nagłówek, tekst | 3 × 300 × 300 | nagłówek modułu do 200 znaków, nagłówki kolumn do 160, tekst kolumny do 1000 |
| Standard Four Images & Text | jak wyżej, 4 kolumny | 4 × 220 × 220 | jak wyżej |
| Standard Image with Dark/Light Overlay | obraz z tekstem nakładanym przez Amazon | co najmniej 970 × 300 | nagłówek do 60 znaków, tekst do 300 |
| Standard Comparison Chart | tabela 2–6 produktów z własnego konta | obraz produktu w kolumnie | wiersze cech |

- Pole edytora podaje proporcję obrazu (np. „300:300”), a nie rozmiar w pikselach. Program może więc renderować większe obrazy w tej proporcji.
- Pomoc KDP zaleca dwukrotność minimum: dla Image & Text Overlay minimum 970 × 300 i 1940 × 600 dla najwyższej rozdzielczości, dla Three Images & Text minimum 300 × 300 i zalecane 600 × 600 (https://kdp.amazon.com/en_US/help/topic/GCKLH8V7ULLD5EXY, sprawdzone 27.11.2026). Dla Image Header With Text pomoc nie podaje rozmiaru.
- Image Header With Text, test w edytorze 27.11.2026 (obrazy testowe z siatką co 50 px):
  - obraz 970 × 600 wypełnia całą szerokość modułu w podglądzie, równo z tabelą porównawczą nad nim, bez pustych pasów i bez przycięcia;
  - obraz 1070 × 600 podgląd modułu przycina do środkowych 970 × 600 (boki znikają);
  - okno szczegółów w bibliotece grafik (Creative Assets) pokazuje cały plik, więc nie mówi, co zobaczy kupujący.
  - obraz 1940 × 1200 (dwukrotność) wyświetla się jak 970 × 600: w podglądzie na komputerze wypełnia szerokość modułu, a w podglądzie na telefonie mieści się cały, przeskalowany do szerokości ekranu (ok. 390 px), w obu bez przycięcia;
  
  Wniosek: proporcja modułu to 970:600 i program renderuje dokładnie ją (1940 × 1200). Szerszy plik niczego nie daje, bo boki i tak zostaną ucięte.
- Teksty modułów mają formatowanie, ale tylko z paska narzędzi edytora: pogrubienie, kursywę, podkreślenie oraz listy punktowaną i numerowaną (w nakładce lista numerowana). Wklejony HTML nie działa: edytor nie zamienia znaczników na formatowanie (sprawdzone 24.11.2026). Tym różni się od opisu KDP (FR-03), który przyjmuje HTML.

**Układ strony (domyślny)**
1. **Baner:** Standard Company Logo 600 × 180. Buduje markę wydawcy na Amazonie, więc powstaje poza programem i jest wspólny dla wszystkich książek. Program bierze tylko gotowy plik z konfiguracji i wskazuje jego miejsce.
2. **1–2 × Standard Image Header With Text:** mockupy gotowego produktu, z minimum tekstu albo bez niego. Pierwszy, tuż pod banerem, to wachlarz okładek opisany niżej w części „Grafiki”; kolejny może pokazywać np. kilka pokolorowanych stron i kredki.
3. **Standard Image with Dark/Light Overlay z twardymi faktami:** zamiast jednego mockupu. Tekst nakładki to tekst strony, więc na telefonie skaluje się lepiej niż napis na grafice. Przykład:
   - liczba kolorowanek;
   - druk jednostronny: każdy obrazek na osobnej kartce, więc przebicie nie zniszczy następnego;
   - pisaki po podłożeniu grubszej kartki, jak na stronie z instrukcją (FR-23).

   Liczby i fakty pochodzą z manifestu, jak lista faktów w opisie (FR-03), więc A+ zgadza się z opisem i wnętrzem. Nie piszemy „nie przebija”, bo pisaki przebijają papier KDP. Liczbę podajemy jako kolorowanki („52 coloring pages”), a nie strony książki. Tekst nakładki przyjmuje listę numerowaną (sprawdzone 24.11.2026), więc fakty będą listą numerowaną.
4. **Jeden moduł 3 albo 4 kolumn:** korzyści i zawartość, bez powtarzania faktów z nakładki. Np. sceny z książki, poziom trudności dla wieku, spokojna zabawa bez ekranu. Każda kolumna ma kwadratową grafikę: stronę książki albo jej fragment. Opcjonalnie grafika z modelu pokazująca korzyść (motywy z profilu wieku, część „Kolumny z grafikami z modelu” niżej).
5. **Opcjonalnie Standard Comparison Chart:** kilka własnych kolorowanek, np. świątecznych. Tabela porównawcza to jedyne właściwe miejsce na „zobacz inne moje kolorowanki”. Tabela może zestawiać tylko książki z własnego konta KDP i układa się ją w KDP z numerów ASIN. Program może przygotować wiersze z manifestów tych książek (wiek, format, liczba grafik, temat), a ASIN-y wziąć z konfiguracji. Bez tabeli to miejsce dostaje drugi mockup.

Kolumny lepiej niż kolejne nakładki pokazują strony książki: kwadrat mieści całą stronę, a pas 970 × 300 tylko jej wycinek albo rząd małych miniatur i na telefonie robi się cienki. Dlatego nakładka jest jedna, na fakty. Zestaw modułów i ich kolejność są w konfiguracji (`aplus.modules`), a nie w kodzie; najwyżej 5.

**Grafiki**
- **Wymagania A+ dla obrazów:** JPG albo PNG w RGB, plik poniżej 2 MB, co najmniej 72 dpi, bez animacji (GIF).
- **Bez napisów od programu:** nagłówki i teksty idą do pól modułu, a obraz nie dostaje napisów. Tytuł widoczny na okładce w mockupie to zdjęcie produktu, nie napis.
- **Mockupy:** dwie drogi.
  - Składane przez program z gotowych plików okładki: perspektywa, obrót, cienie. Bez kosztu API i bez ryzyka zniekształceń. Pierwszy taki mockup opisuje punkt niżej.
  - Scena z modelu obrazu z okładką jako `reference_image`: płatna, a model może zniekształcić tytuł. Do rozważenia tylko dla ujęć, których program nie złoży (np. książka z kredkami na stole).
- **Nagłówek pod banerem: wachlarz okładek** (Standard Image Header With Text, 970 × 600; referencja: `docs/aplus/naglowek_wachlarz_referencja.jpg`, prototyp: `docs/aplus/mockup_prototype.py`, ustalone 26.11.2026):
  - **Kompozycja:** dwie książeczki leżą płasko i zachodzą na siebie jak wachlarz. Przód (`cover/front.png`) leży na wierzchu, obrócony w płaszczyźnie o 7° w lewo, przy lewej krawędzi grafiki. Tył (wycięty z `cover/cover.png` wg `manifest.cover.geometry`) leży pod spodem, obrócony o 9° w prawo i przesunięty w prawo o ok. 60% boku okładki, więc zachodzą na siebie mniej więcej w jednej trzeciej. Razem wypełniają szerokość grafiki.
  - **Wielkość:** bok okładki to ok. 83% wysokości grafiki (1000 px przy 1200). To największy rozmiar, przy którym obie obrócone książeczki mieszczą się w kadrze. Dwukrotne powiększenie względem pierwszej wersji nie mieści się bez ucięcia ilustracji.
  - **Grubość:** każda książeczka ma wąski pasek bloku kartek przy dolnej krawędzi, ok. 1/120 boku. Przy prawej krawędzi przód pokazuje kartki, a tył, leżący tylną okładką do góry, ma tam grzbiet: pasek w kolorze tła grzbietu, lekko przyciemniony, bez napisu.
  - **Cienie:** miękkie, przesunięte w prawo w dół, liczone z zapasem wokół książeczki, żeby rozmycie nie urywało się na brzegu.
  - **Tło:** nie białe i wyraźnie różne od okładek, żeby się z nimi nie zlewały. Program wybiera je z listy kandydatów w konfiguracji (jasne, stonowane barwy, np. beż, szałwia, pudrowy róż, szaroniebieski, ciepły szary). Wygrywa kandydat o największej odległości ΔE (Lab) od kolorów pasa brzegowego obu okładek; liczy się 5. percentyl odległości, żeby pojedyncze piksele nie decydowały. Kandydat poniżej progu `min_delta_e` odpada. Gdy żaden nie przechodzi, program przyciemnia najlepszego, aż przejdzie. Tło ma lekki pionowy gradient. W referencji (kotki) wygrał pudrowy róż.
  - **Plik:** 1940 × 1200 (dwukrotność 970 × 600), JPG jakości 90, RGB. Referencja waży 0,4 MB; ten sam obraz jako PNG miał 1,9 MB, tuż pod limitem 2 MB, dlatego JPG.
  - **Konfiguracja:** kąty, przesunięcie, wielkość, kandydaci tła i próg ΔE w `settings.yaml`, nie w kodzie.
  - **Pole kodu kreskowego:** na wydrukowanej książce KDP drukuje kod na dole tylnej okładki przy grzbiecie. Nasza okładka ma tam tło ilustracji, więc mockup pokazuje tył bez kodu, jak większość mockupów; w referencji to prawy dolny róg tyłu.
- **Pokolorowana strona:** model obrazu koloruje wybraną stronę jak przód okładki (FR-15), za opłatą w ramach `--max-cost`. Opcja, domyślnie wyłączona.

**Kolumny z grafikami z modelu (⬜, zgłoszenie #80, ustalone 28.11.2026)**

Kolumna ze stroną książki pokazuje zawartość, ale nie mówi rodzicowi, dlaczego ta książka mu pasuje. Opcjonalnie kolumny dostają więc grafiki z modelu obrazu, które pokazują jedną korzyść: kontury dla wieku, druk jednostronny, spokojne zajęcie bez ekranu. Koszt to 3–4 obrazy z referencją, ok. 0,15–0,25 USD na książkę.

- **Motywy są w profilu wieku** (`config/ages.yaml`, klucz `aplus_features`), bo to, na co patrzy rodzic przedszkolaka, różni się od tego, czego szuka dorosły. Każdy profil ma 3–4 motywy w kolejności kolumn; program bierze pierwsze `aplus.features.columns` pasujące do książki. Pola motywu:
  - `key`: klucz (unikalny w profilu), w nazwie pliku i manifeście;
  - `label`: krótki opis po polsku dla użytkownika (`aplus.html`, manifest);
  - `scene`: scena po angielsku do promptu obrazu i opis grafiki dla alt textu;
  - `benefit`: korzyść po angielsku, o której model pisze nagłówek i tekst kolumny w języku rynku;
  - `requires` (opcjonalnie): warunek książki, dziś tylko `single_sided` (FR-22). W książce dwustronnej motyw o druku jednostronnym byłby nieprawdą, więc wypada;
  - `fact` (opcjonalnie): fakt z listy faktów (FR-03), który kolumna przejmuje. Nakładka go wtedy pomija, żeby moduły się nie powtarzały (dziś `single_sided`).
- **Uczciwość obrazu:** A+ nie może wprowadzać w błąd co do produktu.
  - Model dostaje prawdziwą stronę książki jako `reference_image` (strony jak dziś, po kolei na kolumny), więc na obrazie widać zawartość książki, a nie wymyśloną.
  - Stałe ograniczenia w kodzie, nie w profilu: same dłonie, bez twarzy dzieci; bez napisów, logo i znaków towarowych; klejony paperback ze zwykłym białym papierem, bez spirali, perforacji i grubego kartonu; kontury strony z referencji bez zmian.
  - Podgląd `aplus.html` przypomina przy tych kolumnach o polu „AI-generated people” w bibliotece grafik edytora.
  - Bez napisów na obrazie, jak wszędzie: nagłówek i tekst idą do pól kolumny.
- **Wywołanie i koszt:** jedno wywołanie na kolumnę, `images.edit` z referencją, kwadrat, jakość z `aplus.features.image_quality`. Koszt (rodzaj `aplus`) liczy się do `--max-cost`. Obraz zapisuje się w `aplus/raw/features_N.png` z hashem (prompt, surowa strona, model, jakość), więc ponowne uruchomienie nie płaci drugi raz, jak pokolorowana strona.
- **Gdy obrazu nie ma** (błąd niekrytyczny dostawcy, limit kosztu, za mało pasujących motywów), kolumna dostaje stronę książki jak dziś, z ostrzeżeniem. Błąd krytyczny kończy krok kodem 4.
- **Teksty i alt text:** model tekstów dostaje `benefit` każdego motywu, a do alt textu opis z `scene`.
- **Włączanie:** `aplus.features.source: pages | generated` (domyślnie `pages`), flaga `--feature-images/--no-feature-images`, sekcja `aplus` w `--config-file` (FR-20).

Motywy w dostarczanych profilach (propozycja, do dopracowania przy pierwszej książce):

| Profil | Motywy (`label` → `scene` w skrócie) |
|---|---|
| `przedszkole` | grube kontury dla małych rąk → dłoń dziecka z grubą kredką na stronie; wspólne kolorowanie z rodzicem → dłoń dorosłego i dziecka na jednej stronie; obrazek na lodówce (`requires: single_sided`) → pokolorowana strona wycięta nożyczkami, na magnesie; spokojna chwila bez ekranu → stół z otwartą książką i kredkami |
| `wczesnoszkolne` | sceny z postaciami do opowiadania → dłoń z kredką przy scenie z kilkoma postaciami; pisaki nie zniszczą następnego obrazka (`requires: single_sided`, `fact: single_sided`) → strona pokolorowana pisakiem obok odwróconej kartki z czystym tyłem; spokojna chwila bez ekranu → stół z książką, kredkami i kubkiem kakao w klimacie tematu; gotowe dzieło do pokazania → pokolorowana strona przypięta do tablicy korkowej |
| `szkolne` | szczegółowe sceny na dłużej → kredki ołówkowe przy w połowie pokolorowanej stronie; pisaki i cienkopisy (`requires: single_sided`, `fact: single_sided`) → strona pokolorowana cienkopisami obok czystego tyłu; własne kolory → ta sama strona w dwóch zestawach barw obok siebie; spokojne popołudnie bez ekranu → biurko z książką i kredkami |
| `nastolatki` | wzory i detale → dłoń z cienkopisem przy drobnym wzorze; własny styl → żelopisy i markery przy pokolorowanej stronie; pisaki nie zniszczą następnej strony (`requires: single_sided`, `fact: single_sided`) → jak wyżej; odpoczynek od telefonu → telefon odłożony ekranem w dół obok książki |
| `dorosli` | relaks po dniu → stół z herbatą, kredkami i otwartą książką w ciepłym świetle; drobne pola dla precyzji → zbliżenie dłoni z cienkopisem w gęstym wzorze; pisaki po podłożeniu kartki (`requires: single_sided`, `fact: single_sided`) → strona pokolorowana pisakami z podłożoną kartką; obrazek do oprawienia → pokolorowana strona w ramce na ścianie |

Motyw „bez ekranu” mówi o zajęciu, nie obiecuje efektów (np. „uspokaja”, „rozwija koncentrację”), bo to byłoby twierdzenie bez źródła (Claims and awards).

**Tekst alternatywny (alt text)**
- Amazon wymaga tekstu alternatywnego przy każdej grafice A+; bez niego edytor nie przyjmie treści do zatwierdzenia. Pole edytora przyjmuje najwyżej 99 znaków, razem ze znakami interpunkcyjnymi (test w edytorze 28.11.2026: dłuższy tekst się nie mieści, przecinek przechodzi; poradniki podają 100).
- Zasady A+ (<https://kdp.amazon.com/help/topic/G4WB7VPPEAREHAAD>): alt text, który nie opisuje obrazu i nie pomógłby osobie z czytnikiem ekranu (dawniej „image keywords”), może być powodem odrzucenia. Program opisuje więc, co widać, i nie upycha w nim słów kluczowych, choć radzą to poradniki SEO.
- Alt text grafik programu pisze model w tym samym wywołaniu co teksty pól, w języku rynku. Program podaje mu dla każdej grafiki klucz i opis po angielsku: wachlarz okładek z tytułem, strony wnętrza i pas nakładki ze scenami, kolumny ze sceną strony (pokolorowana pierwsza kolumna jako pokolorowana; kolumna z modelu ze `scene` motywu), okładki książek z tabeli porównawczej z tytułem. Klucze: `header_fan`, `header_pages`, `overlay_facts`, `features_1…`, `chart_1…`.
- Baner wydawcy ma alt text z ustawienia `aplus.logo_alt`, bo model nie wie, co na nim jest.
- Kod przycina alt text do limitu (`aplus.limits.alt_text`) z ostrzeżeniem, odrzuca klucze spoza listy i ostrzega, gdy grafika nie ma tekstu (przy banerze z podpowiedzią `aplus.logo_alt`) albo dwie mają ten sam. Zakazane sformułowania sprawdza tak samo jak w polach tekstowych.
- Alt text jest w `aplus/texts.yaml` (sekcja `alt`; ręczne poprawki zostają), w manifeście (`aplus.texts.alt`) i w podglądzie `aplus.html` pod każdą grafiką z przyciskiem kopiowania (także w nagłówkach kolumn tabeli porównawczej). Zmiana opisów grafik (np. inne strony w kolumnach) zmienia hash wejść tekstów, więc teksty powstają od nowa.

**Teksty i zakazane sformułowania**

Teksty powstają w jednym wywołaniu LLM z regułami A+ w prompcie i są sprawdzane w kodzie. Wzorce i listy słów są w konfiguracji, według języka rynku. Trafienie oznacza jedno ponowienie, potem ostrzeżenie. Zakazane są trzy grupy.
- **Nacisk czasem:** „now”, „new”, „latest”, „yet”, „on sale now”, „the latest product”, „the best yet” i ich odpowiedniki w języku rynku.
- **Święto albo sezon jako termin lub okazja do zakupu:** KDP zakazuje „references to holidays” na tej samej liście co nacisk czasem. Czytamy to tak: zakazane jest święto jako punkt w czasie albo okazja skłaniająca do zakupu, także z nazwą konkretnego święta. Przykłady: „on sale before Christmas”, „in time for Easter”, „order before Valentine's Day”, „holiday gift”, „perfect Christmas gift”, „stocking stuffer”, a także ogólne „holidays”, „holiday season”, „na święta”, „na wakacje”. Dozwolone jest święto jako temat zawartości, np. „Christmas coloring book with Santa, reindeer and gingerbread houses”. To nasza interpretacja: rozstrzygnie pierwsza recenzja A+, a przy odrzuceniu nazwy świąt trafią na listę zakazanych.
- **Przechwałki (Claims and awards):** „perfect”, „best”, „ultimate”, „must-have”, „#1”, „top-rated”, „bestseller” i obietnice satysfakcji („100% satisfaction guaranteed”). Rekomendacje i certyfikaty („recommended by”, „approved”, „tested”) wymagają podania źródła i roku, więc program ich nie używa.

Do tego zasady wspólne z opisem: bez cen, rabatów, „free”, „bonus”, „buy now”, „add to cart”, „free shipping” i bez wzmianki o Kindle+.

**Wynik**
- `kdp-studio aplus <katalog>` zapisuje katalog `aplus/` z obrazami modułów, nazwanymi w kolejności modułów (np. `02_header_fan.jpg`, `04_features_1.jpg`).
- Obok powstaje podgląd `aplus.html` ułożony jak moduły, z przyciskiem kopiowania przy każdym polu. Przycisk kopiuje zwykły tekst, a punkty listy jako osobne wiersze; formatowanie (pogrubienie, lista) użytkownik nakłada paskiem narzędzi edytora, a podgląd pokazuje, gdzie. Do sprawdzenia przy pierwszym użyciu: czy edytor zachowuje formatowanie przy wklejeniu sformatowanego tekstu ze strony (schowek `text/html`), a nie znaczników. Jeśli tak, przycisk może kopiować i to.
- Manifest dostaje sekcję `aplus`: moduły w kolejności, pliki z wymiarami i rozmiarem, teksty pól, wybrane tło (kandydat, ΔE), ostrzeżenia z kontroli tekstów, koszt i datę. Koszt wywołań liczy się do `--max-cost` (FR-10) jak pozostałe kroki.

**Polecenie**
- `kdp-studio aplus <katalog-książki>`, osobny krok po okładce. Wymaga stron `ok` (FR-17) i okładki ze statusem `ok` (FR-15), bo mockupy składa z `cover/front.png` i `cover/cover.png`. Bez nich kod 1 z informacją, czego brakuje. `generate` go nie uruchamia.
- Opcje: `--color-page/--no-color-page` (pokolorowana strona z modelu, domyślnie `aplus.color_page: false`), `--max-cost`, `--log-level`, `--config-file` (FR-20, sekcja `aplus`).
- Wywołania API: jedno wywołanie LLM na teksty (z jednym ponowieniem po kontroli) i opcjonalnie jedno płatne pokolorowanie strony. Grafiki składa program, bez API.
- Ponowne uruchomienie robi tylko to, co się zmieniło: grafiki, gdy zmieniła się okładka, strony albo ustawienia (hash wejść jak w FR-17), teksty, gdy zmieniły się metadane albo fakty. Teksty poprawione ręcznie w `aplus/texts.yaml` program zostawia, jak ręcznie poprawione strony.

**Konfiguracja (szkic)**

```yaml
# settings.yaml
aplus:
  modules: [logo, header_fan, overlay_facts, features, comparison]   # kolejność, najwyżej 5
  logo: null                    # plik banera 600 × 180 przygotowany poza programem
  logo_alt: null                # tekst alternatywny banera (A+ wymaga go przy każdej grafice)
  image_format: jpg
  jpeg_quality: 90
  scale: 2                      # obrazy w dwukrotności proporcji z edytora
  color_page: false             # --color-page: pokolorowana strona z modelu (płatna)
  limits:                       # znaki, z edytora A+ (24.11.2026)
    header: {headline: 200, body: 6000}
    columns: {module_headline: 200, headline: 160, body: 1000}
    overlay: {headline: 60, body: 300}
    alt_text: 99                # tekst alternatywny każdej grafiki (pole edytora: najwyżej 99)
  header_fan:
    front_angle_deg: 7
    back_angle_deg: -9
    back_offset: 0.62           # przesunięcie tyłu w bokach okładki
    size: 0.83                  # bok okładki względem wysokości grafiki
    page_edge: 0.0083           # grubość bloku kartek względem boku
    background:
      candidates: {beż: [226, 212, 190], szałwia: [200, 212, 190], pudrowy róż: [232, 206, 200],
                   szaroniebieski: [200, 210, 222], ciepły szary: [214, 208, 200]}
      min_delta_e: 15           # do ustalenia po kilku okładkach
  features:
    columns: 3                  # 3 albo 4
    source: pages               # pages | generated (--feature-images): motywy z ages.yaml aplus_features
    image_quality: medium       # grafiki kolumn z modelu (płatne)
  comparison:                   # tabela porównawcza: 2–6 książek z własnego konta
    books: []                   # [{asin: B0…, book: output/…}]
```

- Zakazane sformułowania według języka w `config/markets.yaml` (`texts.<język>.aplus_banned`: `time`, `occasion` z nazwami świąt i słowami terminu lub zakupu, `claims`, `sales`), jak teksty stron wstępnych (FR-23).
- Walidacja (§7): najwyżej 5 modułów, znane nazwy modułów, `comparison` z 2–6 książkami (bez nich moduł wypada z ostrzeżeniem), kandydaci tła jako RGB, limity dodatnie.

**Uwagi do implementacji**
- Moduły: `pipeline/aplus_images.py` (wachlarz okładek, kwadraty kolumn ze stron, pas nakładki, kontrola rozmiaru i trybu pliku), `pipeline/aplus_text.py` (prompt z faktami z `book_facts()` z FR-03, schemat pól z limitami, kontrola zakazanych sformułowań, przycinanie do limitu z ostrzeżeniem), `pipeline/aplus_preview.py` (`aplus.html`). Prototyp wachlarza: `docs/aplus/mockup_prototype.py`.
- Grafiki bez modelu są deterministyczne, więc testy porównują je z plikami wzorcowymi (jak FR-06).
- Testy: wymiary, tryb i rozmiar plików poniżej 2 MB; wybór tła (najlepszy kandydat, próg i przyciemnianie); grzbiet tyłu i cienie bez urwania; zakazane sformułowania (święto jako temat przechodzi, jako termin albo okazja nie; przechwałki; nacisk czasem); limity znaków; alt text przy każdej grafice (klucze, brak, powtórzenie, limit, baner z ustawień); tabela porównawcza z manifestów innych książek; brak wywołań API dla samych grafik; kod 1 bez okładki.

**Do sprawdzenia przy pierwszej książce**
- Czy wklejony sformatowany tekst ze strony (schowek `text/html`) zachowuje formatowanie; jeśli tak, przyciski mogą kopiować też formatowanie.
- Wynik pierwszej recenzji A+: czy sama nazwa święta jako temat przechodzi.
- Próg ΔE tła po kilku różnych okładkach.

**Implementacja (27.11.2026)**
- **Moduły kodu:** `pipeline/aplus_images.py` (wachlarz, kwadraty kolumn, drugi mockup, pas nakładki, baner, zapis z kontrolą), `pipeline/aplus_text.py` (prompt, schemat `_AplusTexts`, `banned_hits()`, `apply_limits()`), `pipeline/aplus_preview.py` (`aplus.html`), `pipeline/aplus_models.py` (teksty pól i wpis manifestu, osobno, żeby manifest nie importował generatora) i `pipeline/aplus.py` (plan bez API, hashe, wykonanie `AplusRun`). CLI `aplus` tylko tworzy dostawców i wypisuje wynik.
- **Nazwy modułów w `aplus.modules`:** `logo`, `header_fan`, `header_pages` (drugi mockup: kilka stron wnętrza obok siebie, składany przez program), `overlay_facts`, `features`, `comparison`. Gdy tabela nie ma co najmniej 2 książek, w jej miejscu staje `header_pages` (albo moduł wypada, jeśli `header_pages` już jest), z ostrzeżeniem.
- **Tabela porównawcza:** książki z `aplus.comparison.books` (`asin` + katalog książki), zwykle w `--config-file` (sekcja `aplus`, FR-20; ścieżki względne od pliku). Ta książka, jeśli jej nie ma na liście, dochodzi jako pierwsza kolumna bez ASIN. Wiersze (wiek, liczba kolorowanek, format) mają etykiety w języku rynku; najwyżej 6 kolumn.
- **Konfiguracja tekstów:** zakazane sformułowania i etykiety tabeli są w `config/markets.yaml` w osobnym kluczu `aplus_texts.<język|odmiana>` (`banned.time`, `banned.occasion.phrases/holidays/context/window`, `banned.claims`, `banned.sales`, `chart`), a nie w `texts.<język>.aplus_banned`: `texts` przyjmuje tylko napisy, a tu są listy. Dopasowanie całych słów bez wielkości liter; myślnik łączy słowa, więc „screen-free” nie trafia na „free”. Nazwa święta trafia tylko w odległości `window` słów od słowa terminu albo zakupu.
- **Teksty:** fakty nakładki to `fact_lines()` z opisu (FR-03), nie od modelu; ponowienie dotyczy tylko tekstów od modelu, a fakty z zakazanym słowem dają ostrzeżenie. Limity: przycięcie na granicy słowa z ostrzeżeniem; fakty, które się nie mieszczą, wypadają od końca.
- **Pokolorowana strona** (`--color-page`): strona pierwszej kolumny, `images.edit` z referencją, zapis w `aplus/raw/<strona>_color.png`; ta sama strona nie jest kolorowana ponownie. Opcja `--image-quality` dla tego wywołania.
- **Ponowne uruchomienie:** `images_sha256` (pliki okładki i stron, ustawienia `aplus` bez limitów, baner, pokolorowana strona) i `texts_inputs_sha256` (metadane, fakty, sceny kolumn, rynek, limity, zakazane słowa). Plik `aplus/texts.yaml` różny od zapisanego przez program jest ręczną poprawką: zostaje, a podgląd i manifest biorą go jako teksty.
- **Kody wyjścia:** 1 bez stron `ok` albo okładki `ok`, albo przy złym `texts.yaml`; 2, gdy teksty nie powstały przez błąd dostawcy (grafiki i podgląd są); 3 po przekroczeniu limitu; 4 przy błędzie krytycznym dostawcy.
- **Sprawdzone na książkach z repozytorium:** wachlarz kotków wybiera pudrowy róż (ΔE 16,6) jak referencja, ciężarówek szałwię (20,5); wachlarz JPG ma ok. 0,4 MB.

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
    # ImageRequest: prompt, aspect, quality, seed (opcjonalnie), reference_image (opcjonalnie),
    #   mask (opcjonalnie, PNG z alfą: przezroczyste = do dorysowania; tylko z reference_image)
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
  [--config-file ksiazki/dinozaury.yaml] \
  --theme "Dinozaury" \
  --age przedszkole \
  --style kawaii \
  --format square \
  --pages 30 \
  [--market US] \
  [--output-dir ./output] \
  [--concurrency 4] \
  [--max-cost 5.00] \
  [--qa] \
  [--image-quality low|medium|high] \
  [--no-review-ideas] \
  [--belongs-to-page] \
  [--first-page title|belongs-to] [--instructions|--no-instructions] \
  [--single-sided|--double-sided] [--copyright minimal|short|full] [--copyright-owner "Jan Kowalski"] \
  [--cover] \
  [--strict] \
  [--image-provider openai|comfyui] \
  [--seed 1234] \
  [--log-level info|debug]

# Generowanie krokowe (FR-17)
kdp-studio ideas --theme "Dinozaury" --age przedszkole --style kawaii --format square --pages 30 \
  [--market US] [--output-dir ./output] [--no-review-ideas] [--strict] [--max-cost 5.00]
kdp-studio ideas ./output/dinozaury_przedszkole_kawaii_square --redo idea_07,idea_19
kdp-studio images ./output/dinozaury_przedszkole_kawaii_square \
  [--qa] [--image-quality low|medium|high] [--concurrency 4] [--max-cost 5.00]
kdp-studio finalize ./output/dinozaury_przedszkole_kawaii_square
# A+ Content (FR-24, poza MVP): po okładce, grafiki bez API, teksty jednym wywołaniem LLM
kdp-studio aplus ./output/dinozaury_przedszkole_kawaii_square [--color-page] [--max-cost 1.00]
# Każdy krok przyjmuje też --log-level info|debug (NFR-09)
# Plik parametrów książki (FR-20, poza MVP): flagi nadpisują wartości z pliku
kdp-studio generate --config-file ksiazki/dinozaury.yaml --pages 40
kdp-studio images ./output/dinozaury_przedszkole_kawaii_square --config-file ksiazki/dinozaury.yaml
# Wznowienie przerwanego kroku = ponowne uruchomienie tej samej komendy

# Lista dostępnych profili
kdp-studio profiles [age|style|format|market]

# Strona „This book belongs to…” (FR-14, poza MVP), po kroku images
kdp-studio belongs-to ./output/dinozaury_przedszkole_kawaii_square \
  [--qa] [--image-quality low|medium|high] [--max-cost 1.00] [--remove]

# Okładka do gotowej książki (FR-15, poza MVP); generate --cover robi to samo bez --cover-page i --thumbnails
kdp-studio cover ./output/dinozaury_przedszkole_kawaii_square \
  [--cover-page 07] \
  [--thumbnails 03,12,21] \
  [--template kdp_template.png] \
  [--color|--no-color] [--image-quality low|medium|high] \
  [--select-pages|--no-select-pages] [--back-text] \
  [--qa] \
  [--max-cost 1.00]

# Strony wstępne (FR-23, poza MVP), po kroku images; generate robi to jako krok przed finalize
kdp-studio front-matter ./output/dinozaury_przedszkole_kawaii_square \
  [--first-page title|belongs-to] [--instructions|--no-instructions] \
  [--qa] [--image-quality low|medium|high] [--max-cost 1.00]
# finalize pisze też interior.pdf (FR-22) i może zmienić tryb druku
kdp-studio finalize ./output/dinozaury_przedszkole_kawaii_square [--single-sided|--double-sided]

# Koszt druku, cena minimalna i tantiemy (FR-16, poza MVP)
kdp-studio price ./output/dinozaury_przedszkole_kawaii_square [--market US,UK,DE,PL] [--price 9.99]
kdp-studio price --format letter --pages 30 [--market US]
```

### 9.2 Konfiguracja i sekrety
- Sekrety wyłącznie w zmiennych środowiskowych lub `.env` (w `.gitignore`): `OPENAI_API_KEY`, później `GEMINI_API_KEY`, a dla ComfyUI opcjonalnie `COMFYUI_URL` i `COMFYUI_TOKEN` (FR-18).
- Ustawienia domyślne w `config/settings.yaml` (dostawcy, modele, cenniki, `reserve_ratio`, strony wstępne `front_matter` (FR-23), wnętrze `interior` (FR-22), `review_ideas`, limity różnorodności `diversity` (FR-03b), `qa`, `qa_max_retries`, domyślna równoległość, poziom logu `log_level` (NFR-09), cennik API `api_pricing` i limit kosztu `max_cost_usd` (FR-10)). Flagi CLI nadpisują plik parametrów książki (`--config-file`, FR-20), a ten nadpisuje `settings.yaml`. Plik książki nie przyjmuje sekretów.

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
├── interior.pdf                    # gotowe wnętrze do KDP (FR-22, poza MVP)
├── description.html                # opis do wklejenia w KDP (FR-03)
├── front_title.png | front_belongs_to.png, front_copyright.png, front_instructions.png   # strony wstępne (FR-23)
├── front_belongs_to.png            # po `belongs-to` albo `generate --belongs-to-page` (FR-14, poza MVP)
├── page_01.png … page_30.png      # pełne strony do importu w Canvie, 300 DPI
├── svg/page_01.svg …               # archiwum wektorowe (nie do Canvy)
├── raw/page_01.png …               # surowe wyniki z modelu
├── rejected/page_07_try1.png …     # surowe grafiki odrzucone przez QA (powód w manifeście)
├── kdp-studio.log                  # logi strukturalne wszystkich kroków, wiersze JSON (NFR-09)
├── .kdp-studio.lock                # tylko w trakcie kroku (FR-17)
├── cover/                          # tylko po `kdp-studio cover` albo `generate --cover` (FR-15, poza MVP)
│   ├── cover.pdf                   # gotowy plik okładki do KDP, CMYK
│   ├── cover_proof.png, cover_gamut.png   # symulacja druku i mapa zmian kolorów
│   ├── cover.png, front.png
│   ├── cover_preview.png           # z liniami cięcia, strefami i polem kodu
│   └── raw/                        # front_sketch, front_color_tryN, back_tryN, contact_sheet
└── aplus/                          # tylko po `kdp-studio aplus` (FR-24, poza MVP)
    ├── 02_header_fan.jpg …         # obrazy modułów w kolejności modułów, RGB, < 2 MB
    ├── texts.yaml                  # teksty pól i alt text grafik; ręczne poprawki zostają
    └── aplus.html                  # podgląd modułów z przyciskami kopiowania
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
2. Strony wstępne: `[front_matter_pages]` (domyślnie strona tytułowa i „This book belongs to…”). Jeśli książka ma stronę z FR-14 (`front_belongs_to.png`), wstaw `front_belongs_to.png` na drugą stronę i rozciągnij na całą stronę, jak grafiki. W przeciwnym razie zaprojektuj tę stronę w Canvie.
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
| NFR-12 | Zgodność z KDP | Domyślne profile formatów zgodne ze specyfikacją KDP (trim, 300 DPI, marginesy, min. 24 strony). Przypomnienie o ujawnieniu AI (FR-13). Prompty nie generują postaci ani znaków chronionych prawem autorskim; chronione nazwy w temacie, metadanych, pomysłach i promptach sprawdza kod (FR-21). |
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
| 1a. Strona „This book belongs to…” | FR-14: ramka w motywie książki z modelu obrazu, napis i miejsce na imię dokładane przez program, polecenie `belongs-to` i krok `generate --belongs-to-page` | Na 3 tematach × 5 wiekach strona pasuje stylem do grafik, a pole na imię jest puste bez ręcznych poprawek w ≥ 80% przypadków (reszta przez układ zapasowy) |
| 1b. Okładka | FR-15: komenda `cover`, geometria z wzorów KDP, przód z pokolorowanej strony z tytułem, tył z grzbietem dopasowany do przodu, miniatury w ramkach, PDF | Na 3 książkach (letter i kwadrat, różna liczba stron) PDF przechodzi kreator KDP bez błędów, a podgląd KDP nie pokazuje szwu na grzbiecie ani elementów w polu kodu |
| 1c. Cena i tantiemy | FR-16: tabele kosztów druku i progów tantiem KDP w konfiguracji, komenda `price`, podsumowanie w `generate` i manifeście | Koszt druku i cena minimalna zgadzają się z kalkulatorem KDP dla letter i kwadratu przy 30, 54 i 100 grafikach na rynkach US, UK, DE i PL |
| 2. PDF w skrypcie | FR-22 i FR-23: `interior.pdf` ze stronami wstępnymi (tytułowa do kolorowania albo FR-14, prawa autorskie, instrukcja) i pustymi stronami, druk jednostronny lub dwustronny | `interior.pdf` dla letter i kwadratu, w obu trybach druku, przechodzi kreator KDP bez błędów, a liczba stron zgadza się z okładką |
| 3. Gemini | Adapter `GeminiImageProvider` i porównanie jakości z OpenAI | Przełączenie przez `--image-provider gemini` |
| 3a. ComfyUI lokalnie | FR-18: adapter `ComfyUIImageProvider`, workflow użytkownika w formacie API, osobny prompt negatywny, limit 512 × 512 / 768 × 512 px | Książka dla wieku przedszkolnego i wczesnoszkolnego (letter i kwadrat) przechodzi `finalize` i QA na poziomie zbliżonym do OpenAI; dla starszych wieków z węzłem powiększania w workflow |
| 4. UI | Streamlit albo Gradio (React dopiero przy produkcie dla innych) | Generowanie bez terminala |

Stan na 17.11.2026 (sekcja 0): zakres etapu 1 jest zrobiony, a jego kryterium wyjścia (książka przyjęta przez kreator KDP) czeka na pierwsze złożenie w Canvie. Etap 1a (FR-14) ma kod; jego kryterium wyjścia wymaga prób na prawdziwych tematach. Etap 1b (FR-15) ma kod wszystkich trzech etapów; jego kryterium wyjścia wymaga próby w kreatorze KDP. Etap 1c ma gotową specyfikację.

## 14. Otwarte pytania

1. Startowa lista stylów i dozwolone połączenia wiek × styl.
2. ~~Język metadanych książki: angielski czy parametr `--lang`?~~ Rozstrzygnięte w FR-19: parametr `--market` (rynek Amazona, domyślnie US), bo odmiana języka i słowa kluczowe zależą od rynku, a nie od samego języka.
3. Czy QA ma być domyślnie włączone po etapie 0, gdy znany będzie jego koszt i skuteczność?
4. Czy używać pierwszej zaakceptowanej strony jako referencji stylu dla kolejnych (spójność kontra koszt i czas)?
5. Wybór modelu tekstowego i domyślnej jakości (`quality`) modelu obrazu. Jakość sprawdzić porównaniem `low` i `medium` na tych samych pomysłach (FR-17).
6. ~~FR-14: wybór czcionki z licencją OFL i wariant polski napisu.~~ Rozstrzygnięte 16.11.2026: Fredoka, napis po angielsku, inny język przez `belongs_to_page.text`.
7. FR-15: ~~wybór czcionki tytułowej (OFL)~~ Fredoka Bold (16.11.2026). Kolory szablonu KDP są skalibrowane na szablonach kwadratu i letter. Profil CMYK (domyślnie SWOP 2013 CRPC5 z repozytorium; porównać z SWOP v2 i GRACoL przez `KDP_STUDIO_CMYK_PROFILE`) i sposób konwersji (`perceptual` czy `relative_colorimetric`) do wyboru po porównaniu `cover_proof.png` z egzemplarzem próbnym z KDP.
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
- W pliku parametrów książki (FR-20) bohater ma osobne pola `look` (wygląd) oraz `name` i `personality`, więc obie warstwy da się podać bez umownego formatu napisu.

**A+ Content:** przeniesione do wymagań jako FR-24 (#71).

**Słowa kluczowe z danych o wyszukiwaniach**
- Dziś słowa kluczowe wybiera model z samej wiedzy o rynku (FR-03). Narzędzia typu KDSpy czy Publisher Rocket pokazują, jak często kupujący wpisują daną frazę i ile książek z nią konkuruje.
- Jeśli któreś z nich udostępnia API na warunkach, które pozwalają go używać w programie, generator mógłby dostawać listę kandydatów z liczbami i wybierać frazy z dużym ruchem i małą konkurencją, także do tytułu i podtytułu.
- Do sprawdzenia przed wymaganiem: dostęp do API, licencja na użycie danych, koszt i rynki, które obejmuje.

**`--scenes`: własne sceny zamiast wymyślonych**
- Plik z listą scen podanych przez użytkownika zastępuje generowanie pomysłów (FR-03). Weryfikacja, prompty i dalsze kroki działają bez zmian.
- Zastosowanie: zbiór własnych opowiadań, w którym część stron to kolorowanki z wybranych scen, razem z `--character` dla bohaterów opowiadań.
- W pliku parametrów książki (FR-20) `scenes` to lista scen w miejscu albo ścieżka do pliku, liczona od katalogu pliku książki.

## 15. Źródła i referencje
- KDP: rozmiary stron (trim sizes), wymagania druku i ujawnianie treści AI: https://kdp.amazon.com/help/topic/GVBQ3CMEQW3W2VL6
- OpenAI Image API: https://developers.openai.com/api/docs/guides/image-generation
- Gemini API (Nano Banana), cennik: https://ai.google.dev/gemini-api/docs/pricing
- ComfyUI: API serwera (`/prompt`, `/history`, `/view`, `/upload/image`, format API workflow): https://docs.comfy.org/development/comfyui-server/comms_routes
- Adobe: kredyty generatywne (zakres użycia): https://helpx.adobe.com/firefly/using/generative-credits-faq.html
- Canva: formaty i limity przesyłanych plików (PNG, SVG): https://www.canva.com/help/upload-formats-requirements/
- KDP: wymagania dla plików do druku (300 DPI, spłaszczanie przezroczystości): https://kdp.amazon.com/help/topic/G202145060
- KDP: słowa kluczowe i metadane (czego unikać): https://kdp.amazon.com/help/topic/G201298500
- KDP: zasady A+ Content (nacisk czasem, święta, przechwałki, ceny, obrazy RGB poniżej 2 MB): https://kdp.amazon.com/en_US/help/topic/G4WB7VPPEAREHAAD
- KDP: okładka paperback (CMYK zalecany, bez mieszania przestrzeni barw, profile kolorów usuwane przed publikacją, brak wskazanego profilu i limitu farb): https://kdp.amazon.com/en_US/help/topic/G201953020
- Poradniki zewnętrzne o CMYK dla okładek (profile SWOP v2 / GRACoL; limit farb 240% w IngramSpark): https://www.ebookpbook.com/2026/04/30/rgb-vs-cmyk-book-covers/, https://www.kdpeasy.com/guides/kdp-cover-requirements
