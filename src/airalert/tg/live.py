"""Live collector: catch up on everything missed, then keep appending new and edited messages.

One Telethon client (a session file must never be opened by two processes) serves several channel
groups, each with its own SQLite journal: alert channels -> ``alerts.sqlite``, drone-monitoring channels ->
``drones.sqlite`` (so heavy drone traffic never blocks the alerts DB).

Two delivery paths write into the same idempotent journal:
- Telegram updates (NewMessage / MessageEdited) — instant, but Telegram only pushes updates for
  channels the account is subscribed to (the collector never joins channels itself);
- polling every ``POLL_SECONDS`` with ``min_id = max(msg_id)`` — the same code as backfill; covers
  unsubscribed channels and any updates lost during reconnects.

A channel is *ready* once its catch-up is done; updates for channels that are not ready yet are ignored
(otherwise a fresh message would bump ``max(msg_id)`` and the catch-up would skip the gap before it).
Groups with ``since`` download their history from that date on the first start, in the background, as
``ingest_mode='backfill'`` (known at ``posted_at``); the other channels keep being collected meanwhile.

Messages fetched by the collector are stored with ``ingest_mode='live'``: they are known from
``received_at`` (for a catch-up after downtime that is honestly later than ``posted_at``).
Read-only: no send/join/read-acknowledge calls are made.
"""

import asyncio
import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from telethon import TelegramClient, events

from airalert.tg import backfill, store

log = logging.getLogger(__name__)
POLL_SECONDS = 15


@dataclass
class ChannelGroup:
    conn: sqlite3.Connection
    channels: list[str]
    since: datetime | None = None  # first start: download history from here


async def _poll_forever(client: TelegramClient, groups: list[ChannelGroup], ready: dict, stop: asyncio.Event):
    while not stop.is_set():
        for g in groups:
            for name in g.channels:
                if name not in ready:
                    continue
                try:
                    n = await backfill.fetch_new(client, g.conn, name, "live", peer=ready[name])
                    if n:
                        log.info("%s: +%s messages (poll)", name, n)
                except (ConnectionError, OSError) as e:  # Telethon reconnects by itself; retry next tick
                    log.warning("%s: poll failed: %s", name, e)
            store.heartbeat(g.conn, None)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)


async def _fill_histories(
    client: TelegramClient, pending: list[tuple[ChannelGroup, str]], peers: dict, ready: dict
):
    for g, name in pending:
        log.info("%s: downloading history since %s", name, g.since)
        n = await backfill.fill_history(client, g.conn, name, g.since, peer=peers[name])
        n += await backfill.fetch_new(client, g.conn, name, "live", peer=peers[name])
        ready[name] = peers[name]
        log.info("%s: history done, +%s messages; now live", name, n)


async def run(client: TelegramClient, groups: list[ChannelGroup]) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("not logged in — run `airalert tg-login` first")
    conns = {name: g.conn for g in groups for name in g.channels}
    peers = {name: await client.get_input_entity(name) for name in conns}
    ids = {(await client.get_peer_id(p)): name for name, p in peers.items()}
    ready: dict = {}

    @client.on(events.NewMessage(chats=list(peers.values())))
    async def on_new(event):
        name = ids.get(event.chat_id)
        if name in ready and store.insert_messages(
            conns[name], [backfill.to_raw(event.message, name, "live")]
        ):
            store.heartbeat(conns[name], event.message.id)
            log.info("%s: msg %s (update)", name, event.message.id)

    @client.on(events.MessageEdited(chats=list(peers.values())))
    async def on_edit(event):
        name = ids.get(event.chat_id)
        m = event.message
        if name in ready and store.record_edit(
            conns[name], name, m.id, store.iso(m.edit_date), m.message or ""
        ):
            log.info("%s: msg %s edited", name, m.id)

    pending = []
    for g in groups:
        for name in g.channels:
            if g.since is not None and backfill.needs_history(g.conn, name, g.since):
                pending.append((g, name))
                continue
            if store.max_msg_id(g.conn, name) is None:
                raise RuntimeError(f"{name}: no history stored; run `airalert tg-backfill --since …` first")
            n = await backfill.fetch_new(client, g.conn, name, "live", peer=peers[name])
            ready[name] = peers[name]
            log.info("%s: caught up, +%s messages", name, n)
        store.heartbeat(g.conn, None)

    stop = asyncio.Event()
    poller = asyncio.create_task(_poll_forever(client, groups, ready, stop))
    filler = asyncio.create_task(_fill_histories(client, pending, peers, ready))
    # A failed history download stops the whole collector (Docker restarts it; the download resumes).
    filler.add_done_callback(
        lambda t: t.cancelled() or t.exception() is None or asyncio.ensure_future(client.disconnect())
    )
    try:
        await client.run_until_disconnected()
    finally:
        stop.set()
        filler.cancel()
        await poller
        await asyncio.gather(filler, return_exceptions=True)
    if not filler.cancelled() and filler.exception() is not None:
        raise RuntimeError("history download failed") from filler.exception()
