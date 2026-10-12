# Drone channels: parser coverage

Generated 2026-10-12 12:06 UTC from the drones.sqlite journal.

## Messages

| channel | first | last | lines | message versions | late edits (>5 min) |
|---|---|---|---|---|---|
| kpszsu | 2026-08-10 | 2026-10-12 12:01 | 15415 | 13338 | 1208 |
| kudy_letyt | 2026-08-10 | 2026-10-12 10:19 | 45764 | 8144 | 116 |
| kyiv_nebo | 2026-08-10 | 2026-10-12 09:56 | 5919 | 5885 | 10 |

## Line kinds

| line kind | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| drone_jet | 7922 | 18377 | 355 |
| drone | 2856 | 6347 | 21 |
| kab | 1547 | 189 | 0 |
| summary | 717 | 657 | 0 |
| missile | 705 | 1106 | 84 |
| other | 676 | 249 | 758 |
| unknown | 471 | 0 | 3687 |
| header | 261 | 17956 | 0 |
| ballistic | 176 | 198 | 66 |
| noise | 76 | 40 | 10 |
| status:shot_down | 8 | 267 | 153 |
| status:all_clear | 0 | 65 | 654 |
| status:descending | 0 | 26 | 84 |
| status:recheck | 0 | 287 | 47 |

## Place resolution

| match | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| ambiguous | 294 | 89 | 17 |
| context | 12 | 142 | 5 |
| exact | 9757 | 17578 | 3834 |
| fuzzy | 67 | 467 | 4 |
| lemma | 2880 | 7579 | 982 |
| none | 509 | 224 | 125 |
| **with coordinates** | **94.1%** | **98.8%** | **97.1%** |

`exact` — name as written; `lemma` — after inflection to the nominative; `fuzzy` — spelling variant / rapidfuzz ≥ 92 within the oblast; `context` — homonym chosen by proximity to places mentioned in the same message or the previous 30 min of the channel; `ambiguous` — several same-name places, no coordinates; `none` — not found. This is coverage, not accuracy: precision/recall come from `airalert drones-eval`.

## Top 50 unresolved place phrases

Add them to `data/gazetteer/kyiv_local.csv` (Kyiv) or tell the parser what they are.

| # | phrase | match | channel | n | oblast scope |
|---|---|---|---|---|---|
| 1 | Миколаївку | ambiguous | kudy_letyt | 19 | UA.17 |
| 2 | межі | none | kpszsu | 19 | UA.04,nan |
| 3 | Снігурівку | ambiguous | kpszsu | 18 | nan |
| 4 | Іванків | ambiguous | kpszsu | 16 | UA.12,nan |
| 5 | Калинопіль | none | kudy_letyt | 15 | UA.01 |
| 6 | Кременчуцького водосховища | none | kpszsu | 14 | UA.18,nan |
| 7 | Гайдамацьке | none | kudy_letyt | 12 | UA.10 |
| 8 | північ Київщини | none | kpszsu | 11 | UA.02,nan |
| 9 | центральної частини Києва | none | kpszsu | 11 | nan |
| 10 | зону відчуження Чорнобильської АЕС | none | kpszsu | 11 | nan |
| 11 | Поліський природний заповідник | none | kudy_letyt | 10 | UA.27 |
| 12 | столиці | none | kpszsu | 10 | UA.13,nan |
| 13 | Дергачі/Малу Данилівку | ambiguous | kpszsu | 10 | nan |
| 14 | південь Одещини | none | kpszsu | 10 | UA.17 |
| 15 | Маяки | ambiguous | kpszsu | 10 | nan |
| 16 | акваторії Чорного моря | none | kudy_letyt | 10 | UA.08,UA.16,UA.17 |
| 17 | Мости | ambiguous | kyiv_nebo | 9 | nan |
| 18 | південь Одещини (Вилкове) | none | kpszsu | 9 | UA.17 |
| 19 | Просяну | ambiguous | kudy_letyt | 9 | UA.04 |
| 20 | Чорноморське | ambiguous | kpszsu | 8 | nan |
| 21 | Чабани | ambiguous | kpszsu | 8 | nan |
| 22 | Південне | ambiguous | kpszsu | 8 | nan |
| 23 | Козин | ambiguous | kpszsu | 7 | nan |
| 24 | Пеньківку | ambiguous | kudy_letyt | 7 | UA.23 |
| 25 | півночі Чернігівщини вектором руху | none | kpszsu | 7 | nan |
| 26 | Сергіївку | ambiguous | kudy_letyt | 7 | UA.17 |
| 27 | Богуслав | ambiguous | kpszsu | 7 | nan |
| 28 | схід Дніпропетровщини | none | kpszsu | 6 | nan |
| 29 | Городню | ambiguous | kpszsu | 6 | nan |
| 30 | Підлітає | none | kyiv_nebo | 6 | UA.12 |
| 31 | столицю | none | kpszsu | 6 | nan |
| 32 | Сергіївку/Затоку | ambiguous | kpszsu | 6 | UA.17,nan |
| 33 | Козина | ambiguous | kpszsu | 5 | nan |
| 34 | Десну | ambiguous | kpszsu | 5 | nan |
| 35 | Циркони | none | kyiv_nebo | 5 | UA.12 |
| 36 | Нароўля | none | kudy_letyt | 5 | BY |
| 37 | Лебедівку | ambiguous | kudy_letyt | 5 | UA.13 |
| 38 | Кременчуцьке водосховище | none | kpszsu | 5 | nan |
| 39 | обласний центр | none | kpszsu | 5 | UA.02,UA.21,nan |
| 40 | Південний міст | none | kudy_letyt | 5 | UA.12 |
| 41 | Самарський ліс | none | kudy_letyt | 5 | UA.04 |
| 42 | Вишневе | ambiguous | kpszsu | 5 | nan |
| 43 | Кагарлик | ambiguous | kpszsu | 5 | nan |
| 44 | Березань | ambiguous | kpszsu | 5 | nan |
| 45 | Калинівку | ambiguous | kudy_letyt | 5 | UA.12,UA.13 |
| 46 | Гоголеве | ambiguous | kudy_letyt | 5 | UA.18 |
| 47 | Одещині н.п.Балта | none | kpszsu | 4 | nan |
| 48 | Іванівки | ambiguous | kpszsu | 4 | nan |
| 49 | Хриплин | none | kudy_letyt | 4 | UA.06 |
| 50 | Калинівку/Васильків | ambiguous | kpszsu | 4 | UA.13 |
