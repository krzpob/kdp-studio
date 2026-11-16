# Szablony okładek KDP (FR-15)

Pliki testowe dla odczytu szablonu (`kdp-studio cover --template`).

| Plik | Parametry |
|---|---|
| `PAPERBACK_8.500x8.500_104_BW_WHITE_en_US.jpg` | paperback, 8.5" × 8.5", 104 strony, wnętrze czarno-białe, papier biały |
| `PAPERBACK_8.500x11.000_104_BW_WHITE_en_US.jpg` | paperback, 8.5" × 11" (letter), 104 strony, wnętrze czarno-białe, papier biały |

- Szablony pochodzą z kalkulatora okładek KDP. KDP udostępnia je jako PNG; te egzemplarze zostały przekonwertowane do JPEG przy przesyłaniu, więc mają artefakty kompresji na krawędziach kolorów. Odczyt musi działać dla obu formatów, stąd tolerancje kolorów.
- Rozdzielczość szablonów to ok. 457.5 px/cal (szerokość zawsze 8000 px: 8000 × 4003 px dla kwadratu, 8000 × 5146 px dla letter), a nie 300 DPI. Położenie obszarów porównuje się w calach, przeliczając piksele przez `szerokość_px / szerokość_okładki_in`.
- `*.expected.json` zawiera geometrię wyliczoną wzorami KDP, wartości zmierzone na szablonie i skalibrowane kolory. Zmierzone wartości zgadzają się z wyliczonymi z dokładnością do 0.003".
- Oba szablony mają tę samą liczbę stron, więc ten sam grzbiet: różnią się tylko wysokością, co sprawdza, że pomiar pionowy (cięcie, strefy, pole kodu liczone od dołu) nie jest przypadkowy.
- Nazwa pliku KDP koduje parametry (`<oprawa>_<szer>x<wys>_<strony>_<atrament>_<papier>_<locale>`), które program porównuje z manifestem książki.
