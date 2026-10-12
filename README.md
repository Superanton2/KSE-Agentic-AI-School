# KSE-Agentic-AI-School

Прогноз повітряних тривог у **Києві** («Чи встигну закупитись у Metro до тривоги»).
Фаза 1 — збір і перевірка даних: `src/airalert`, звіт якості — [`reports/data_quality.md`](reports/data_quality.md).

## Дані

### Джерела

| Джерело | Що це | Період у фінальному наборі |
|---|---|---|
| `dataset_official` | [Vadimkin/ukrainian-air-raid-sirens-dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset) (MIT), `official_data_en.csv`, після дедупу | 2022-03-15 … 2026-08-26 |
| `tg_official` | Telegram [@air_alert_ua](https://t.me/air_alert_ua) («Повітряна Тривога»), наш парсер | 2026-08-26 … 2026-09-07, крім збою 08-29…09-02 |
| `tg_volunteer` | Telegram [@UkraineAlarmSignal](https://t.me/UkraineAlarmSignal) (єТривога), наш парсер | збій 08-29…09-02 і з 2026-09-07 06:09 UTC до зараз |
| `dataset_volunteer` | `volunteer_data_en.csv` того ж репо | тільки для перехресної перевірки (№8) |

Шов датасет → Telegram: `2026-08-26T00:00Z` (за `started_at`). Перемикання між Telegram-джерелами — за вікнами
мовчання офіційного каналу (> 6 год), вони записані в `data/processed/manifest.json`.

### Знайдені проблеми

1. **Офіційний CSV містить історію двічі.** Перші 113 911 рядків (до 2026-01-25) дописані у файл ще раз одним
   блоком: 299 275 → 185 430 рядків після `drop_duplicates()`, Київ 4141 → 2267.
2. **Офіційний CSV застарів, бо помер сам канал.** 2026-08-30 `air_alert_ua` оголосив, що «з технічних причин
   тимчасово не працює публікація повідомлень» (рекомендують API api.ukrainealarm.com); 08-31…09-01 — жодного
   повідомлення, після 2026-09-07 06:09 UTC — тиша. Тому і датасет закінчується 2026-09-07.
3. **Прихована імпутація автора.** Незакрита тривога закривається як `start + 1h` (255 рядків рівно по 3600 с —
   прапорець `end_imputed`), а повторний старт < 3 год затирає попередній. Під час збою 08-29…09-02 це дало
   4-денні «тривоги» в датасеті.
4. **Парсер автора не відрізняє загрози від тривог.** У `air_alert_ua` є «🔴🔴 Загроза ударних БпЛА/КАБ/балістики»,
   «🟠 УВАГА!!! …», «Загроза артобстрілу», «вуличні бої», «радіаційна небезпека» — автор рахує 🔴 як старт
   тривоги, а «Відбій загрози …» як її кінець. Наш парсер розрізняє `alert_type`.
5. **Волонтерський CSV занижує тривалість** через пізні старти (2025: у 37% тривог Києва старт пізніший за
   офіційний > 2 хв, години 740 vs 419). Причина — парсер автора за ключовими словами: **наш** парсер того самого
   каналу збігається з офіційним до ~10–15 с (перевірка №9, деталі у звіті).
6. **єТривога змінила формат:** з 2026-09-06 замість 🚨 — рівні «🟡 Жовтий» / «🔴 Червоний рівень тривоги»;
   з 2026-09-25 списки місць мають маркери «• »; райони, перейменовані 2024 р. (Берестинський, Володимирський,
   Шептицький), мапляться на назви датасету (Krasnohradskyi …).
7. Дрібне: 2 нульові/від'ємні тривалості (official), 6 (volunteer); 3 дні без записів (08-30…09-01 — збій каналу).

### Політика чистки

- Точні дублікати видаляються; перекриття однієї локації зливаються (прапорець `merged_overlap`).
- **Нічого не домальовуємо.** Незакрита тривога = `finished_at IS NULL`. Інтервали, які обірвав збій джерела,
  лишаються без кінця з прапорцем `source_gap` і у фінальний набір не потрапляють — замість них береться копія
  з іншого каналу з реальним кінцем.
- Аномалії — прапорцями, не перезаписом: `dup_start` (повторний старт без відбою), `open_over_24h`,
  `end_imputed` / `naive_end` (імпутація в датасетах), `closed_by_air_raid_end` (загрозу закрив загальний відбій).
  Нерозпізнані повідомлення й невідомі місця → таблиця `parse_errors`.
- **Без витоку:** кожен рядок має `start_known_at` / `end_known_at` — коли ми про подію дізналися. Для історії
  (датасет, backfill) це час публікації, для live — `received_at`. Тексти повідомлень зберігаються такими, як
  ми їх побачили вперше; редагування — окремо в `message_edits`.

### `data/processed/alerts.parquet`

`granularity` (`raw` — інтервали як є; `oblast_union` — «тривога десь в області», union усіх рівнів, тільки
повітряні тривоги), `location` (`Kyiv City`, `Kyivska oblast`, …), `level`, `raion`, `hromada`, `alert_type`
(`air_raid`, `air_raid_red`, `drones`, `kab`, `ballistic`, `missile`, `artillery`, `street_fight`, `radiation`,
`threat_other`), `started_at`, `finished_at`, `start_known_at`, `end_known_at` (UTC), `source`, `flags`,
`start_msg_id`, `end_msg_id`. Поруч — `manifest.json` (коміти, вікна збоїв, кількості рядків).

## Як запустити фазу 1

```bash
uv sync                                   # Python 3.12
uv run airalert fetch-dataset             # clone Vadimkin у data/raw/
uv run airalert validate-dataset          # перевірки 1–8 → reports/data_quality.{md,json}
uv run pytest && uv run ruff check .      # офлайн-тести
```

Telegram (потрібні `TG_API_ID`/`TG_API_HASH` з my.telegram.org у `.env`, див. `.env.example`):

```bash
uv run airalert tg-login                  # ІНТЕРАКТИВНО, людина; QR-код (або --method code)
uv run airalert tg-backfill --since 2026-08-25 --channel air_alert_ua
uv run airalert tg-backfill --since 2026-08-25 --channel UkraineAlarmSignal
uv run airalert rebuild-alerts --channel UkraineAlarmSignal   # raw_messages → alerts (детерміновано)
uv run airalert build                     # alerts.parquet + manifest + повний звіт (перевірки 1–13)
```

Сесія Telethon дає повний доступ до акаунта: вона лежить **поза репозиторієм** (`~/.config/airalert/`, права
600), `*.session` і `.env` — у `.gitignore`. Колектор лише читає публічні канали: нічого не надсилає й ні до чого
не приєднується. Оновлення в реальному часі Telegram надсилає тільки для каналів, на які акаунт підписаний;
для решти колектор опитує канал кожні 15 с.

### Живий колектор у Docker

```bash
export AIRALERT_UID=$(id -u) AIRALERT_GID=$(id -g)
docker compose up -d --build collector    # tg-live: дочитує пропущене з max(msg_id), потім слухає
docker compose ps                         # healthy = heartbeat свіжіший за 5 хв
AIRALERT_CODE_SHA=$(git rev-parse HEAD) docker compose run --rm tools build
```

Не-root, `read_only` + `tmpfs /tmp`, жодних портів, `cap_drop: ALL`, `restart: unless-stopped`; змонтовані лише
`data/live` і каталог сесії. Поки колектор працює, не запускайте Telegram-команди на хості з тією ж сесією, а
команди, що читають `data/live/alerts.sqlite`, запускайте через `docker compose run --rm tools …` (SQLite у
Docker Desktop на macOS не можна безпечно ділити між хостом і контейнером).

## Фаза 4: модель, оцінка, API

Результати — `reports/model_eval.md` (аблація дронів, BSS з CI, калібрування, KM, продуктовий бектест) і
`data/processed/model_card.json`. Коротко: дрон-ознаки на тесті 09-13…10-11 не дали значущого виграшу, у продукті
M1a (історія тривог + час).

```bash
docker compose exec collector airalert db-snapshot --db alerts   # знімок для офлайн-кроків
uv run airalert model-features      # сітка 5 хв + мітки + ознаки, тест на витік -> reports/model_lift.md
uv run airalert model-eval          # C на 08-24…09-12, walk-forward на тесті, KM, бектест -> reports/model_eval.md
uv run airalert model-fit --no-rebuild   # фінальний ансамбль (5 bootstrap-рефітів) + model_card.json
uv run airalert serve               # http://127.0.0.1:8000 (потрібен web/ з фронтенду)
```

У Docker: `docker compose --profile serve up -d api nightly`. `api` слухає лише `127.0.0.1:8000`, `nightly`
перенавчає модель о 04:00 за Києвом; API підхоплює нові файли без перезапуску. Обидва сервіси монтують
`data/live` **лише для читання**: так вони фізично не можуть зачепити WAL колектора.

API (усі часи ISO 8601 UTC; `Cache-Control: no-store`, крім model-card):
- `GET /api/state` — `{status, level, since, data_as_of, sources_ok}`; `level` береться з SITREP, якщо той свіжий,
  інакше з `air_raid_red` волонтерського каналу.
- `GET /api/scenarios` — 5 членів × 200 сценаріїв на 120 хв, оновлення кожні 30 с, ETag.
- `GET /api/estimate?travel=&depart_in=&shop_mean=&shop_sd=&wait_max=&open_delay=` — готова ймовірність встигнути
  (`{p, band, wait, curve, best, share_beyond, unsure, skill_bucket, …}`). Сюди надходять лише хвилини, без
  координат; query string не логується.
- `GET /api/model-card`, а на `/` — статика фронтенду.

Атрибуція: `states.json` і логіка хештегів — з репозиторію Vadimkin (MIT, `LICENSES/vadimkin-MIT.txt`).
