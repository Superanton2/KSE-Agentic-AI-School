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


def _drones_db(db: Path | None) -> Path:
    s = get_settings()
    path = db or s.live_dir / "snapshots" / "drones.sqlite"
    if not path.exists():
        raise typer.BadParameter(
            f"{path} not found — make a snapshot first: docker compose exec collector airalert db-snapshot"
        )
    return path


@app.command("drones-parse")
def drones_parse(db: Path = typer.Option(None, help="drones journal (default: the snapshot)")) -> None:
    """Parse drone channels -> data/processed/drone_{mentions,lines}.parquet, misses CSV, reports/drone_parse.md."""
    import sqlite3
    from contextlib import closing

    from airalert.drones import mentions as dm
    from airalert.drones.gazetteer import Gazetteer

    s = get_settings()
    with closing(sqlite3.connect(_drones_db(db))) as conn:
        raw, edits = dm.read_journal(conn)
    lines, mentions = dm.build(raw, edits, Gazetteer.load(s.gazetteer_dir))
    s.processed_dir.mkdir(parents=True, exist_ok=True)
    mentions.to_parquet(s.processed_dir / "drone_mentions.parquet", index=False, compression="zstd")
    lines.drop(columns=["message"]).to_parquet(
        s.processed_dir / "drone_lines.parquet", index=False, compression="zstd"
    )
    dm.misses(mentions).to_csv(s.processed_dir / "drone_parse_misses.csv", index=False)
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    (s.reports_dir / "drone_parse.md").write_text(dm.report_md(lines, mentions), encoding="utf-8")
    share = mentions.assign(ok=mentions["lat"].notna()).groupby("channel")["ok"].mean().round(3).to_dict()
    typer.echo(f"{len(lines)} lines, {len(mentions)} mentions; with coordinates: {share}")


@app.command("drones-sample")
def drones_sample(
    n: int = 300,
    seed: int = 20260812,
    db: Path = typer.Option(None, help="drones journal (default: the snapshot)"),
    out: Path = typer.Option(None, help="default: data/labels/sample.jsonl"),
    exclude: list[Path] = typer.Option([], help="jsonl files whose ids must not be sampled again (hold-out)"),
    blind: bool = typer.Option(
        False,
        help="keep the parser-derived stratum out of the jsonl (-> <out>_strata.json) for independent labelling",
    ),
) -> None:
    """Stratified sample of parsed lines for manual labelling -> data/labels/sample.jsonl (+ _meta.json)."""
    import json
    import sqlite3
    from contextlib import closing

    from airalert.drones import evaluate as ev
    from airalert.drones import mentions as dm
    from airalert.drones.gazetteer import Gazetteer

    s = get_settings()
    with closing(sqlite3.connect(_drones_db(db))) as conn:
        raw, edits = dm.read_journal(conn)
    lines, mentions = dm.build(raw, edits, Gazetteer.load(s.gazetteer_dir))
    messages = {
        (r.channel, int(r.msg_id), int(r.version)): r.message
        for r in lines.drop_duplicates(["channel", "msg_id", "version"]).itertuples(index=False)
    }
    seen = {r["id"] for f in exclude for r in ev.read_jsonl(f)}
    if seen:
        ids = (
            lines["channel"]
            + ":"
            + lines["msg_id"].astype(str)
            + ":"
            + lines["version"].astype(str)
            + ":"
            + lines["line_no"].astype(str)
        )
        lines = lines[~ids.isin(seen)]
    rows = ev.sample(lines, mentions, messages, n, seed)
    out = out or s.data_dir / "labels" / "sample.jsonl"
    if blind:
        strata = {r["id"]: r.pop("stratum") for r in rows}
        out.with_name(out.stem + "_strata.json").write_text(
            json.dumps(strata, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    ev.write_jsonl(rows, out)
    meta = {"n": len(rows), "seed": seed, "strata_sizes": ev.strata_sizes(lines, mentions)}
    out.with_name(out.stem + "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    by = pd.Series([r["channel"] for r in rows]).value_counts().to_dict()
    typer.echo(f"{out}: {len(rows)} lines {by}")


@app.command("drones-eval")
def drones_eval(
    gold: Path = typer.Option(None, help="default: data/labels/gold.jsonl"),
    mentions_path: Path = typer.Option(
        None, "--mentions", help="default: data/processed/drone_mentions.parquet"
    ),
    sample: Path = typer.Option(None, help="the sample the gold labels belong to (for re-weighting)"),
    report: str = typer.Option("drone_parse_eval", help="report name in reports/"),
) -> None:
    """Precision/recall of the parser vs gold labels (kind, count, oblast, place) -> reports/drone_parse_eval.md."""
    import json

    from airalert.drones import evaluate as ev

    s = get_settings()
    labels = s.data_dir / "labels"
    gold = gold or labels / "gold.jsonl"
    if not gold.exists():
        typer.echo(
            f"{gold} not found. Label {labels / 'sample.jsonl'} first (format: {labels / 'README.md'}), "
            "save the result as gold.jsonl, then re-run.",
            err=True,
        )
        raise typer.Exit(2)
    gold_rows = ev.read_jsonl(gold)
    mentions = pd.read_parquet(mentions_path or s.processed_dir / "drone_mentions.parquet")
    weights = None
    sample = sample or labels / "sample.jsonl"
    meta_path = sample.with_name(sample.stem + "_meta.json")
    if meta_path.exists() and sample.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rows = ev.read_jsonl(sample)
        strata_path = sample.with_name(sample.stem + "_strata.json")
        if strata_path.exists():  # blind sample: strata kept apart from the labeller's file
            strata = json.loads(strata_path.read_text(encoding="utf-8"))
            rows = [{**r, "stratum": strata[r["id"]]} for r in rows]
        weights = ev.weights_for(rows, meta["strata_sizes"])
    table, errors = ev.evaluate(gold_rows, mentions, weights)
    missed = ev.meets_targets(table)
    md = [
        "# Drone parser vs gold labels",
        "",
        f"{len(gold_rows)} labelled lines. `precision`/`recall` are measured on the stratified sample, which "
        "over-samples failure strata; `w_precision`/`w_recall` re-weight it to the whole stream by stratum size "
        "(the targets are checked on these). Caveat: `kind`/`count`/`oblast` are scored only on places that "
        "matched, and `oblast` counts as correct whenever the gold oblast is empty — so they mostly repeat the "
        "`place` numbers and are not independent accuracy estimates.",
        "",
        ev.md_table(table),
        "",
    ]
    md += (
        ["## Targets", "", *(f"- MISSED: {m}" for m in missed)] if missed else ["## Targets", "", "- all met"]
    )
    md += ["", "## Errors", ""] + [
        f"- `{e['id']}` **{e['error']}** gold={json.dumps(e['gold'], ensure_ascii=False)} "
        f"pred={json.dumps(e['pred'], ensure_ascii=False, default=str)}"
        for e in errors
    ]
    (s.reports_dir / f"{report}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    typer.echo(table.to_string(index=False))
    typer.echo(f"errors: {dict(ev.error_summary(errors))}; report: {s.reports_dir / (report + '.md')}")
    if missed:
        typer.echo("TARGETS MISSED: " + "; ".join(missed))
        raise typer.Exit(1)


@app.command("drones-motion")
def drones_motion(seed: int = 0) -> None:
    """Pseudo-tracks + CRW motion model calibration vs baselines -> data/processed/drone_tracks.parquet,
    drone_motion_params.json, reports/drone_motion.md (+ PNG examples)."""
    import json

    from airalert.drones import motion as mo
    from airalert.drones import report_motion as rm
    from airalert.drones import tracker as tk
    from airalert.drones.gazetteer import Gazetteer

    s = get_settings()
    mentions = pd.read_parquet(s.processed_dir / "drone_mentions.parquet")
    tracks = tk.build_tracks(tk.observations(mentions), Gazetteer.load(s.gazetteer_dir).oblast_centroids)
    tracks.to_parquet(s.processed_dir / "drone_tracks.parquet", index=False, compression="zstd")
    pairs = mo.calibration_pairs(tracks)
    cal, val = rm.split(pairs)
    result = mo.calibrate(cal, val, seed=seed)
    p = result["params"]
    (s.processed_dir / "drone_motion_params.json").write_text(
        json.dumps(
            {"sigma_theta": p.sigma_theta, "sigma_v": p.sigma_v, "calibrated_until": str(rm.CAL_END)},
            indent=1,
        ),
        encoding="utf-8",
    )
    pngs = rm.plot_examples(tracks, p, s.reports_dir / "drone_motion", seed=seed)
    out = rm.write_report(tracks, pairs, result, pngs, s.reports_dir)
    typer.echo(f"{tk.track_stats(tracks)}; fitted {p}")
    typer.echo(result["models"].to_string(index=False))
    typer.echo(f"report: {out}")


@app.command("drones-features")
def drones_features(
    check_leak: int = typer.Option(
        5, help="random grid points re-computed from data truncated at t (0 = skip)"
    ),
    seed: int = 0,
) -> None:
    """As-of drone 'pressure field' features on a 5-min grid -> data/processed/drone_features.parquet,
    leakage check and lift vs the raion-alert baseline -> reports/drone_features.md."""
    import json

    import numpy as np

    from airalert.drones import features as fe
    from airalert.drones import motion as mo
    from airalert.drones.gazetteer import Gazetteer

    s = get_settings()
    mentions = pd.read_parquet(s.processed_dir / "drone_mentions.parquet")
    p = json.loads((s.processed_dir / "drone_motion_params.json").read_text())
    params = mo.MotionParams(p["sigma_theta"], p["sigma_v"])
    centroids = Gazetteer.load(s.gazetteer_dir).oblast_centroids
    times = fe.grid(pd.Timestamp("2026-08-10", tz="UTC"), mentions["known_at"].max())
    feats = fe.build(mentions, centroids, params, times)
    feats.to_parquet(s.processed_dir / "drone_features.parquet", index=False, compression="zstd")
    typer.echo(f"{len(feats)} rows x {len(fe.FEATURES)} features")

    leak = []
    rng = np.random.default_rng(seed)
    busy = feats.index[feats["mentions_last_60m"] > 0].to_numpy()  # check where something is going on
    for i in rng.choice(busy, size=min(check_leak, len(busy)), replace=False):
        t = feats.at[i, "t"]
        prep = fe.prepare(mentions[mentions["known_at"] <= t], centroids, params)
        again = fe.features_at(prep, t)
        same = all(
            (np.isnan(a) and np.isnan(b)) if isinstance(a, float) and np.isnan(a) else a == b
            for a, b in ((again[c], feats.at[i, c]) for c in fe.FEATURES)
        )
        leak.append((t, same))
        typer.echo(f"leak check {t}: {'identical' if same else 'DIFFERENT'}")

    alerts = pd.read_parquet(s.processed_dir / "alerts.parquet")
    cal = feats[feats["t"] < pd.Timestamp("2026-09-13", tz="UTC")].reset_index(drop=True)
    cal_t = pd.DatetimeIndex(cal["t"])
    table = fe.lift_table(cal, fe.alert_labels(alerts, cal_t), fe.raion_alert_active(alerts, cal_t))
    md = [
        "# Drone pressure-field features",
        "",
        f"`data/processed/drone_features.parquet`: {len(feats)} rows (5-min UTC grid, {feats['t'].min():%Y-%m-%d} … "
        f"{feats['t'].max():%Y-%m-%d %H:%M}), as-of: row t uses only mentions with known_at ≤ t. Main source kudy_letyt; "
        "kpszsu only as auxiliary counters (parser recall 0.66 raw on the hold-out); motion model "
        f"σ_θ={params.sigma_theta}, σ_v={params.sigma_v} (fitted on 2026-08-10…09-12).",
        "",
        "## Leakage check",
        "",
        f"{len(leak)} random busy grid points recomputed from data truncated at t: "
        f"**{sum(ok for _, ok in leak)}/{len(leak)} bit-identical**.",
        "",
        "## Lift on the calibration period (2026-08-10 … 2026-09-12)",
        "",
        "Lift = P(Kyiv City alert starts within H | feature on) / P(… | off), grid points outside an alert only. "
        "Baseline: a raion alert in Kyiv oblast is on (as known at t). No modelling, single features.",
        "",
        "| feature | share on | lift 15 | lift 30 | lift 60 | lift 120 |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r.feature} | {r.share_on:.1%} | {r.lift_15:.1f} | {r.lift_30:.1f} | {r.lift_60:.1f} | {r.lift_120:.1f} |"
            for r in table.itertuples()
        ],
        "",
        "### Incremental: only grid points with **no raion alert** in Kyiv oblast",
        "",
        "Does the feature say something the raion alerts do not (yet)?",
        "",
        "| feature | lift 15 | lift 30 | lift 60 | lift 120 |",
        "|---|---|---|---|---|",
        *[
            f"| {r.feature} | {r.lift_15_no_raion:.1f} | {r.lift_30_no_raion:.1f} | {r.lift_60_no_raion:.1f} "
            f"| {r.lift_120_no_raion:.1f} |"
            for r in table.itertuples()
            if not r.feature.startswith("raion")
        ],
        "",
    ]
    (s.reports_dir / "drone_features.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    typer.echo(table.round(2).to_string(index=False))
    if not all(ok for _, ok in leak):
        raise typer.Exit(1)


@app.command("model-features")
def model_features(check_leak: int = typer.Option(200, help="random t recomputed from truncated sources")) -> None:
    """Phase 4 grid: labels + as-of features -> data/processed/model_grid.parquet, reports/model_lift.md."""
    from airalert.model import pipeline

    s = get_settings()
    g = pipeline.build_grid(s.data_dir, s.reports_dir, check_leak)
    typer.echo(f"{len(g)} grid points ({int(g['calm'].sum())} calm) -> {s.reports_dir / 'model_lift.md'}")


@app.command("model-eval")
def model_eval(n_trips: int = 2000) -> None:
    """Phase 4: C selection, walk-forward test, KM, product backtest -> reports/model_eval.md."""
    from airalert.model import pipeline

    s = get_settings()
    r = pipeline.evaluate_all(s.data_dir, s.reports_dir, n_trips)
    typer.echo(f"product model {r['product']}; backtest BSS vs B1 {r['bt']['bss_vs_B1']:.3f}")


@app.command("model-fit")
def model_fit(
    rebuild: bool = typer.Option(True, help="rebuild the grid first"),
    from_live: bool = typer.Option(False, help="back up the live alerts DB read-only into data/work first"),
    at: str = typer.Option("", help="HH:MM Kyiv time: run every day at that time (nightly service)"),
) -> None:
    """Nightly: (grid rebuild) -> refit the product ensemble on all closed labels -> model_card.json."""
    import json
    import time as _time

    from airalert.model import pipeline

    s = get_settings()

    def once() -> None:
        db = None
        if from_live:  # read-only online backup: safe even from another container (cannot touch the WAL)
            import sqlite3
            from contextlib import closing

            db = s.data_dir / "work" / "alerts.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(f"file:{s.sqlite_path}?mode=ro", uri=True, timeout=30)) as a, \
                    closing(sqlite3.connect(db)) as b:
                a.backup(b)
        if rebuild:
            pipeline.build_grid(s.data_dir, s.reports_dir, check_leak=20, db=db, report=False)
        summ = json.loads((pipeline.eval_dir(s.data_dir) / "summary.json").read_text())
        art = pipeline.fit_final(s.data_dir, summ["product"], summ["C"][summ["product"]], db=db)
        pipeline.model_card(s.data_dir, updated_at=art["fitted_at"], db=db)
        typer.echo(f"{art['model']} x{len(art['members'])} fitted on data to {art['train_end']}")

    if not at:
        once()
        return
    hh, mm = (int(x) for x in at.split(":"))
    while True:
        now = pd.Timestamp.now(tz="Europe/Kyiv")
        nxt = now.normalize() + pd.Timedelta(hours=hh, minutes=mm)
        if nxt <= now:
            nxt += pd.Timedelta(days=1)
        log.info("next refit at %s", nxt)
        _time.sleep((nxt - now).total_seconds())
        try:
            once()
        except Exception:
            log.exception("nightly refit failed; the API keeps the previous model")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """FastAPI: /api/state, /api/scenarios, /api/estimate, /api/model-card + static web/."""
    import uvicorn

    from airalert.api.app import create_app

    uvicorn.run(create_app(), host=host, port=port, access_log=False, log_level="info")


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
