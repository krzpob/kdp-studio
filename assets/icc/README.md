# Profile ICC

`SWOP2013C3_CRPC5.icc` to domyślny profil konwersji okładki do CMYK (FR-15, `cover.cmyk.profile` w `config/settings.yaml`). Odpowiada warunkom druku CGATS21-2-CRPC5 (SWOP 2013, papier powlekany, TAC 300%, GCR Medium+).

- Źródło: rejestr profili ICC, https://registry.color.org/profile-registry/SWOP2013C3_CRPC5
- Dostawca: Idealliance; copyright X-Rite, Inc.
- Profile ID: `1e1bd1ca 60b69673 b356f3cd 478494b2` (test `tests/test_cover.py` sprawdza, że plik jest niezmieniony)

## Licencja

Tekst licencji ze strony rejestru ICC:

> This profile is made available by IDEAlliance®, with permission of X-Rite, Inc., and may be used, embedded, exchanged, and shared without restriction. It may not be altered, or sold without written permission of IDEAlliance.

Pliku nie wolno więc zmieniać ani sprzedawać. Program używa go tylko do konwersji i podglądu, a do `cover.pdf` profil nie trafia.

## Własny profil

Inny profil, np. U.S. Web Coated (SWOP) v2 z pakietu profili Adobe, wskazujesz zmienną `KDP_STUDIO_CMYK_PROFILE` w pliku `.env` (ma pierwszeństwo przed `settings.yaml`). Profili Adobe nie wolno dołączać do repozytorium, dlatego `.gitignore` pomija wszystkie pliki `*.icc` poza tym jednym.

```bash
echo 'KDP_STUDIO_CMYK_PROFILE=~/icc/USWebCoatedSWOP.icc' >> .env
```
