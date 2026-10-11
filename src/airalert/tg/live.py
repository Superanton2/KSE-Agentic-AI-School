"""Live collector: catch up on everything missed, then keep appending new and edited messages.

Two delivery paths write into the same idempotent journal:
- Telegram updates (NewMessage / MessageEdited) — instant, but Telegram only pushes updates for
  channels the account is subscribed to (the collector never joins channels itself);
- polling every ``POLL_SECONDS`` with ``min_id = max(msg_id)`` — the same code as backfill; covers
  unsubscribed channels and any updates lost during reconnects.

Messages fetched by the collector are stored with ``ingest_mode='live'``: they are known from
``received_at`` (for a catch-up after downtime that is honestly later than ``posted_at``).
Read-only: no send/join/read-acknowledge calls are made.
"""

import asyncio
import contextlib
import logging
import sqlite3

from telethon import TelegramClient, events

from airalert.tg import backfill, store

log = logging.getLogger(__name__)
POLL_SECONDS = 15


async def _poll_forever(client: TelegramClient, conn: sqlite3.Connection, peers: dict, stop: asyncio.Event):
    while not stop.is_set():
        for name, peer in peers.items():
            try:
                n = await backfill.catch_up(client, conn, name, "live", peer=peer)
                if n:
                    log.info("%s: +%s messages (poll)", name, n)
            except (ConnectionError, OSError) as e:  # Telethon reconnects by itself; retry next tick
                log.warning("%s: poll failed: %s", name, e)
        store.heartbeat(conn, None)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)


async def run(client: TelegramClient, conn: sqlite3.Connection, channels: list[str]) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("not logged in — run `airalert tg-login` first")
    peers = {name: await client.get_input_entity(name) for name in channels}
    ids = {(await client.get_peer_id(p)): name for name, p in peers.items()}

    @client.on(events.NewMessage(chats=list(peers.values())))
    async def on_new(event):
        name = ids.get(event.chat_id)
        if name and store.insert_messages(conn, [backfill.to_raw(event.message, name, "live")]):
            store.heartbeat(conn, event.message.id)
            log.info("%s: msg %s (update)", name, event.message.id)

    @client.on(events.MessageEdited(chats=list(peers.values())))
    async def on_edit(event):
        name = ids.get(event.chat_id)
        m = event.message
        if name and store.record_edit(conn, name, m.id, store.iso(m.edit_date), m.message or ""):
            log.info("%s: msg %s edited", name, m.id)

    for name, peer in peers.items():
        if store.max_msg_id(conn, name) is None:
            raise RuntimeError(f"{name}: no history stored; run `airalert tg-backfill --since …` first")
        n = await backfill.catch_up(client, conn, name, "live", peer=peer)
        log.info("%s: caught up, +%s messages", name, n)
    store.heartbeat(conn, None)

    stop = asyncio.Event()
    poller = asyncio.create_task(_poll_forever(client, conn, peers, stop))
    try:
        await client.run_until_disconnected()
    finally:
        stop.set()
        await poller
