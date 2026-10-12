# Drone channels: parser coverage

Generated 2026-10-12 11:14 UTC from the drones.sqlite journal.

## Messages

| channel | first | last | lines | message versions | late edits (>5 min) |
|---|---|---|---|---|---|
| kpszsu | 2026-08-10 | 2026-10-12 11:10 | 15403 | 13326 | 1208 |
| kudy_letyt | 2026-08-10 | 2026-10-12 10:19 | 45764 | 8144 | 116 |
| kyiv_nebo | 2026-08-10 | 2026-10-12 09:56 | 5919 | 5885 | 10 |

## Line kinds

| line kind | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| drone_jet | 7912 | 18377 | 355 |
| drone | 2855 | 6347 | 21 |
| kab | 1546 | 189 | 0 |
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
| exact | 9746 | 17578 | 3834 |
| fuzzy | 73 | 470 | 5 |
| lemma | 2879 | 7579 | 981 |
| none | 503 | 221 | 125 |
| **with coordinates** | **94.1%** | **98.8%** | **97.1%** |

`exact` — name as written; `lemma` — after inflection to the nominative; `fuzzy` — spelling variant / rapidfuzz ≥ 92 within the oblast; `context` — homonym chosen by proximity to places mentioned in the same message or the previous 30 min of the channel; `ambiguous` — several same-name places, no coordinates; `none` — not found. This is coverage, not accuracy: precision/recall come from `airalert drones-eval`.

## Top 50 unresolved place phrases

Add them to `data/gazetteer/kyiv_local.csv` (Kyiv) or tell the parser what they are.

| # | phrase | match | channel | n | oblast scope |
|---|---|---|---|---|---|
| 1 | межі | none | kpszsu | 19 | UA.04,nan |
| 2 | Миколаївку | ambiguous | kudy_letyt | 19 | UA.17 |
| 3 | Снігурівку | ambiguous | kpszsu | 18 | nan |
| 4 | Іванків | ambiguous | kpszsu | 16 | UA.12,nan |
| 5 | Калинопіль | none | kudy_letyt | 15 | UA.01 |
| 6 | Кременчуцького водосховища | none | kpszsu | 14 | UA.18,nan |
| 7 | Гайдамацьке | none | kudy_letyt | 12 | UA.10 |
| 8 | зону відчуження Чорнобильської АЕС | none | kpszsu | 11 | nan |
| 9 | центральної частини Києва | none | kpszsu | 11 | nan |
| 10 | північ Київщини | none | kpszsu | 11 | UA.02,nan |
| 11 | Дергачі/Малу Данилівку | ambiguous | kpszsu | 10 | nan |
| 12 | південь Одещини | none | kpszsu | 10 | UA.17 |
| 13 | Поліський природний заповідник | none | kudy_letyt | 10 | UA.27 |
| 14 | Маяки | ambiguous | kpszsu | 10 | nan |
| 15 | акваторії Чорного моря | none | kudy_letyt | 10 | UA.08,UA.16,UA.17 |
| 16 | столиці | none | kpszsu | 10 | UA.13,nan |
| 17 | південь Одещини (Вилкове) | none | kpszsu | 9 | UA.17 |
| 18 | Мости | ambiguous | kyiv_nebo | 9 | nan |
| 19 | Просяну | ambiguous | kudy_letyt | 9 | UA.04 |
| 20 | Південне | ambiguous | kpszsu | 8 | nan |
| 21 | Чабани | ambiguous | kpszsu | 8 | nan |
| 22 | Чорноморське | ambiguous | kpszsu | 8 | nan |
| 23 | Козин | ambiguous | kpszsu | 7 | nan |
| 24 | Богуслав | ambiguous | kpszsu | 7 | nan |
| 25 | півночі Чернігівщини вектором руху | none | kpszsu | 7 | nan |
| 26 | Сергіївку | ambiguous | kudy_letyt | 7 | UA.17 |
| 27 | Пеньківку | ambiguous | kudy_letyt | 7 | UA.23 |
| 28 | Підлітає | none | kyiv_nebo | 6 | UA.12 |
| 29 | Сергіївку/Затоку | ambiguous | kpszsu | 6 | UA.17,nan |
| 30 | схід Дніпропетровщини | none | kpszsu | 6 | nan |
| 31 | Городню | ambiguous | kpszsu | 6 | nan |
| 32 | столицю | none | kpszsu | 6 | nan |
| 33 | Козина | ambiguous | kpszsu | 5 | nan |
| 34 | Десну | ambiguous | kpszsu | 5 | nan |
| 35 | Нароўля | none | kudy_letyt | 5 | BY |
| 36 | Калинівку | ambiguous | kudy_letyt | 5 | UA.12,UA.13 |
| 37 | Південний міст | none | kudy_letyt | 5 | UA.12 |
| 38 | Циркони | none | kyiv_nebo | 5 | UA.12 |
| 39 | Кагарлик | ambiguous | kpszsu | 5 | nan |
| 40 | Кременчуцьке водосховище | none | kpszsu | 5 | nan |
| 41 | Гоголеве | ambiguous | kudy_letyt | 5 | UA.18 |
| 42 | Лебедівку | ambiguous | kudy_letyt | 5 | UA.13 |
| 43 | обласний центр | none | kpszsu | 5 | UA.02,UA.21,nan |
| 44 | Самарський ліс | none | kudy_letyt | 5 | UA.04 |
| 45 | Вишневе | ambiguous | kpszsu | 5 | nan |
| 46 | Березань | ambiguous | kpszsu | 5 | nan |
| 47 | Дмитрівку | ambiguous | kudy_letyt | 4 | UA.04 |
| 48 | Улянівку | ambiguous | kudy_letyt | 4 | UA.21 |
| 49 | Цей | none | kyiv_nebo | 4 | UA.12 |
| 50 | Хриплин | none | kudy_letyt | 4 | UA.06 |
