# Звіт якості даних — фаза 1

Згенеровано: `2026-10-12T06:41:31+00:00` · загальний статус: **WARN**

- **vadimkin_commit**: `bf0c323c78e3e4508721458797dcd38c95df13f3`
- **code_git_sha**: `8aff4ebea51af651087d840080b7ef204c8c45fa`
- **seam**: `2026-08-26T00:00:00+00:00`
- **official_outages**: `2026-08-29 04:55…2026-08-30 12:42; 2026-08-30 12:42…2026-09-02 13:48; 2026-09-07 06:09…2026-10-12 06:41`

## Зведення

| # | Область перевірки | Перевірка | Статус | Значення | Коротко |
|---|---|---|---|---|---|
| 1 | dataset_official | Схема й типи | ✅ PASS | 0 | Колонки, типи (tz-aware UTC) і допустимі level — коректні. |
| 1 | dataset_volunteer | Схема й типи | ✅ PASS | 0 | Колонки, типи (tz-aware UTC) і допустимі level — коректні. |
| 2 | dataset_official | started_at < finished_at | ⚠️ WARN | 2 | 2 закритих тривог з нульовою/від'ємною тривалістю (0.001% з 185430). |
| 2 | dataset_volunteer | started_at < finished_at | ⚠️ WARN | 6 | 6 закритих тривог з нульовою/від'ємною тривалістю (0.005% з 115989). |
| 3 | dataset_official | Точні дублікати | ⚠️ WARN | 113845 | 299275 → 185430 рядків (38.04% дублів); Київ 4141 → 2267 (45.255%). Дублі прибираємо в clean.dedup. Дублі — суцільний блок: рядки 113911…227831 повторюють перші 113911 рядків файлу (історія до 2026-01-25 13:11:52+00:00), частка збігу 0.99899. |
| 3 | dataset_volunteer | Точні дублікати | ✅ PASS | 0 | 115989 → 115989 рядків (0.0% дублів); Київ 2669 → 2669 (0.0%). Дублі прибираємо в clean.dedup. |
| 4 | dataset_official | Перекриття інтервалів однієї локації | ⚠️ WARN | 2 | Після дедупу злито 2 рядків у перекриті інтервали (Київ: 0); результат позначено прапорцем merged_overlap. |
| 4 | dataset_volunteer | Перекриття інтервалів однієї локації | ✅ PASS | 0 | Після дедупу злито 0 рядків у перекриті інтервали (Київ: 0); результат позначено прапорцем merged_overlap. |
| 5 | dataset_official | Тривалості | ⚠️ WARN | 2.617 | Рівно 3600 с (імпутація автора): 255, з них Київ 1; < 60 с: 453; > 12 год: 4144; рівно 1800 с: 38. |
| 5 | dataset_volunteer | Тривалості | ⚠️ WARN | 6.214 | naive=True (кінець домальовано як старт+30 хв): 5812 (5.011%), з них Київ 214; < 60 с: 1367; > 12 год: 28; рівно 1800 с: 5855. |
| 6 | dataset_official | Свіжість | ⚠️ WARN | 35.05 | Останній старт 2026-09-07T05:28:22+00:00, відставання 35.05 дн. Джерело застаріло: діру після цієї дати добираємо з Telegram air_alert_ua (шов C = 2026-09-01). |
| 6 | dataset_volunteer | Свіжість | ✅ PASS | 1.09 | Останній старт 2026-10-11T04:36:59+00:00, відставання 1.09 дн. |
| 7 | dataset_official | Дні без жодної тривоги по Україні | ⚠️ WARN | 3 | 3 днів (UTC) з 1638 без жодного запису. Перші: 2026-08-30, 2026-08-31, 2026-09-01 |
| 7 | dataset_volunteer | Дні без жодної тривоги по Україні | ✅ PASS | 0 | 0 днів (UTC) з 1690 без жодного запису. |
| 8 | kyiv: official vs volunteer | Перехресна згода по Києву | ⚠️ WARN | 75.6 | Вікно 2022-03-15…2026-09-05: збіг стартів ±2 хв 75.6%; сумарні години official 2625.2 vs volunteer 2036.9 (розрив 22.41%). Якщо зіставити за КІНЦЕМ (±2 хв, 94.0% тривог), волонтерський старт пізніший за офіційний більш ніж на 2 хв у 23.7% пар — розрив годин пояснюється запізнілими стартами eTryvoga, а не офіційним джерелом. |
| 9 | telegram: air_alert_ua vs dataset | Парсер vs датасет на перекритті (±1 хв, ціль ≥ 95%) | ✅ PASS | 100.0 | 100.0% з 1005 інтервалів датасету (Kyiv City, Kyivska oblast, Zhytomyrska oblast, Chernihivska oblast, Cherkaska oblast, Poltavska oblast) знайдено в Telegram зі стартом і кінцем ±1 хв; з урахуванням 10 інтервалів, що зачіпають збій каналу, — 99.015%. Київ, єТривога vs air_alert_ua: 92.157% збігів ±1 хв, медіанне запізнення старту єТривоги 11 с. |
| 10 | telegram | parse_errors (нерозпізнані < 1%) | ✅ PASS | 0.006 | air_alert_ua: нерозпізнаних 0.0% з 7207, причини {'end_without_start': 113}; UkraineAlarmSignal: нерозпізнаних 0.006% з 53623, причини {'truncated_place_list': 3, 'end_without_start': 67}. end_without_start — відбої тривог, що почались до початку вибірки або під час збою каналу. |
| 11 | telegram | Ідемпотентність backfill і детермінізм rebuild | ✅ PASS | 0 | Повторна вставка 60830 повідомлень додала 0 рядків (60830 → 60830); два rebuild поспіль дають однакові alerts. |
| 12 | telegram | Live-затримка received_at − posted_at | ⚠️ WARN | 94.19999999999982 | 566 live-повідомлень; медіана 7.0 с, p95 2442.2 с (усталений режим ≤ 5 хв: p95 94.19999999999982 с; довші — дочитування після простою). |
| 13 | build | Шви між джерелами: немає дублів | ✅ PASS | 0 | Перекриттів між інтервалами різних джерел однієї локації: 0 (в межах одного джерела: 0). Біля шва 2026-08-26T00:00:00+00:00 у Києві 1 тривог: dataset_official 2026-08-25 20:54:26+00:00. |

## Деталі

### 1. Схема й типи — dataset_official (PASS)

Колонки, типи (tz-aware UTC) і допустимі level — коректні.

### 1. Схема й типи — dataset_volunteer (PASS)

Колонки, типи (tz-aware UTC) і допустимі level — коректні.

### 2. started_at < finished_at — dataset_official (WARN)

2 закритих тривог з нульовою/від'ємною тривалістю (0.001% з 185430).

```json
{
  "share_pct": 0.001,
  "examples": [
    {
      "location": "Odeska oblast",
      "level": "raion",
      "raion": "Podilskyi raion",
      "started_at": "2025-11-14 20:17:15+00:00",
      "finished_at": "2025-11-14 20:17:15+00:00"
    },
    {
      "location": "Kharkivska oblast",
      "level": "raion",
      "raion": "Bohodukhivskyi raion",
      "started_at": "2025-11-17 01:13:53+00:00",
      "finished_at": "2025-11-17 01:13:53+00:00"
    }
  ]
}
```

### 2. started_at < finished_at — dataset_volunteer (WARN)

6 закритих тривог з нульовою/від'ємною тривалістю (0.005% з 115989).

```json
{
  "share_pct": 0.005,
  "examples": [
    {
      "location": "Dnipropetrovska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2025-11-03 22:27:41+00:00",
      "finished_at": "2025-11-03 22:27:41+00:00"
    },
    {
      "location": "Dnipropetrovska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-01-15 22:14:22+00:00",
      "finished_at": "2026-01-15 22:14:22+00:00"
    },
    {
      "location": "Dnipropetrovska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-03-11 22:43:16+00:00",
      "finished_at": "2026-03-11 22:43:16+00:00"
    },
    {
      "location": "Dnipropetrovska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-03-12 12:08:51+00:00",
      "finished_at": "2026-03-12 12:08:51+00:00"
    },
    {
      "location": "Kirovohradska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-03-28 19:28:39+00:00",
      "finished_at": "2026-03-28 19:28:39+00:00"
    },
    {
      "location": "Kyivska oblast",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-09-16 01:12:16+00:00",
      "finished_at": "2026-09-16 01:12:16+00:00"
    }
  ]
}
```

### 3. Точні дублікати — dataset_official (WARN)

299275 → 185430 рядків (38.04% дублів); Київ 4141 → 2267 (45.255%). Дублі прибираємо в clean.dedup. Дублі — суцільний блок: рядки 113911…227831 повторюють перші 113911 рядків файлу (історія до 2026-01-25 13:11:52+00:00), частка збігу 0.99899.

```json
{
  "rows": 299275,
  "rows_after_dedup": 185430,
  "kyiv_rows": 4141,
  "kyiv_rows_after_dedup": 2267,
  "kyiv_duplicate_share_pct": 45.255,
  "layout": {
    "first_duplicate_row": 113911,
    "last_duplicate_row": 227831,
    "prefix_rows": 113911,
    "prefix_last_started_at": "2026-01-25 13:11:52+00:00",
    "rows_after_prefix_equal_to_prefix_share": 0.99899,
    "duplicate_rows_by_year": {
      "2022": 17493,
      "2023": 17362,
      "2024": 26135,
      "2025": 45901,
      "2026": 6954
    }
  }
}
```

### 3. Точні дублікати — dataset_volunteer (PASS)

115989 → 115989 рядків (0.0% дублів); Київ 2669 → 2669 (0.0%). Дублі прибираємо в clean.dedup.

```json
{
  "rows": 115989,
  "rows_after_dedup": 115989,
  "kyiv_rows": 2669,
  "kyiv_rows_after_dedup": 2669,
  "kyiv_duplicate_share_pct": 0.0,
  "layout": {}
}
```

### 4. Перекриття інтервалів однієї локації — dataset_official (WARN)

Після дедупу злито 2 рядків у перекриті інтервали (Київ: 0); результат позначено прапорцем merged_overlap.

```json
{
  "rows_before_merge": 185430,
  "rows_after_merge": 185428,
  "kyiv_rows_merged_away": 0,
  "merged_intervals": 2
}
```

### 4. Перекриття інтервалів однієї локації — dataset_volunteer (PASS)

Після дедупу злито 0 рядків у перекриті інтервали (Київ: 0); результат позначено прапорцем merged_overlap.

```json
{
  "rows_before_merge": 115989,
  "rows_after_merge": 115989,
  "kyiv_rows_merged_away": 0,
  "merged_intervals": 0
}
```

### 5. Тривалості — dataset_official (WARN)

Рівно 3600 с (імпутація автора): 255, з них Київ 1; < 60 с: 453; > 12 год: 4144; рівно 1800 с: 38.

```json
{
  "lt_60s": 453,
  "gt_12h": 4144,
  "eq_3600s": 255,
  "eq_1800s": 38,
  "kyiv_lt_60s": 6,
  "kyiv_gt_12h": 0,
  "kyiv_eq_3600s": 1,
  "kyiv_eq_1800s": 0,
  "rows": 185430,
  "median_minutes": 48.9,
  "p99_hours": 18.83,
  "suspicious_share_pct": 2.617
}
```

### 5. Тривалості — dataset_volunteer (WARN)

naive=True (кінець домальовано як старт+30 хв): 5812 (5.011%), з них Київ 214; < 60 с: 1367; > 12 год: 28; рівно 1800 с: 5855.

```json
{
  "lt_60s": 1367,
  "gt_12h": 28,
  "eq_3600s": 10,
  "eq_1800s": 5855,
  "kyiv_lt_60s": 9,
  "kyiv_gt_12h": 1,
  "kyiv_eq_3600s": 0,
  "kyiv_eq_1800s": 215,
  "rows": 115989,
  "median_minutes": 30.0,
  "p99_hours": 4.44,
  "naive_true": 5812,
  "kyiv_naive_true": 214,
  "suspicious_share_pct": 6.214
}
```

### 6. Свіжість — dataset_official (WARN)

Останній старт 2026-09-07T05:28:22+00:00, відставання 35.05 дн. Джерело застаріло: діру після цієї дати добираємо з Telegram air_alert_ua (шов C = 2026-09-01).

```json
{
  "max_started_at": "2026-09-07T05:28:22+00:00",
  "now": "2026-10-12T06:41:27.219760+00:00",
  "lag_days": 35.05
}
```

### 6. Свіжість — dataset_volunteer (PASS)

Останній старт 2026-10-11T04:36:59+00:00, відставання 1.09 дн.

```json
{
  "max_started_at": "2026-10-11T04:36:59+00:00",
  "now": "2026-10-12T06:41:27.219760+00:00",
  "lag_days": 1.09
}
```

### 7. Дні без жодної тривоги по Україні — dataset_official (WARN)

3 днів (UTC) з 1638 без жодного запису. Перші: 2026-08-30, 2026-08-31, 2026-09-01

Дні без записів (3): 2026-08-30, 2026-08-31, 2026-09-01

```json
{
  "range": [
    "2022-03-15",
    "2026-09-07"
  ]
}
```

### 7. Дні без жодної тривоги по Україні — dataset_volunteer (PASS)

0 днів (UTC) з 1690 без жодного запису.

```json
{
  "missing_days": [],
  "range": [
    "2022-02-25",
    "2026-10-11"
  ]
}
```

### 8. Перехресна згода по Києву — kyiv: official vs volunteer (WARN)

Вікно 2022-03-15…2026-09-05: збіг стартів ±2 хв 75.6%; сумарні години official 2625.2 vs volunteer 2036.9 (розрив 22.41%). Якщо зіставити за КІНЦЕМ (±2 хв, 94.0% тривог), волонтерський старт пізніший за офіційний більш ніж на 2 хв у 23.7% пар — розрив годин пояснюється запізнілими стартами eTryvoga, а не офіційним джерелом.

**По роках (Київ):**

| period | n_official | n_volunteer | hours_official | hours_volunteer | median_min_official | median_min_volunteer | start_match_pct | hours_diff |
|---|---|---|---|---|---|---|---|---|
| 2022 | 505 | 507 | 540.8 | 543.7 | 48.9 | 48.5 | 97.2 | -2.9 |
| 2023 | 301 | 304 | 397.1 | 398.6 | 55.0 | 55.0 | 93.4 | -1.5 |
| 2024 | 502 | 524 | 542.1 | 387.6 | 34.0 | 31.6 | 73.3 | 154.5 |
| 2025 | 511 | 539 | 740.4 | 419.5 | 35.1 | 30.0 | 63.2 | 320.9 |
| 2026 | 448 | 533 | 404.9 | 287.5 | 29.9 | 28.0 | 55.8 | 117.4 |

**Топ-10 місяців за розбіжністю сумарних годин:**

| period | n_official | n_volunteer | hours_official | hours_volunteer | median_min_official | median_min_volunteer | start_match_pct | hours_diff |
|---|---|---|---|---|---|---|---|---|
| 2025-02 | 43 | 44 | 124.2 | 63.5 | 188.0 | 55.8 | 41.9 | 60.7 |
| 2024-11 | 63 | 72 | 116.4 | 62.1 | 50.6 | 34.4 | 57.1 | 54.3 |
| 2025-07 | 49 | 50 | 77.4 | 35.7 | 27.7 | 24.7 | 63.3 | 41.7 |
| 2025-09 | 46 | 50 | 63.6 | 28.0 | 37.9 | 30.0 | 58.7 | 35.6 |
| 2026-08 | 90 | 97 | 78.2 | 43.5 | 31.2 | 19.0 | 42.2 | 34.7 |
| 2025-06 | 34 | 36 | 62.0 | 27.6 | 33.5 | 30.9 | 61.8 | 34.4 |
| 2025-05 | 38 | 39 | 62.1 | 30.3 | 31.7 | 30.4 | 65.8 | 31.8 |
| 2024-10 | 54 | 58 | 79.7 | 52.0 | 60.4 | 39.3 | 61.1 | 27.7 |
| 2026-01 | 58 | 68 | 58.4 | 36.4 | 33.1 | 25.3 | 56.9 | 22.0 |
| 2025-03 | 35 | 38 | 65.5 | 43.9 | 87.7 | 62.9 | 51.4 | 21.6 |

**Зіставлення за кінцем тривоги: запізнення волонтерського старту (хв), по роках:**

| year | pairs | vol_start_later_gt2min_pct | lag_min_p75 | lag_min_p90 |
|---|---|---|---|---|
| 2022 | 473 | 2.7 | 0.5 | 0.9 |
| 2023 | 278 | 6.1 | 0.6 | 1.4 |
| 2024 | 478 | 27.4 | 2.9 | 69.7 |
| 2025 | 504 | 37.1 | 12.7 | 142.0 |
| 2026 | 399 | 39.3 | 13.5 | 70.8 |

Повна помісячна таблиця — у `data_quality.json`.

```json
{
  "window": [
    "2022-03-15T16:19:20+00:00",
    "2026-09-05T23:22:48+00:00"
  ],
  "tolerance": "2min",
  "overall_start_match_pct": 75.6,
  "total_hours_official": 2625.2,
  "total_hours_volunteer": 2036.9,
  "end_pairing": {
    "end_match_pct": 94.0,
    "volunteer_start_later_than_2min_pct": 23.7,
    "volunteer_start_lag_min_median": 0.33
  },
  "hours_gap_pct": 22.41
}
```

### 9. Парсер vs датасет на перекритті (±1 хв, ціль ≥ 95%) — telegram: air_alert_ua vs dataset (PASS)

100.0% з 1005 інтервалів датасету (Kyiv City, Kyivska oblast, Zhytomyrska oblast, Chernihivska oblast, Cherkaska oblast, Poltavska oblast) знайдено в Telegram зі стартом і кінцем ±1 хв; з урахуванням 10 інтервалів, що зачіпають збій каналу, — 99.015%. Київ, єТривога vs air_alert_ua: 92.157% збігів ±1 хв, медіанне запізнення старту єТривоги 11 с.

```json
{
  "window": [
    "2026-08-25T06:00:00+00:00",
    "2026-09-07T06:00:00+00:00"
  ],
  "rate_excluding_outage_pct": 100.0,
  "rate_all_pct": 99.015,
  "dataset_intervals": 1015,
  "touching_outage": 10,
  "by_location": {
    "Kyiv City": "51/51",
    "Kyivska oblast": "312/312",
    "Zhytomyrska oblast": "50/50",
    "Chernihivska oblast": "224/224",
    "Cherkaska oblast": "163/163",
    "Poltavska oblast": "205/205"
  },
  "misses": [
    {
      "location": "Chernihivska oblast",
      "level": "raion",
      "raion": "Chernihivskyi raion",
      "started_at": "2026-08-29 04:27:26+00:00",
      "finished_at": "2026-09-02 16:41:59+00:00",
      "flags": "",
      "touches_outage": "True"
    },
    {
      "location": "Chernihivska oblast",
      "level": "raion",
      "raion": "Nizhynskyi raion",
      "started_at": "2026-08-29 04:33:34+00:00",
      "finished_at": "2026-08-29 05:33:34+00:00",
      "flags": "end_imputed",
      "touches_outage": "True"
    },
    {
      "location": "Kyiv City",
      "level": "oblast",
      "raion": "",
      "started_at": "2026-08-29 04:29:09+00:00",
      "finished_at": "2026-08-29 05:29:09+00:00",
      "flags": "end_imputed",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Boryspilskyi raion",
      "started_at": "2026-08-29 00:43:11+00:00",
      "finished_at": "2026-09-02 16:42:16+00:00",
      "flags": "",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Brovarskyi raion",
      "started_at": "2026-08-29 00:30:05+00:00",
      "finished_at": "2026-09-02 16:42:22+00:00",
      "flags": "",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Buchanskyi raion",
      "started_at": "2026-08-29 04:29:53+00:00",
      "finished_at": "2026-08-29 05:29:53+00:00",
      "flags": "end_imputed",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Fastivskyi raion",
      "started_at": "2026-08-29 00:49:10+00:00",
      "finished_at": "2026-09-02 16:42:11+00:00",
      "flags": "",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Obukhivskyi raion",
      "started_at": "2026-08-29 00:49:03+00:00",
      "finished_at": "2026-09-02 16:42:05+00:00",
      "flags": "",
      "touches_outage": "True"
    },
    {
      "location": "Kyivska oblast",
      "level": "raion",
      "raion": "Vyshhorodskyi raion",
      "started_at": "2026-08-29 04:29:42+00:00",
      "finished_at": "2026-08-29 05:29:42+00:00",
      "flags": "end_imputed",
      "touches_outage": "True"
    },
    {
      "location": "Poltavska oblast",
      "level": "raion",
      "raion": "Poltavskyi raion",
      "started_at": "2026-08-29 04:55:28+00:00",
      "finished_at": "2026-08-29 05:55:28+00:00",
      "flags": "end_imputed",
      "touches_outage": "True"
    }
  ],
  "kyiv_volunteer_vs_official": {
    "official_intervals": 51,
    "matched_pct": 92.157,
    "volunteer_start_lag_s_median": 11.0,
    "volunteer_start_lag_s_p95": 19.3
  }
}
```

### 10. parse_errors (нерозпізнані < 1%) — telegram (PASS)

air_alert_ua: нерозпізнаних 0.0% з 7207, причини {'end_without_start': 113}; UkraineAlarmSignal: нерозпізнаних 0.006% з 53623, причини {'truncated_place_list': 3, 'end_without_start': 67}. end_without_start — відбої тривог, що почались до початку вибірки або під час збою каналу.

```json
{
  "air_alert_ua": {
    "messages": 7207,
    "messages_unrecognised": 0,
    "unrecognised_pct": 0.0,
    "errors_by_reason": {
      "end_without_start": 113
    },
    "top_reasons": [
      {
        "reason": "end_without_start",
        "n": 113
      }
    ]
  },
  "UkraineAlarmSignal": {
    "messages": 53623,
    "messages_unrecognised": 3,
    "unrecognised_pct": 0.006,
    "errors_by_reason": {
      "truncated_place_list": 3,
      "end_without_start": 67
    },
    "top_reasons": [
      {
        "reason": "end_without_start",
        "n": 67
      },
      {
        "reason": "truncated_place_list",
        "n": 3
      }
    ]
  }
}
```

### 11. Ідемпотентність backfill і детермінізм rebuild — telegram (PASS)

Повторна вставка 60830 повідомлень додала 0 рядків (60830 → 60830); два rebuild поспіль дають однакові alerts.

```json
{
  "raw_before": 60830,
  "raw_after": 60830,
  "reinserted": 60830,
  "rebuild_identical": true
}
```

### 12. Live-затримка received_at − posted_at — telegram (WARN)

566 live-повідомлень; медіана 7.0 с, p95 2442.2 с (усталений режим ≤ 5 хв: p95 94.19999999999982 с; довші — дочитування після простою).

```json
{
  "messages": 566,
  "all": {
    "median_s": 7.0,
    "p95_s": 2442.25,
    "max_s": 4153.0
  },
  "steady_state_le_5min": {
    "messages": 460,
    "median_s": 4.0,
    "p95_s": 94.19999999999982
  },
  "by_channel": {
    "UkraineAlarmSignal": {
      "messages": 566,
      "median_s": 7.0,
      "p95_s": 2442.25
    }
  }
}
```

### 13. Шви між джерелами: немає дублів — build (PASS)

Перекриттів між інтервалами різних джерел однієї локації: 0 (в межах одного джерела: 0). Біля шва 2026-08-26T00:00:00+00:00 у Києві 1 тривог: dataset_official 2026-08-25 20:54:26+00:00.

```json
{
  "cross_source_overlaps": 0,
  "same_source_overlaps": 0,
  "examples": [],
  "kyiv_near_seam": [
    {
      "source": "dataset_official",
      "started_at": "2026-08-25 20:54:26+00:00",
      "finished_at": "2026-08-25 21:41:42+00:00"
    }
  ]
}
```

