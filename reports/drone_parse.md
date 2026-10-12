# Drone channels: parser coverage

Generated 2026-10-12 09:59 UTC from the drones.sqlite journal.

## Messages

| channel | first | last | lines | message versions | late edits (>5 min) |
|---|---|---|---|---|---|
| kpszsu | 2026-08-10 | 2026-10-12 09:51 | 15391 | 13314 | 1208 |
| kudy_letyt | 2026-08-10 | 2026-10-12 09:54 | 45725 | 8136 | 116 |
| kyiv_nebo | 2026-08-10 | 2026-10-12 09:56 | 5919 | 5885 | 10 |

## Line kinds

| line kind | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| drone_jet | 7903 | 18363 | 354 |
| drone | 2853 | 6343 | 21 |
| kab | 1544 | 189 | 0 |
| other | 1151 | 248 | 779 |
| summary | 717 | 657 | 0 |
| missile | 702 | 1106 | 84 |
| header | 261 | 17938 | 0 |
| ballistic | 176 | 198 | 66 |
| noise | 76 | 39 | 10 |
| status:shot_down | 8 | 267 | 147 |
| status:all_clear | 0 | 65 | 654 |
| status:descending | 0 | 26 | 102 |
| status:recheck | 0 | 286 | 47 |
| unknown | 0 | 0 | 3655 |

## Place resolution

| match | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| ambiguous | 178 | 108 | 12 |
| context | 86 | 122 | 5 |
| exact | 9168 | 17583 | 3802 |
| fuzzy | 63 | 470 | 4 |
| lemma | 2553 | 7562 | 970 |
| none | 511 | 205 | 133 |
| **with coordinates** | **94.5%** | **98.8%** | **97.1%** |

`exact` — name as written; `lemma` — after inflection to the nominative; `fuzzy` — spelling variant / rapidfuzz ≥ 92 within the oblast; `context` — homonym chosen by proximity to places mentioned in the same message or the previous 30 min of the channel; `ambiguous` — several same-name places, no coordinates; `none` — not found. This is coverage, not accuracy: precision/recall come from `airalert drones-eval`.

## Top 50 unresolved place phrases

Add them to `data/gazetteer/kyiv_local.csv` (Kyiv) or tell the parser what they are.

| # | phrase | match | channel | n | oblast scope |
|---|---|---|---|---|---|
| 1 | Миколаївку | ambiguous | kudy_letyt | 21 | UA.17 |
| 2 | Ширяєве | none | kudy_letyt | 15 | UA.17 |
| 3 | Південне | ambiguous | kpszsu | 12 | nan |
| 4 | Кременчуцького водосховища | none | kpszsu | 12 | UA.18,nan |
| 5 | Просяну | ambiguous | kudy_letyt | 11 | UA.04 |
| 6 | центральної частини Києва | none | kpszsu | 11 | nan |
| 7 | акваторії Чорного моря | none | kudy_letyt | 10 | UA.08,UA.16,nan |
| 8 | зону відчуження Чорнобильської АЕС | none | kpszsu | 10 | nan |
| 9 | Лавіна | none | kyiv_nebo | 10 | UA.12 |
| 10 | північ Київщини | none | kpszsu | 10 | UA.02,nan |
| 11 | Поліський природний заповідник | none | kudy_letyt | 10 | UA.27 |
| 12 | Сергіївку | ambiguous | kudy_letyt | 10 | UA.17 |
| 13 | південь Одещини | none | kpszsu | 10 | nan |
| 14 | південь Одещини (Вилкове) | none | kpszsu | 9 | nan |
| 15 | Дергачі/Малу Данилівку | ambiguous | kpszsu | 9 | nan |
| 16 | Мости | ambiguous | kyiv_nebo | 9 | nan |
| 17 | Іванків | ambiguous | kpszsu | 9 | UA.12,nan |
| 18 | Київське водосховище | none | kpszsu | 8 | UA.02 |
| 19 | Лебедівку | ambiguous | kudy_letyt | 7 | UA.13 |
| 20 | Пеньківку | ambiguous | kudy_letyt | 7 | UA.23 |
| 21 | Затоку | ambiguous | kpszsu | 7 | nan |
| 22 | Дмитрівку | ambiguous | kudy_letyt | 7 | UA.04,UA.16 |
| 23 | півночі Чернігівщини вектором руху | none | kpszsu | 7 | nan |
| 24 | столиці | none | kpszsu | 7 | UA.13,nan |
| 25 | Калинівку | ambiguous | kudy_letyt | 7 | UA.12,UA.13 |
| 26 | захід та | none | kpszsu | 6 | UA.01,UA.02,UA.13,UA.23,UA.27,nan |
| 27 | Чорноморське | ambiguous | kpszsu | 6 | nan |
| 28 | Затоки | ambiguous | kpszsu | 6 | nan |
| 29 | Сергіївку/Затоку | ambiguous | kpszsu | 6 | UA.17,nan |
| 30 | Підлітає | none | kyiv_nebo | 6 | UA.12 |
| 31 | Лавіни | none | kyiv_nebo | 5 | UA.12 |
| 32 | Кременчуцьке водосховище | none | kpszsu | 5 | nan |
| 33 | Гоголеве | ambiguous | kudy_letyt | 5 | UA.18 |
| 34 | Козина | ambiguous | kpszsu | 5 | nan |
| 35 | Київщині в районах н.п. Боярка/Чабани | none | kpszsu | 5 | nan |
| 36 | Нароўля | none | kudy_letyt | 5 | BY |
| 37 | заході Запоріжжя | none | kpszsu | 5 | nan |
| 38 | півночі Запоріжжя | none | kpszsu | 5 | nan |
| 39 | Циркони | none | kyiv_nebo | 5 | UA.12 |
| 40 | Самарський ліс | none | kudy_letyt | 5 | UA.04 |
| 41 | Південний міст | none | kudy_letyt | 5 | UA.12 |
| 42 | Сергіївку | ambiguous | kpszsu | 4 | UA.17 |
| 43 | південь та | none | kpszsu | 4 | UA.04,UA.07,UA.21 |
| 44 | Сергіївки | ambiguous | kpszsu | 4 | UA.17,nan |
| 45 | Схоже | none | kyiv_nebo | 4 | UA.12 |
| 46 | Південного | ambiguous | kpszsu | 4 | nan |
| 47 | межі між Чернігівщиною та Сумщиною | none | kpszsu | 4 | nan |
| 48 | територію Білорусі | none | kudy_letyt | 4 | BY,nan |
| 49 | Х-22 | none | kpszsu | 4 | nan |
| 50 | Хриплин | none | kudy_letyt | 4 | UA.06 |
