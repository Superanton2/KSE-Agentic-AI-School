# Розгортання на Proxmox

Коротко: створити VM → поставити Docker → з ноутбука `make migrate HOST=…` → увімкнути тунель і `make cron`.
Далі воно працює саме: колектор пише журнали й сам оновлює таблицю тривог, `nightly` о 04:00 перенавчає модель,
API підхоплює нову модель без перезапуску, логи обмежені (3 × 10 МБ на контейнер), бекап — щоночі.

## 1. VM

**VM** на Debian 12 або Ubuntu 24.04: 2 vCPU, 2–4 ГБ RAM, 10 ГБ диска. LXC — лише якщо дуже треба, з
`features: nesting=1,keyctl=1`; Docker у LXC поверх overlayfs/ZFS ламається після оновлень Proxmox, тож для сервісу
без нагляду беремо VM. В опціях VM: *Start at boot = Yes*.

```bash
# на сервері, один раз
sudo apt update && sudo apt install -y docker.io docker-compose-v2 make git curl rsync   # Debian 12: docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"            # перелогінитись після цього
sudo mkdir -p /opt/airalert && sudo chown "$USER" /opt/airalert
```

Python, uv і node на сервері **не потрібні**: усе, що рахує, запускається в образі. Образ збирається на сервері
(`make up` → `docker compose up --build`), тож архітектура рідна; збірку під `linux/amd64` перевірено через buildx.

## 2. Перенесення з ноутбука

Один акаунт Telegram — **один** живий колектор. `make migrate` зупиняє стек на ноутбуці й переносить усе потрібне:

```bash
# на ноутбуці, з кореня репозиторію
make migrate HOST=user@server DIR=/opt/airalert
```

Що робить: `docker compose stop` тут → rsync `data/live/` (журнали з історією; без `snapshots/`) → `.env` (600) →
сесія Telegram у `~/.config/airalert/airalert.session` на сервері (каталог 700, файл 600) → `make deploy`
(rsync коду + `make up` на сервері). `make up` сам докачує датасет Vadimkin (`make dataset`), якщо треба — робить
запасну модель на закомічених даних, піднімає `collector`, `sitrep`, `api`, `nightly` і чекає `/api/health`.
Без навченої моделі `nightly` одразу (не чекаючи 04:00) навчає її на перенесених журналах.

Після цього **не запускайте колектор на ноутбуці** (`make down` там безпечний).

Без перенесення (новий акаунт, порожній `data/live`): скопіюйте `.env`, зробіть `make login` на сервері й `make up`.
Колектор сам завантажить історію каналів тривог з `TG_ALERTS_SINCE` (2026-08-25) і дронів з `TG_DRONE_SINCE`
(це хвилини–десятки хвилин); поки історії немає, сайт показує «Немає свіжих даних», а `nightly` відмовляється
навчатись на неповному журналі й лишає попередню модель.

## 3. HTTPS (потрібен для геолокації в браузері)

API слухає **лише `127.0.0.1:8000`**. **Порти на роутері не відкриваємо.** Назовні — тунель з хоста:

- Tailscale Funnel: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up && sudo tailscale funnel --bg 8000`
  → `https://<host>.<tailnet>.ts.net` (переживає перезавантаження);
- або Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8000` (швидко) або іменований тунель як сервіс.

## 4. Бекапи

```bash
cd /opt/airalert && make cron     # 03:30 щоночі: make snapshot → data/work/backup/<дата>/, зберігає 7 днів
```

`make snapshot` робить консистентні копії `alerts`, `drones`, `sitrep` **усередині колектора** (SQLite online backup).
Повну VM знімайте ще й Proxmox Backup / vzdump.

## Оновлення коду

```bash
make deploy HOST=user@server DIR=/opt/airalert     # з ноутбука
```

rsync не чіпає `data/live`, `data/work`, `data/raw`, `.env`, сесії й файли нічної моделі (`model_final.pkl`,
`model_card.json`, `model_grid.parquet` копіюються лише якщо їх ще немає); коміт записується в `.code_sha` →
`/api/health.code_sha`. `make up` перезбирає образ і перезапускає сервіси; журнали лишаються.

## Моніторинг

```bash
make health     # /api/health: code_sha, model_updated_at, sources.{alerts,drones,sitrep}.{data_as_of,ok}
make ps         # healthy: collector (heartbeat ≤ 5 хв), sitrep, api
make logs
```

Тривожні ознаки: `sources.alerts.ok = false` довше 10 хв (колектор відстав або сесія злетіла — `make logs`, за
потреби `make login` і `make up`); `model_updated_at` старше 2 діб (нічне перенавчання падає — `docker compose logs nightly`).

Чек-лист після переїзду: `make health` → `status` `calm`/`alert`, `sources.alerts.ok = true`, `sitrep.ok = true`;
сайт через тунель відкривається з телефона, геолокація працює.
