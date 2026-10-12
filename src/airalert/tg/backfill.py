"""Idempotent history download into ``raw_messages``. Shared by ``tg-backfill`` and ``tg-live``
(on start the live collector catches up from ``max(msg_id)`` with exactly this code)."""

import asyncio
import logging
import sqlite3
from datetime import datetime

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from airalert.tg import store

log = logging.getLogger(__name__)
BATCH = 200
# Seconds between history pages (Telethon's ``wait_time``) — be gentle with long backfills.
HISTORY_PAGE_PAUSE = 1.0


def to_raw(message, channel: str, mode: str) -> store.RawMessage:
    return store.RawMessage(
        channel=channel,
        msg_id=message.id,
        posted_at=store.iso(message.date),
        edited_at=store.iso(getattr(message, "edit_date", None)),
        text=getattr(message, "message", None) or "",
        received_at=store.utc_now_iso(),
        ingest_mode=mode,
    )


async def _fetch(
    client: TelegramClient, conn: sqlite3.Connection, channel: str, mode: str, peer=None, **kw
) -> int:
    inserted, buf = 0, []
    async for m in client.iter_messages(peer or channel, reverse=True, **kw):
        buf.append(to_raw(m, channel, mode))
        if len(buf) >= BATCH:
            inserted += store.insert_messages(conn, buf)
            store.heartbeat(conn, buf[-1].msg_id)
            log.info("%s: stored up to msg %s (%s)", channel, buf[-1].msg_id, buf[-1].posted_at)
            buf.clear()
    if buf:
        inserted += store.insert_messages(conn, buf)
        store.heartbeat(conn, buf[-1].msg_id)
    return inserted


async def _with_flood_wait(coro_factory) -> int:
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as e:  # longer than FLOOD_SLEEP_THRESHOLD; wait exactly as told
            log.warning("FloodWait: sleeping %s s", e.seconds)
            await asyncio.sleep(e.seconds + 1)


def needs_history(conn: sqlite3.Connection, channel: str, since: datetime) -> bool:
    first = store.min_posted_at(conn, channel)
    return first is None or datetime.fromisoformat(first[1]) > since


async def fill_history(
    client: TelegramClient, conn: sqlite3.Connection, channel: str, since: datetime, peer=None
) -> int:
    """Download history between ``since`` and the oldest stored message (everything, if nothing is stored),
    as ``ingest_mode='backfill'``. One request per ``HISTORY_PAGE_PAUSE`` seconds."""
    if not needs_history(conn, channel, since):
        return 0
    first = store.min_posted_at(conn, channel)
    older_than = first[0] if first else 0
    return await _with_flood_wait(
        lambda: _fetch(
            client,
            conn,
            channel,
            "backfill",
            peer,
            offset_date=since,
            max_id=older_than,
            wait_time=HISTORY_PAGE_PAUSE,
        )
    )


async def fetch_new(
    client: TelegramClient, conn: sqlite3.Connection, channel: str, mode: str, peer=None
) -> int:
    """Everything after the newest stored message. ``max(msg_id)`` is recomputed inside the lambda so a
    retry after FloodWait resumes from where it stopped."""
    return await _with_flood_wait(
        lambda: _fetch(client, conn, channel, mode, peer, min_id=store.max_msg_id(conn, channel) or 0)
    )


async def catch_up(
    client: TelegramClient,
    conn: sqlite3.Connection,
    channel: str,
    mode: str = "backfill",
    since: datetime | None = None,
    peer=None,
) -> int:
    """Fetch everything after the newest stored message; with ``since``, also fill the history between
    ``since`` and the oldest stored message. Re-running never creates duplicates."""
    inserted = 0
    if since is not None:
        inserted += await fill_history(client, conn, channel, since, peer)
    elif store.min_posted_at(conn, channel) is None:
        raise ValueError(f"no messages stored for {channel}; pass --since for the first backfill")
    return inserted + await fetch_new(client, conn, channel, mode, peer)
