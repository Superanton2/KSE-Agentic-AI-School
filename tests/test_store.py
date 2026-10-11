from airalert.tg import store


def _msg(i, text="t", mode="backfill"):
    return store.RawMessage(
        "air_alert_ua", i, f"2026-09-01T10:{i:02d}:00+00:00", None, text, "2026-09-01T11:00:00+00:00", mode
    )


def test_insert_is_idempotent(tmp_path):
    with store.open_db(tmp_path / "a.sqlite") as conn:
        assert store.insert_messages(conn, [_msg(1), _msg(2)]) == 2
        assert store.insert_messages(conn, [_msg(1), _msg(2), _msg(3)]) == 1
        assert store.count(conn, "raw_messages") == 3
        assert store.max_msg_id(conn, "air_alert_ua") == 3


def test_first_seen_text_is_kept_and_edits_logged(tmp_path):
    with store.open_db(tmp_path / "a.sqlite") as conn:
        store.insert_messages(conn, [_msg(1, "orig")])
        store.insert_messages(conn, [_msg(1, "changed")])
        assert store.record_edit(conn, "air_alert_ua", 1, "2026-09-01T10:05:00+00:00", "edited")
        assert not store.record_edit(conn, "air_alert_ua", 1, "2026-09-01T10:06:00+00:00", "edited")
        text, edited = conn.execute("SELECT text, edited_at FROM raw_messages").fetchone()
        assert (text, edited) == ("orig", "2026-09-01T10:05:00+00:00")
        assert conn.execute("SELECT old_text, new_text FROM message_edits").fetchall() == [("orig", "edited")]


def test_heartbeat_upsert(tmp_path):
    with store.open_db(tmp_path / "a.sqlite") as conn:
        store.heartbeat(conn, 5)
        store.heartbeat(conn, None)
        assert conn.execute("SELECT last_msg_id FROM collector_heartbeat").fetchall() == [(5,)]
