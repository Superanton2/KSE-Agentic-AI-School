# Drone channels: parser coverage

Generated 2026-10-12 10:16 UTC from the drones.sqlite journal.

## Messages

| channel | first | last | lines | message versions | late edits (>5 min) |
|---|---|---|---|---|---|
| kpszsu | 2026-08-10 | 2026-10-12 10:06 | 15392 | 13315 | 1208 |
| kudy_letyt | 2026-08-10 | 2026-10-12 10:13 | 45757 | 8142 | 116 |
| kyiv_nebo | 2026-08-10 | 2026-10-12 09:56 | 5919 | 5885 | 10 |

## Line kinds

| line kind | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| drone_jet | 7904 | 18373 | 354 |
| drone | 2853 | 6347 | 21 |
| kab | 1544 | 189 | 0 |
| other | 1151 | 249 | 779 |
| summary | 717 | 657 | 0 |
| missile | 702 | 1106 | 84 |
| header | 261 | 17953 | 0 |
| ballistic | 176 | 198 | 66 |
| noise | 76 | 40 | 10 |
| status:shot_down | 8 | 267 | 147 |
| status:all_clear | 0 | 65 | 654 |
| status:descending | 0 | 26 | 102 |
| status:recheck | 0 | 287 | 47 |
| unknown | 0 | 0 | 3655 |

## Place resolution

| match | kpszsu | kudy_letyt | kyiv_nebo |
|---|---|---|---|
| ambiguous | 178 | 108 | 12 |
| context | 88 | 122 | 10 |
| exact | 9161 | 17563 | 3800 |
| fuzzy | 63 | 470 | 5 |
| lemma | 2554 | 7564 | 965 |
| none | 516 | 237 | 134 |
| **with coordinates** | **94.5%** | **98.7%** | **97.0%** |

`exact` — name as written; `lemma` — after inflection to the nominative; `fuzzy` — spelling variant / rapidfuzz ≥ 92 within the oblast; `context` — homonym chosen by proximity to places mentioned in the same message or the previous 30 min of the channel; `ambiguous` — several same-name places, no coordinates; `none` — not found. This is coverage, not accuracy: precision/recall come from `airalert drones-eval`.

## Top 50 unresolved place phrases

Add them to `data/gazetteer/kyiv_local.csv` (Kyiv) or tell the parser what they are.

| # | phrase | match | channel | n | oblast scope |
|---|---|---|---|---|---|
| 1 | Миколаївку | ambiguous | kudy_letyt | 21 | UA.17 |
| 2 | Калинопіль | none | kudy_letyt | 15 | UA.01 |
| 3 | Ширяєве | none | kudy_letyt | 15 | UA.17 |
| 4 | Гайдамацьке | none | kudy_letyt | 12 | UA.10 |
| 5 | Південне | ambiguous | kpszsu | 12 | nan |
| 6 | Кременчуцького водосховища | none | kpszsu | 12 | UA.18,nan |
| 7 | Просяну | ambiguous | kudy_letyt | 11 | UA.04 |
| 8 | центральної частини Києва | none | kpszsu | 11 | nan |
| 9 | зону відчуження Чорнобильської АЕС | none | kpszsu | 10 | nan |
| 10 | Поліський природний заповідник | none | kudy_letyt | 10 | UA.27 |
| 11 | Сергіївку | ambiguous | kudy_letyt | 10 | UA.17 |
| 12 | південь Одещини | none | kpszsu | 10 | nan |
| 13 | акваторії Чорного моря | none | kudy_letyt | 10 | UA.08,UA.16,nan |
| 14 | північ Київщини | none | kpszsu | 10 | UA.02,nan |
| 15 | Лавіна | none | kyiv_nebo | 10 | UA.12 |
| 16 | Мости | ambiguous | kyiv_nebo | 9 | nan |
| 17 | Дергачі/Малу Данилівку | ambiguous | kpszsu | 9 | nan |
| 18 | південь Одещини (Вилкове) | none | kpszsu | 9 | nan |
| 19 | Іванків | ambiguous | kpszsu | 9 | UA.12,nan |
| 20 | Київське водосховище | none | kpszsu | 8 | UA.02 |
| 21 | Пеньківку | ambiguous | kudy_letyt | 7 | UA.23 |
| 22 | столиці | none | kpszsu | 7 | UA.13,nan |
| 23 | півночі Чернігівщини вектором руху | none | kpszsu | 7 | nan |
| 24 | Лебедівку | ambiguous | kudy_letyt | 7 | UA.13 |
| 25 | Дмитрівку | ambiguous | kudy_letyt | 7 | UA.04,UA.16 |
| 26 | Калинівку | ambiguous | kudy_letyt | 7 | UA.12,UA.13 |
| 27 | Затоку | ambiguous | kpszsu | 7 | nan |
| 28 | захід та | none | kpszsu | 6 | UA.01,UA.02,UA.13,UA.23,UA.27,nan |
| 29 | Чорноморське | ambiguous | kpszsu | 6 | nan |
| 30 | Сергіївку/Затоку | ambiguous | kpszsu | 6 | UA.17,nan |
| 31 | Затоки | ambiguous | kpszsu | 6 | nan |
| 32 | Підлітає | none | kyiv_nebo | 6 | UA.12 |
| 33 | заході Запоріжжя | none | kpszsu | 5 | nan |
| 34 | півночі Запоріжжя | none | kpszsu | 5 | nan |
| 35 | Київщині в районах н.п. Боярка/Чабани | none | kpszsu | 5 | nan |
| 36 | Циркони | none | kyiv_nebo | 5 | UA.12 |
| 37 | Кременчуцьке водосховище | none | kpszsu | 5 | nan |
| 38 | Гоголеве | ambiguous | kudy_letyt | 5 | UA.18 |
| 39 | Самарський ліс | none | kudy_letyt | 5 | UA.04 |
| 40 | Лавіни | none | kyiv_nebo | 5 | UA.12 |
| 41 | Нароўля | none | kudy_letyt | 5 | BY |
| 42 | Південний міст | none | kudy_letyt | 5 | UA.12 |
| 43 | Козина | ambiguous | kpszsu | 5 | nan |
| 44 | Схоже | none | kyiv_nebo | 4 | UA.12 |
| 45 | територію Білорусі | none | kudy_letyt | 4 | BY,nan |
| 46 | Нові Санжари Полтавщина | none | kpszsu | 4 | nan |
| 47 | Чорноморське/Одесу | ambiguous | kpszsu | 4 | nan |
| 48 | Одещині н.п.Балта | none | kpszsu | 4 | nan |
| 49 | Мар'янівку | ambiguous | kudy_letyt | 4 | UA.27 |
| 50 | Миколаївку | ambiguous | kpszsu | 4 | UA.12,UA.17,nan |
