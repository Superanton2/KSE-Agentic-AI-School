"""Command-line entry point: ``airalert <command>``."""

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd
import typer

from airalert import dataset, report, validate
from airalert.config import OFFICIAL_CHANNEL, get_settings

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
def tg_login() -> None:
    """INTERACTIVE: log in to Telegram and create the session file (run by a human)."""
    from airalert.tg.client import make_client, secure_session, session_file

    s = get_settings()

    async def run() -> int:
        client = make_client(s)
        await client.start()  # prompts for phone, code and 2FA password on the terminal
        me = await client.get_me()
        await client.disconnect()
        return me.id

    user_id = asyncio.run(run())
    secure_session(s.session_path)
    typer.echo(f"Logged in as user id {user_id}. Session: {session_file(s.session_path)} (mode 600)")


@app.command("tg-backfill")
def tg_backfill(
    since: str = typer.Option(..., help="UTC date, e.g. 2026-08-25"),
    channel: str = typer.Option(OFFICIAL_CHANNEL),
) -> None:
    """Download channel history since a date into raw_messages (idempotent, resumable)."""
    from airalert.tg import backfill, store
    from airalert.tg.client import make_client

    s = get_settings()

    async def run() -> int:
        client = make_client(s)
        await client.connect()
        if not await client.is_user_authorized():
            raise typer.BadParameter("not logged in — run `airalert tg-login` first")
        try:
            with store.open_db(s.sqlite_path) as conn:
                return await backfill.catch_up(client, conn, channel, "backfill", since=_utc(since))
        finally:
            await client.disconnect()

    inserted = asyncio.run(run())
    with store.open_db(s.sqlite_path) as conn:
        total = store.count(conn, "raw_messages", channel)
    typer.echo(f"{channel}: inserted {inserted} new messages, {total} stored")


@app.command("tg-sample")
def tg_sample(n: int = 20, channel: str = OFFICIAL_CHANNEL, offset: int = 0) -> None:
    """Print stored raw messages (to check the real format)."""
    from airalert.tg import store

    with store.open_db(get_settings().sqlite_path) as conn:
        rows = conn.execute(
            "SELECT msg_id, posted_at, text FROM raw_messages WHERE channel=? ORDER BY msg_id LIMIT ? OFFSET ?",
            (channel, n, offset),
        ).fetchall()
    for msg_id, posted_at, text in rows:
        typer.echo(f"--- #{msg_id} {posted_at}\n{text}")


@app.command("rebuild-alerts")
def rebuild_alerts(channel: str = OFFICIAL_CHANNEL) -> None:
    """Rebuild alerts + parse_errors from raw_messages (deterministic)."""
    from airalert.tg import rebuild, store

    with store.open_db(get_settings().sqlite_path) as conn:
        st = rebuild.rebuild(conn, channel)
    typer.echo(
        f"{channel}: {st.messages} messages, {st.events} events -> {st.alerts} alerts "
        f"({st.open_alerts} open); ignored {dict(st.ignored)}; errors {dict(st.errors)}"
    )


if __name__ == "__main__":
    app()
