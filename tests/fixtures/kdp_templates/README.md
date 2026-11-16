# Szablony okładek KDP (FR-15)

Pliki testowe dla odczytu szablonu (`kdp-studio cover --template`).

| Plik | Parametry |
|---|---|
| `PAPERBACK_8.500x8.500_104_BW_WHITE_en_US.jpg` | paperback, 8.5" × 8.5", 104 strony, wnętrze czarno-białe, papier biały |

- Szablon pochodzi z kalkulatora okładek KDP. KDP udostępnia go jako PNG; ten egzemplarz został przekonwertowany do JPEG przy przesyłaniu, więc ma artefakty kompresji na krawędziach kolorów. Odczyt musi działać dla obu formatów, stąd tolerancje kolorów.
- Rozdzielczość szablonu to ok. 457.5 px/cal (8000 × 4003 px), a nie 300 DPI. Położenie obszarów porównuje się w calach, przeliczając piksele przez `szerokość_px / szerokość_okładki_in`.
- `*.expected.json` zawiera geometrię wyliczoną wzorami KDP, wartości zmierzone na szablonie i skalibrowane kolory. Zmierzone wartości zgadzają się z wyliczonymi z dokładnością do 0.003".
- Nazwa pliku KDP koduje parametry (`<oprawa>_<szer>x<wys>_<strony>_<atrament>_<papier>_<locale>`), które program porównuje z manifestem książki.
