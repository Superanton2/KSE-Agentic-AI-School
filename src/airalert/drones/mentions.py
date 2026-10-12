"""drones.sqlite journal -> message versions -> ``drone_lines`` + ``drone_mentions`` (+ parse misses).

Versions and time (no leakage):
- a message has version 0 (first text we hold) and one version per logged edit (``message_edits``);
- ``observed_at`` — when the described situation was reported (``posted_at`` for v0, ``edited_at`` for edits);
- ``known_at`` — when *we* could have read this text: live messages ``received_at``; history (backfill)
  ``edited_at`` if the message was edited (Telegram history returns only the final text), else ``posted_at``;
  edits ``received_at``;
- ``superseded_at`` — ``known_at`` of the next version (as-of selection: ``known_at <= t < superseded_at``);
- ``late_edit`` — history text edited more than ``LATE_EDIT_SECONDS`` after posting: the final text may be
  stale/retrospective, so such versions are excluded from calibration.
"""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from airalert.drones import parse as dp
from airalert.drones.gazetteer import (
    KYIV_CITY,
    KYIV_LAT,
    KYIV_LON,
    OBLASTS,
    Gazetteer,
    Resolved,
    bearing_deg,
    haversine_km,
)

LATE_EDIT_SECONDS = 300
CONTEXT_MINUTES = 30  # homonyms are resolved by proximity to places mentioned this recently in the channel
CONTEXT_RATIO = 0.5  # ... if the nearest candidate is at most half as far as the second nearest
KYIV_FIRST_CHANNELS = {"kyiv_nebo"}  # bare names there are Kyiv districts/suburbs first

MENTION_COLUMNS = [
    "channel",
    "msg_id",
    "version",
    "line_no",
    "posted_at",
    "observed_at",
    "known_at",
    "superseded_at",
    "late_edit",
    "ingest_mode",
    "line_kind",
    "kind",
    "count",
    "plural",
    "rel",
    "oblast",
    "place_raw",
    "place_norm",
    "place_type",
    "lat",
    "lon",
    "match",
    "candidates",
    "via_raw",
    "via_norm",
    "via_lat",
    "via_lon",
    "heading_deg",
    "from_deg",
    "dist_to_kyiv_km",
    "bearing_to_kyiv_deg",
]
LINE_COLUMNS = [
    "channel",
    "msg_id",
    "version",
    "line_no",
    "posted_at",
    "known_at",
    "superseded_at",
    "late_edit",
    "line_kind",
    "oblast",
    "n_mentions",
    "text",
    "message",
]


@dataclass(frozen=True)
class Version:
    channel: str
    msg_id: int
    version: int
    text: str
    posted_at: pd.Timestamp
    observed_at: pd.Timestamp
    known_at: pd.Timestamp
    superseded_at: pd.Timestamp | None
    late_edit: bool
    ingest_mode: str


def _ts(s) -> pd.Timestamp | None:
    return None if s is None or (isinstance(s, float) and pd.isna(s)) else pd.Timestamp(s).tz_convert("UTC")


def versions(raw: pd.DataFrame, edits: pd.DataFrame) -> Iterable[Version]:
    """raw: raw_messages rows; edits: message_edits rows (with rowid order preserved)."""
    by_msg = {k: g for k, g in edits.groupby(["channel", "msg_id"], sort=False)} if len(edits) else {}
    for r in raw.itertuples(index=False):
        posted = _ts(r.posted_at)
        edited = _ts(r.edited_at)
        eds = by_msg.get((r.channel, r.msg_id))
        if r.ingest_mode == "live":
            known0, late = _ts(r.received_at), False
        elif edited is not None and eds is None:
            known0 = max(edited, posted)
            late = (edited - posted).total_seconds() > LATE_EDIT_SECONDS
        else:  # never edited, or edited only after we started collecting live (first-seen text is original)
            known0, late = posted, False
        chain = [(r.text, posted, known0, late)]
        if eds is not None:
            for e in eds.itertuples(index=False):
                rec = _ts(e.received_at)
                chain.append((e.new_text, _ts(e.edited_at) or rec, max(rec, chain[-1][2]), False))
        for i, (text, observed, known, late_) in enumerate(chain):
            sup = chain[i + 1][2] if i + 1 < len(chain) else None
            yield Version(
                r.channel, int(r.msg_id), i, text or "", posted, observed, known, sup, late_, r.ingest_mode
            )


def _scopes(m: dp.RawMention, channel: str) -> list[str | None]:
    if m.admin1 is not None:
        return [m.admin1]
    if channel in KYIV_FIRST_CHANNELS or m.rel == "bare":
        return [KYIV_CITY, None]
    return [None]


def _resolve(gz: Gazetteer, phrase: str | None, scopes: list[str | None]):
    if not phrase:
        return None
    if phrase.startswith("@"):  # oblast-only location from the parser
        code = phrase[1:]
        c = gz.centroid(code)
        name = OBLASTS.get(code, (code,))[0]
        return Resolved(
            name, c[0] if c else None, c[1] if c else None, code, "exact" if c else "none", "oblast", 1
        )
    best = None
    for sc in scopes:
        r = gz.resolve(phrase, sc)
        if r.lat is not None:
            return r
        if best is None or (best.match == "none" and r.match == "ambiguous"):
            best = r
    return best


def _by_context(r, context: list[tuple[float, float]]):
    """Pick the homonym nearest to the context points if it is clearly nearer than the runner-up."""
    if not r or r.match != "ambiguous" or not r.options or not context:
        return r
    dist = sorted(
        (min(haversine_km(p.lat, p.lon, la, lo) for la, lo in context), i) for i, p in enumerate(r.options)
    )
    if len(dist) == 1 or dist[0][0] <= CONTEXT_RATIO * dist[1][0]:
        p = r.options[dist[0][1]]
        return Resolved(p.name, p.lat, p.lon, p.admin1, "context", p.kind, r.candidates)
    return r


def build(raw: pd.DataFrame, edits: pd.DataFrame, gz: Gazetteer) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse every message version and resolve places. Within a channel, versions are processed in
    ``known_at`` order and only earlier-known places serve as homonym context (no look-ahead)."""
    line_rows, mention_rows = [], []
    recent: dict[str, deque] = defaultdict(deque)  # channel -> (known_at, lat, lon)
    for v in sorted(versions(raw, edits), key=lambda v: (v.channel, v.known_at, v.msg_id, v.version)):
        ctx = recent[v.channel]
        while ctx and (v.known_at - ctx[0][0]).total_seconds() > CONTEXT_MINUTES * 60:
            ctx.popleft()
        parsed = dp.parse_message(v.text, v.channel)
        first = {}  # pass 1: unambiguous places in this message are context for its homonyms
        for lp in parsed:
            for j, m in enumerate(lp.mentions):
                first[(lp.line_no, j)] = _resolve(gz, m.place_raw, _scopes(m, v.channel))
        msg_pts = [
            (r.lat, r.lon)
            for r in first.values()
            if r is not None and r.lat is not None and r.place_type != "oblast"
        ]
        context = msg_pts + [(la, lo) for _, la, lo in ctx]
        for lp in parsed:
            base = dict(
                channel=v.channel,
                msg_id=v.msg_id,
                version=v.version,
                line_no=lp.line_no,
                posted_at=v.posted_at,
                known_at=v.known_at,
                superseded_at=v.superseded_at,
                late_edit=v.late_edit,
            )
            line_rows.append(
                {
                    **base,
                    "line_kind": lp.line_kind,
                    "oblast": lp.admin1,
                    "n_mentions": len(lp.mentions),
                    "text": lp.text,
                    "message": v.text,
                }
            )
            for j, m in enumerate(lp.mentions):
                scopes = _scopes(m, v.channel)
                r = _by_context(first[(lp.line_no, j)], context)
                via = _by_context(_resolve(gz, m.via_raw, scopes), context) if m.via_raw else None
                lat, lon = (r.lat, r.lon) if r else (None, None)
                mention_rows.append(
                    {
                        **base,
                        "observed_at": v.observed_at,
                        "ingest_mode": v.ingest_mode,
                        "line_kind": lp.line_kind,
                        "kind": m.kind,
                        "count": m.count,
                        "plural": m.plural,
                        "rel": m.rel,
                        "oblast": (r.admin1 if r and r.admin1 else m.admin1),
                        "place_raw": m.place_raw,
                        "place_norm": r.place_norm if r and r.lat is not None else None,
                        "place_type": r.place_type if r else None,
                        "lat": lat,
                        "lon": lon,
                        "match": r.match if r else "none",
                        "candidates": r.candidates if r else 0,
                        "via_raw": m.via_raw,
                        "via_norm": via.place_norm if via and via.lat is not None else None,
                        "via_lat": via.lat if via else None,
                        "via_lon": via.lon if via else None,
                        "heading_deg": m.heading_deg,
                        "from_deg": m.from_deg,
                        "dist_to_kyiv_km": haversine_km(lat, lon, KYIV_LAT, KYIV_LON)
                        if lat is not None
                        else None,
                        "bearing_to_kyiv_deg": bearing_deg(lat, lon, KYIV_LAT, KYIV_LON)
                        if lat is not None
                        else None,
                    }
                )
        ctx.extend((v.known_at, la, lo) for la, lo in msg_pts)
    lines = pd.DataFrame(line_rows, columns=LINE_COLUMNS)
    mentions = pd.DataFrame(mention_rows, columns=MENTION_COLUMNS)
    for col in ("count",):
        mentions[col] = mentions[col].astype("Int64")
    for col in (
        "lat",
        "lon",
        "via_lat",
        "via_lon",
        "heading_deg",
        "from_deg",
        "dist_to_kyiv_km",
        "bearing_to_kyiv_deg",
    ):
        mentions[col] = mentions[col].astype("float64")
    return lines, mentions


def misses(mentions: pd.DataFrame) -> pd.DataFrame:
    """Unresolved place phrases (none/ambiguous), most frequent first."""
    m = mentions[mentions["lat"].isna() & ~mentions["place_raw"].str.startswith("@")]
    return (
        m.groupby(["place_raw", "match", "channel"], dropna=False)
        .agg(n=("msg_id", "size"), oblast=("oblast", lambda s: ",".join(sorted({str(x) for x in s if x}))))
        .reset_index()
        .sort_values("n", ascending=False)
    )


def read_journal(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_sql_query("SELECT * FROM raw_messages ORDER BY channel, msg_id", conn)
    edits = pd.read_sql_query("SELECT * FROM message_edits ORDER BY rowid", conn)
    return raw, edits


def report_md(lines: pd.DataFrame, mentions: pd.DataFrame, top: int = 50) -> str:
    """reports/drone_parse.md: line kinds, match quality, top unresolved place phrases."""
    out = ["# Drone channels: parser coverage", ""]
    out.append(f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC from the drones.sqlite journal.")
    out.append("")
    span = lines.groupby("channel")["posted_at"].agg(["min", "max", "size"])
    out += [
        "## Messages",
        "",
        "| channel | first | last | lines | message versions | late edits (>5 min) |",
        "|---|---|---|---|---|---|",
    ]
    for ch, r in span.iterrows():
        v = lines[lines["channel"] == ch].drop_duplicates(["msg_id", "version"])
        out.append(
            f"| {ch} | {r['min']:%Y-%m-%d} | {r['max']:%Y-%m-%d %H:%M} | {r['size']} | {len(v)} | {int(v['late_edit'].sum())} |"
        )
    kinds = lines.groupby(["line_kind", "channel"]).size().unstack(fill_value=0)
    out += [
        "",
        "## Line kinds",
        "",
        "| line kind | " + " | ".join(kinds.columns) + " |",
        "|---" * (len(kinds.columns) + 1) + "|",
    ]
    for k, r in kinds.sort_values(kinds.columns[0], ascending=False).iterrows():
        out.append(f"| {k} | " + " | ".join(str(int(x)) for x in r) + " |")
    m = mentions.groupby(["match", "channel"]).size().unstack(fill_value=0)
    share = mentions.assign(ok=mentions["lat"].notna()).groupby("channel")["ok"].mean()
    out += [
        "",
        "## Place resolution",
        "",
        "| match | " + " | ".join(m.columns) + " |",
        "|---" * (len(m.columns) + 1) + "|",
    ]
    for k, r in m.iterrows():
        out.append(f"| {k} | " + " | ".join(str(int(x)) for x in r) + " |")
    out.append(
        "| **with coordinates** | "
        + " | ".join(f"**{share.get(c, float('nan')):.1%}**" for c in m.columns)
        + " |"
    )
    out += [
        "",
        "`exact` — name as written; `lemma` — after inflection to the nominative; `fuzzy` — spelling variant / "
        "rapidfuzz ≥ 92 within the oblast; `context` — homonym chosen by proximity to places mentioned in the same "
        "message or the previous 30 min of the channel; `ambiguous` — several same-name places, no coordinates; "
        "`none` — not found. This is coverage, not accuracy: precision/recall come from `airalert drones-eval`.",
        "",
        f"## Top {top} unresolved place phrases",
        "",
        "Add them to `data/gazetteer/kyiv_local.csv` (Kyiv) or tell the parser what they are.",
        "",
        "| # | phrase | match | channel | n | oblast scope |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(misses(mentions).head(top).itertuples(index=False), 1):
        out.append(f"| {i} | {r.place_raw} | {r.match} | {r.channel} | {r.n} | {r.oblast} |")
    return "\n".join(out) + "\n"
