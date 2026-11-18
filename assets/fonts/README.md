# Czcionki

- `Fredoka-Variable.ttf`: Fredoka (font zmienny, osie `wght` 300–700 i `wdth` 75–125), autorzy: The Fredoka Project Authors. Źródło: https://github.com/google/fonts/tree/main/ofl/fredoka (pobrane 16.11.2026, plik `Fredoka[wdth,wght].ttf`, tu bez nawiasów w nazwie).
- `Baloo2-Variable.ttf`: Baloo 2 (font zmienny, oś `wght` 400–800, warianty Regular, Medium, SemiBold, Bold, ExtraBold), autorzy: The Baloo 2 Project Authors. Źródło: https://github.com/google/fonts/tree/main/ofl/baloo2 (pobrane 18.11.2026, plik `Baloo2[wght].ttf`, tu bez nawiasów w nazwie). Ma litery Latin Extended (m.in. polskie ą, ć, ę, ń, ś, ź, ż), których nie ma Fredoka, więc używają jej rynki inne niż US i UK (`font` w `config/markets.yaml`, FR-19). Japońskich znaków nie ma.
- Licencje: SIL Open Font License 1.1, pełne teksty w `OFL.txt` (Fredoka) i `OFL-Baloo2.txt` (Baloo 2). Pozwalają na komercyjne użycie czcionek w drukowanych książkach.

Napis na stronie „This book belongs to…” (FR-14) używa wariantu `SemiBold` (`belongs_to_page.font_variation` w `config/settings.yaml`), a tytuł okładki (FR-15) wariantu `Bold` (`cover.title_font_variation`). Obie czcionki mają warianty o tych nazwach.
