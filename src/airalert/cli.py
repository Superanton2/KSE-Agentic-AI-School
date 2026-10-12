"""Command-line entry point: ``airalert <command>``."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import typer

from airalert import dataset, report, validate
from airalert.config import HEARTBEAT_MAX_AGE_SECONDS, LIVE_CHANNELS, OFFICIAL_CHANNEL, get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("airalert")


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Telethon logs request internals at DEBUG; keep it quiet regardless.
    logging.getLogger("telethon").setLevel(logging.WARNING)


@app.command("fetch-dataset")
def fetch_dataset() -> None:
    """Clone or update the Vadimkin dataset in data/raw/."""
    s = get_settings()
    sha = dataset.fetch(s.dataset_dir)
    typer.echo(f"dataset at {s.dataset_dir} @ {sha}")


def _dataset_frames() -> tuple[validate.DatasetFrames, dict]:
    s = get_settings()
    if not (s.dataset_dir / "datasets").exists():
        raise typer.BadParameter("dataset not found — run `airalert fetch-dataset` first")
    frames = validate.prepare(
        dataset.read_official_raw(s.dataset_dir), dataset.read_volunteer_raw(s.dataset_dir)
    )
    return frames, dataset.commit_info(s.dataset_dir)


@app.command("validate-dataset")
def validate_dataset() -> None:
    """Run dataset checks 1–8 and write reports/data_quality.{md,json}."""
    s = get_settings()
    frames, commit = _dataset_frames()
    checks = validate.run_dataset_checks(frames)
    checks += validate.pending_telegram_checks(
        "Telegram-дані ще не зібрані (потрібен tg-login + tg-backfill)."
    )
    meta = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "vadimkin_commit": commit["sha"],
        "vadimkin_committed_at": commit["committed_at"],
    }
    md, _ = report.write(checks, meta, s.reports_dir)
    for c in checks:
        typer.echo(f"[{c.status:4}] #{c.id:<2} {c.scope:28} {c.name}: {c.value}")
    typer.echo(f"report: {md}")
    if any(c.status == "FAIL" for c in checks):
        raise typer.Exit(1)


def _utc(day: str) -> datetime:
    dt = datetime.fromisoformat(day)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


@app.command("tg-login")
def tg_login(
    method: str = typer.Option("qr", help="qr (scan in the Telegram app) or code (phone + login code)"),
) -> None:
    """INTERACTIVE: log in to Telegram and create the session file (run by a human)."""
    from getpass import getpass

    from airalert.tg.client import login_code, login_qr, make_client, secure_session, session_file

    s = get_settings()

    def show_qr(url: str) -> None:
        import qrcode

        typer.echo("\nTelegram на телефоні → Налаштування → Пристрої → Підключити пристрій, і скануйте:")
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
        typer.echo("(код оновлюється кожні ~60 с)")

    def ask_password() -> str:
        return getpass("Пароль двофакторної автентифікації (2FA): ")

    async def run() -> int:
        client = make_client(s)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                if method == "qr":
                    await login_qr(client, show_qr, ask_password)
                else:
                    ask = lambda text: typer.prompt(text, default="", show_default=False)  # noqa: E731
                    await login_code(client, ask, ask_password, typer.echo)
            return (await client.get_me()).id
        finally:
            await client.disconnect()

    user_id = asyncio.run(run())
    secure_session(s.session_path)
    typer.echo(f"Logged in as user id {user_id}. Session: {session_file(s.session_path)} (mode 600)")


@app.command("tg-backfill")
def tg_backfill(
    since: str = typer.Option(..., help="UTC date, e.g. 2026-08-25"),
    channel: str = typer.Option(OFFICIAL_CHANNEL),
) -> None:
    """Download channel history since a date into raw_messages (idempotent, resumable).

    Drone channels (TG_DRONE_CHANNELS) go to drones.sqlite. Do not run while tg-live holds the session."""
    from airalert.tg import backfill, store
    from airalert.tg.client import make_client

    s = get_settings()

    async def run() -> int:
        client = make_client(s)
        await client.connect()
        if not await client.is_user_authorized():
            raise typer.BadParameter("not logged in — run `airalert tg-login` first")
        try:
            with store.open_db(s.db_for_channel(channel)) as conn:
                return await backfill.catch_up(client, conn, channel, "backfill", since=_utc(since))
        finally:
            await client.disconnect()

    inserted = asyncio.run(run())
    with store.open_db(s.db_for_channel(channel)) as conn:
        total = store.count(conn, "raw_messages", channel)
    typer.echo(f"{channel}: inserted {inserted} new messages, {total} stored")


@app.command("build")
def build_cmd() -> None:
    """Rebuild alerts from raw_messages, assemble alerts.parquet + manifest, run checks 1–13."""
    from airalert import build as build_mod
    from airalert.config import LIVE_CHANNELS as CHANNELS
    from airalert.tg import rebuild, store

    s = get_settings()
    frames, _ = _dataset_frames()
    dataset_commit = build_mod.git_sha(s.dataset_dir)
    with store.open_db(s.sqlite_path) as conn:
        for ch in CHANNELS:
            st = rebuild.rebuild(conn, ch)
            typer.echo(f"{ch}: {st.alerts} alerts, by type {st.by_type}, errors {dict(st.errors)}")
        result = build_mod.build(conn, frames.official_clean, dataset_commit, Path.cwd())
        checks = validate.run_dataset_checks(frames)
        if store.count(conn, "raw_messages") == 0:  # clean clone: Telegram steps not run yet
            checks += validate.pending_telegram_checks(
                "Telegram-дані відсутні (tg-login + tg-backfill не запускались)."
            )[:4]
        else:
            checks += [
                validate.check_parser_vs_dataset(
                    frames.official_clean, result.tg_official, result.official_outages, result.tg_volunteer
                ),
                validate.check_parse_errors(conn, CHANNELS),
                validate.check_idempotency(conn, CHANNELS, rebuild.rebuild),
                validate.check_live_latency(conn),
            ]
        checks.append(validate.check_seams(result.raw, build_mod.SEAM))
    pq, mf = build_mod.write(result, s.processed_dir)
    meta = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "vadimkin_commit": dataset_commit,
        "code_git_sha": result.manifest["code_git_sha"],
        "seam": build_mod.SEAM.isoformat(),
        "official_outages": "; ".join(
            f"{w.start:%Y-%m-%d %H:%M}…{w.end:%Y-%m-%d %H:%M}" for w in result.official_outages
        ),
    }
    md, _ = report.write(checks, meta, s.reports_dir)
    for c in checks:
        typer.echo(f"[{c.status:4}] #{c.id:<2} {c.scope:34} {c.name}: {c.value}")
    typer.echo(f"{pq} ({len(result.output)} rows), {mf}, {md}")
    if any(c.status == "FAIL" for c in checks):
        raise typer.Exit(1)


@app.command("tg-live")
def tg_live(
    channel: list[str] = typer.Option(LIVE_CHANNELS, help="alert channels (alerts.sqlite)"),
    drones: bool = typer.Option(True, help="also collect TG_DRONE_CHANNELS into drones.sqlite"),
) -> None:
    """Catch up on missed messages, then collect new/edited ones forever (Ctrl+C to stop).

    Drone channels without history are downloaded from TG_DRONE_SINCE in the background first."""
    from airalert.tg import live, store
    from airalert.tg.client import make_client

    s = get_settings()
    with store.open_db(s.sqlite_path) as alerts_conn, store.open_db(s.drones_sqlite_path) as drones_conn:
        groups = [live.ChannelGroup(alerts_conn, channel)]
        if drones and s.drone_channels:
            groups.append(live.ChannelGroup(drones_conn, s.drone_channels, since=s.tg_drone_since))
        try:
            asyncio.run(live.run(make_client(s), groups))
        except KeyboardInterrupt:
            typer.echo("collector stopped")


_HEALTH_DBS = {"alerts": "sqlite_path", "drones": "drones_sqlite_path", "sitrep": "sitrep_sqlite_path"}


@app.command("healthcheck")
def healthcheck(
    max_age: int = HEARTBEAT_MAX_AGE_SECONDS,
    db: list[str] = typer.Option(["alerts", "drones"], help="alerts | drones | sitrep (repeatable)"),
) -> None:
    """Exit 0 if every listed collector heartbeat is fresher than ``max_age`` seconds."""
    from airalert.tg import store

    s = get_settings()
    stale = False
    for name in db:
        if name not in _HEALTH_DBS:
            raise typer.BadParameter(f"unknown db {name!r}")
        if name == "drones" and not s.drone_channels:
            continue
        age = store.heartbeat_age(getattr(s, _HEALTH_DBS[name]))
        typer.echo(f"{name}: heartbeat age {age if age is None else round(age)} s")
        stale |= age is None or age > max_age
    if stale:
        raise typer.Exit(1)


@app.command("tg-sample")
def tg_sample(n: int = 20, channel: str = OFFICIAL_CHANNEL, offset: int = 0) -> None:
    """Print stored raw messages (to check the real format)."""
    from airalert.tg import store

    with store.open_db(get_settings().db_for_channel(channel)) as conn:
        rows = conn.execute(
            "SELECT msg_id, posted_at, text FROM raw_messages WHERE channel=? ORDER BY msg_id LIMIT ? OFFSET ?",
            (channel, n, offset),
        ).fetchall()
    for msg_id, posted_at, text in rows:
        typer.echo(f"--- #{msg_id} {posted_at}\n{text}")


@app.command("sitrep-poll")
def sitrep_poll(iterations: int = typer.Option(0, help="0 = forever")) -> None:
    """Poll the alerts.in.ua SITREP every SITREP_POLL_SECONDS; store raw text in sitrep.sqlite when changed."""
    from airalert.sitrep import collector

    s = get_settings()
    src = collector.MarkdownSitrep(s.sitrep_url, s.sitrep_contact)
    with collector.open_db(s.sitrep_sqlite_path) as conn:
        try:
            collector.poll_forever(conn, src, s.sitrep_poll_seconds, iterations=iterations or None)
        except KeyboardInterrupt:
            typer.echo("sitrep collector stopped")


@app.command("sitrep-show")
def sitrep_show() -> None:
    """Parse the newest stored SITREP: m. Kyiv and Kyivska oblast raions under warning."""
    from airalert.sitrep import collector, parser

    with collector.open_db(get_settings().sitrep_sqlite_path) as conn:
        snaps = collector.read_snapshots(conn, collector.MarkdownSitrep.name, limit=1)
    if not snaps:
        raise typer.BadParameter("no snapshots yet — run `airalert sitrep-poll`")
    fetched_at, text = snaps[0]
    typer.echo(f"fetched {fetched_at}, report {parser.report_time(text).isoformat()}")
    for a in parser.kyiv_status(text):
        typer.echo(
            f"{a.region_uk:18} {a.area_uk or '—':16} {a.level:6} since {a.started_at:%H:%M}Z ({a.elapsed_min} min)"
        )


@app.command("db-snapshot")
def db_snapshot(
    db: str = typer.Option("drones", help="alerts | drones | sitrep"),
    out: Path = typer.Option(None, help="default: DATA_DIR/live/snapshots/<db>.sqlite"),
) -> None:
    """Consistent copy of a live DB (SQLite online backup) that is safe to read anywhere.

    Run it INSIDE the container that writes the DB: `docker compose exec collector airalert db-snapshot`.
    On Docker Desktop, SQLite locks are not shared between different bind mounts/containers: a connection
    from another container (e.g. `tools`, which mounts ./data, not ./data/live) believes it is the last one,
    checkpoints and deletes the -wal file the collector is still writing to."""
    import sqlite3
    from contextlib import closing

    s = get_settings()
    if db not in _HEALTH_DBS:
        raise typer.BadParameter(f"unknown db {db!r}")
    src = getattr(s, _HEALTH_DBS[db])
    out = out or s.live_dir / "snapshots" / f"{db}.sqlite"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(src, timeout=30)) as a, closing(sqlite3.connect(tmp)) as b:
        a.backup(b)
    tmp.replace(out)
    typer.echo(f"{src} -> {out}")


@app.command("drones-gazetteer")
def drones_gazetteer() -> None:
    """Download GeoNames UA (+ Ukrainian alternate names) and write data/gazetteer/ua_places.csv.gz."""
    from airalert.drones import gazetteer

    s = get_settings()
    out, n = gazetteer.build_places(s.raw_dir / "geonames", s.gazetteer_dir)
    typer.echo(f"{out}: {n} populated places with Ukrainian names")


@app.command("rebuild-alerts")
def rebuild_alerts(channel: str = OFFICIAL_CHANNEL) -> None:
    """Rebuild alerts + parse_errors from raw_messages (deterministic)."""
    from airalert.tg import rebuild, store

    with store.open_db(get_settings().sqlite_path) as conn:
        st = rebuild.rebuild(conn, channel)
    typer.echo(
        f"{channel}: {st.messages} messages, {st.events} events -> {st.alerts} alerts "
        f"({st.open_alerts} open); by type {st.by_type}; source gaps end at {st.gaps}; ignored {dict(st.ignored)}; errors {dict(st.errors)}"
    )


if __name__ == "__main__":
    app()
