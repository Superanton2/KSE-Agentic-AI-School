"""tg-live with a fake Telethon client: one client, two DBs, background history download."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from airalert.tg import live, store

T0 = datetime(2026, 8, 1, tzinfo=UTC)


def _m(i: int, text: str = "t"):
    return SimpleNamespace(id=i, date=T0 + timedelta(days=i), edit_date=None, message=text)


class FakeClient:
    """Implements just the Telethon surface used by live/backfill."""

    def __init__(self, history: dict[str, list], run_for: float = 0.2, on_start=None):
        self.history, self.run_for, self.on_start = history, run_for, on_start
        self.handlers = []
        self.requests: list[tuple[str, dict]] = []

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_input_entity(self, name):
        return name

    async def get_peer_id(self, peer):
        return -100 - sorted(self.history).index(peer)

    def on(self, builder):
        def deco(fn):
            self.handlers.append((type(builder).__name__, fn))
            return fn

        return deco

    async def iter_messages(self, peer, reverse=True, min_id=0, max_id=0, offset_date=None, wait_time=None):
        self.requests.append((peer, {"min_id": min_id, "max_id": max_id, "offset_date": offset_date}))
        for m in sorted(self.history[peer], key=lambda m: m.id):
            if m.id <= min_id or (max_id and m.id >= max_id) or (offset_date and m.date <= offset_date):
                continue
            yield m

    async def run_until_disconnected(self):
        if self.on_start:
            await self.on_start(self)
        await asyncio.sleep(self.run_for)

    async def disconnect(self):
        pass

    async def fire_new(self, peer, message):
        ev = SimpleNamespace(chat_id=await self.get_peer_id(peer), message=message)
        for kind, fn in self.handlers:
            if kind == "NewMessage":
                await fn(ev)


def _rows(conn, channel):
    return conn.execute(
        "SELECT msg_id, ingest_mode FROM raw_messages WHERE channel=? ORDER BY msg_id", (channel,)
    ).fetchall()


def test_two_groups_history_download_and_routing(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "POLL_SECONDS", 0.01)
    since = T0 + timedelta(days=2, hours=12)  # history from msg 3 on
    client = FakeClient({"alerts": [_m(i) for i in range(1, 6)], "drones": [_m(i) for i in range(1, 8)]})
    with store.open_db(tmp_path / "a.sqlite") as a, store.open_db(tmp_path / "d.sqlite") as d:
        store.insert_messages(a, [store.RawMessage("alerts", 1, "x", None, "t", "x", "backfill")])
        asyncio.run(
            live.run(client, [live.ChannelGroup(a, ["alerts"]), live.ChannelGroup(d, ["drones"], since)])
        )
        assert _rows(a, "alerts") == [(1, "backfill")] + [(i, "live") for i in range(2, 6)]
        assert _rows(d, "drones") == [(i, "backfill") for i in range(3, 8)]  # nothing before `since`
        assert _rows(a, "drones") == [] and _rows(d, "alerts") == []
        for conn in (a, d):
            assert conn.execute("SELECT COUNT(*) FROM collector_heartbeat").fetchone() == (1,)


def test_updates_ignored_until_channel_is_caught_up(tmp_path, monkeypatch):
    """A fresh update must not bump max(msg_id) before the catch-up, or the gap before it is lost."""
    monkeypatch.setattr(live, "POLL_SECONDS", 0.01)
    history = {"alerts": [_m(i) for i in range(1, 4)]}
    with store.open_db(tmp_path / "a.sqlite") as a:
        store.insert_messages(a, [store.RawMessage("alerts", 1, "x", None, "t", "x", "backfill")])

        async def scenario():
            client = FakeClient(history)
            orig = client.iter_messages

            async def slow_iter(peer, **kw):  # an update for msg 9 arrives during the catch-up request
                if len(client.requests) == 0:
                    await client.fire_new("alerts", _m(9))
                async for m in orig(peer, **kw):
                    yield m

            client.iter_messages = slow_iter
            await live.run(client, [live.ChannelGroup(a, ["alerts"])])

        asyncio.run(scenario())
        assert [r[0] for r in _rows(a, "alerts")] == [1, 2, 3]


def test_second_start_does_not_redownload_history(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "POLL_SECONDS", 0.01)
    since = T0
    hist = {"drones": [_m(i) for i in range(1, 4)]}
    with store.open_db(tmp_path / "d.sqlite") as d:
        asyncio.run(live.run(FakeClient(hist, run_for=0.05), [live.ChannelGroup(d, ["drones"], since)]))
        hist["drones"].append(_m(4))
        client = FakeClient(hist, run_for=0.05)
        asyncio.run(live.run(client, [live.ChannelGroup(d, ["drones"], since)]))
        assert _rows(d, "drones")[-1] == (4, "live")
        # only "newer than max" or "older than the oldest stored" (cheap, empty) requests — no re-download
        assert all(r[1]["min_id"] >= 3 or r[1]["max_id"] == 1 for r in client.requests)
