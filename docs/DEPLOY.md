# Розгортання на Proxmox

## Що створити

**VM** (Debian 12 або Ubuntu 24.04) з Docker Engine + compose plugin: 2 vCPU, 2–4 ГБ RAM, 10 ГБ диска.

LXC — лише якщо дуже треба: контейнер з `features: nesting=1,keyctl=1`. Docker у LXC працює поверх overlayfs/ZFS
і ламається після оновлень ядра/Proxmox; для сервісу, який має жити тижнями без нагляду, беремо VM.

## Перший запуск

```bash
# на сервері
sudo apt install -y docker.io docker-compose-plugin make rsync curl git
curl -LsSf https://astral.sh/uv/install.sh | sh        # для make model / model-fallback на хості
sudo mkdir -p /opt/airalert && sudo chown "$USER" /opt/airalert

# з ноутбука
make deploy HOST=user@server DIR=/opt/airalert          # rsync коду + ssh "make up"
```

Образ збирається **на сервері** (`make up` → `docker compose up --build`), тож архітектура — рідна (amd64);
у compose платформа не закріплена. Збірку під `linux/amd64` перевірено локально через
`docker buildx build --platform linux/amd64 -f docker/collector.Dockerfile .`.

Вручну, один раз, **поза git і поза rsync**:

| що | куди | права |
|---|---|---|
| `.env` (TG_API_ID, TG_API_HASH, SITREP_CONTACT…) | `/opt/airalert/.env` | 600 |
| файл сесії Telegram (`make login` на ноутбуці або на сервері) | `~/.config/airalert/airalert.session` | 600, каталог 700 |
| опційно: історія `data/live/` з ноутбука (щоб не втрачати журнал) | `/opt/airalert/data/live/` | власник — користувач, від якого `make up` |

Сесію не тримайте в обох місцях одночасно: один акаунт — один живий колектор.

Без моделі в `data/processed` `make up` спершу робить `make model-fallback` (модель на закомічених даних), далі її
замінить нічне перенавчання. Для нічного перенавчання на сервері потрібен `data/raw/vadimkin` — `make model` докачає
його (`airalert fetch-dataset`).

## HTTPS (потрібен для геолокації в браузері)

API слухає **лише `127.0.0.1:8000`**. **Порти на роутері не відкриваємо.** Назовні — тунель з хоста:

- Tailscale Funnel: `sudo tailscale funnel --bg 8000` → `https://<host>.<tailnet>.ts.net`;
- або Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8000` (або іменований тунель з DNS).

## Бекапи

```cron
# crontab -e (користувач, від якого make up)
30 3 * * *  cd /opt/airalert && make snapshot >> data/work/backup.log 2>&1
```

`make snapshot` робить консистентні копії `alerts`, `drones`, `sitrep` **усередині колектора** (SQLite online backup)
у `data/work/backup/<дата>/` і видаляє каталоги, старші за 7 днів. Копіюйте `data/work/backup/` ще кудись
(Proxmox Backup Server знімає всю VM — теж годиться).

## Оновлення

```bash
make deploy HOST=user@server DIR=/opt/airalert
```

rsync не чіпає `data/live`, `data/work`, `data/raw`, `.env`, `*.session` і нічну модель; `make up` перезбирає образ і
перезапускає сервіси, журнали лишаються.

## Моніторинг

```bash
curl -s http://127.0.0.1:8000/api/health   # code_sha, model_updated_at, sources.{alerts,drones,sitrep}.{data_as_of,ok}
make ps                                      # healthy: collector (heartbeat ≤ 5 хв), sitrep, api
make logs
```

Тривожні ознаки: `sources.alerts.ok = false` довше 10 хв (колектор відстав або сесія злетіла — `make logs`),
`model_updated_at` старше 2 діб (нічне перенавчання падає — дивись логи `nightly`).
