"""Stratified line sample for manual labelling (``drones-sample``) and parser evaluation (``drones-eval``).

``data/labels/sample.jsonl`` — one line per sampled message line, *without* parser output (no anchoring):
``{"id", "channel", "msg_id", "version", "line_no", "posted_at", "message", "line"}``.

``data/labels/gold.jsonl`` — what a human (or Claude in chat) labels, one object per sampled id::

    {"id": "kudy_letyt:122375:0:3",
     "mentions": [{"place": "Олександрія", "oblast": "Кіровоградська", "kind": "drone_jet", "count": 1,
                   "role": "target", "via": null}]}

``mentions`` is ``[]`` for lines without a place (status, ads, headers). ``place`` is the nominative name as on
a map (Kyiv districts by district name; an oblast as a target -> oblast name, e.g. "Чернігівська").
``kind`` ∈ drone_jet, drone, missile, ballistic, kab, unknown. ``count`` is 1 unless stated.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from airalert.drones.gazetteer import OBLASTS, loose_key
from airalert.drones.normalize import key

SKIP_KINDS = {"header", "noise", "summary"}
CHANNEL_SHARE = {"kudy_letyt": 0.6, "kpszsu": 0.25, "kyiv_nebo": 0.15}
TARGETS = {"kudy_letyt": {"place_precision": 0.90, "place_recall": 0.85}}


def line_id(channel: str, msg_id: int, version: int, line_no: int) -> str:
    return f"{channel}:{msg_id}:{version}:{line_no}"


def _stratum(lines: pd.DataFrame, mentions: pd.DataFrame) -> pd.Series:
    """line kind x worst match on the line (none < ambiguous < fuzzy < context < lemma < exact)."""
    order = {"none": 0, "ambiguous": 1, "fuzzy": 2, "context": 3, "lemma": 4, "exact": 5}
    m = mentions.assign(r=mentions["match"].map(order), id=_ids(mentions)).groupby("id")["r"].min()
    inv = {v: k for k, v in order.items()}
    worst = _ids(lines).map(m).map(inv).fillna("no_mention")
    kind = lines["line_kind"].str.replace(r"^status:.*", "status", regex=True)
    return kind + "|" + worst


def _ids(df: pd.DataFrame) -> pd.Series:
    return (
        df["channel"]
        + ":"
        + df["msg_id"].astype(str)
        + ":"
        + df["version"].astype(str)
        + ":"
        + df["line_no"].astype(str)
    )


def sample(
    lines: pd.DataFrame, mentions: pd.DataFrame, messages: dict, n: int, seed: int = 20260812
) -> list[dict]:
    """Stratified sample: channel shares as in CHANNEL_SHARE; within a channel every stratum gets
    at least ``max(2, n_channel // 40)`` lines (rare failure modes are over-sampled), the rest proportional."""
    rng = np.random.default_rng(seed)
    lines = lines[~lines["line_kind"].isin(SKIP_KINDS) & ~lines["late_edit"]].copy()
    lines["stratum"] = _stratum(lines, mentions)
    picked = []
    quota = {ch: round(n * share) for ch, share in CHANNEL_SHARE.items()}
    quota["kudy_letyt"] += n - sum(quota.values())
    for ch in CHANNEL_SHARE:
        pool = lines[lines["channel"] == ch]
        k = quota[ch]
        if pool.empty or k == 0:
            continue
        sizes = pool["stratum"].value_counts()
        floor = max(2, k // 40)
        alloc = {s: min(c, floor) for s, c in sizes.items()}
        rest = k - sum(alloc.values())
        if rest > 0:
            extra = (sizes - pd.Series(alloc)).clip(lower=0)
            prop = (extra / extra.sum() * rest).round().astype(int) if extra.sum() else extra * 0
            for s, c in prop.items():
                alloc[s] += min(int(c), int(extra[s]))
        # rounding: top up / trim to exactly k (largest strata first)
        order = sizes.index.tolist()
        while sum(alloc.values()) < min(k, len(pool)):
            s = next(s for s in order if alloc[s] < sizes[s])
            alloc[s] += 1
            order = order[1:] + order[:1]
        while sum(alloc.values()) > k:
            s = max(alloc, key=alloc.get)
            alloc[s] -= 1
        for s, c in alloc.items():
            grp = pool[pool["stratum"] == s]
            idx = rng.choice(len(grp), size=min(c, len(grp)), replace=False)
            picked.append(grp.iloc[np.sort(idx)])
    out = pd.concat(picked).sort_values(["channel", "posted_at", "msg_id", "line_no"])
    return [
        {
            "id": line_id(r.channel, r.msg_id, r.version, r.line_no),
            "channel": r.channel,
            "msg_id": int(r.msg_id),
            "version": int(r.version),
            "line_no": int(r.line_no),
            "posted_at": pd.Timestamp(r.posted_at).isoformat(),
            "message": messages[(r.channel, int(r.msg_id), int(r.version))],
            "line": r.text,
            "stratum": r.stratum,
        }
        for r in out.itertuples(index=False)
    ]


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- evaluation

_OBLAST_KEY = {key(name): code for code, (name, aliases) in OBLASTS.items()} | {
    key(a): code for code, (_, aliases) in OBLASTS.items() for a in aliases
}


def _oblast(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = str(x)
    return (
        s if s.startswith("UA.") else _OBLAST_KEY.get(key(s.replace(" область", "")), _OBLAST_KEY.get(key(s)))
    )


def _place_key(x) -> str | None:
    """Names compare without apostrophes: GeoNames "Пятихатки" == "П'ятихатки"."""
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else loose_key(key(str(x)))


@dataclass
class FieldScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    w: list = field(default_factory=lambda: [0.0, 0.0, 0.0])  # population-weighted tp, fp, fn

    def add(self, kind: str, weight: float = 1.0) -> None:
        setattr(self, kind, getattr(self, kind) + 1)
        self.w[("tp", "fp", "fn").index(kind)] += weight

    @staticmethod
    def _pr(tp, fp, fn) -> tuple[float, float]:
        return (tp / (tp + fp) if tp + fp else float("nan"), tp / (tp + fn) if tp + fn else float("nan"))

    @property
    def precision(self) -> float:
        return self._pr(self.tp, self.fp, self.fn)[0]

    @property
    def recall(self) -> float:
        return self._pr(self.tp, self.fp, self.fn)[1]

    @property
    def weighted(self) -> tuple[float, float]:
        return self._pr(*self.w)


def strata_sizes(lines: pd.DataFrame, mentions: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Population size of every (channel, stratum) — to re-weight metrics measured on the stratified sample."""
    lines = lines[~lines["line_kind"].isin(SKIP_KINDS) & ~lines["late_edit"]]
    st = _stratum(lines, mentions)
    return {
        ch: {k: int(v) for k, v in st[lines["channel"] == ch].value_counts().items()} for ch in CHANNEL_SHARE
    }


def weights_for(sample_rows: list[dict], sizes: dict[str, dict[str, int]]) -> dict[str, float]:
    """id -> how many population lines this sampled line stands for (stratum size / sampled in stratum)."""
    n = Counter((r["channel"], r["stratum"]) for r in sample_rows)
    return {
        r["id"]: sizes.get(r["channel"], {}).get(r["stratum"], 0) / n[(r["channel"], r["stratum"])]
        for r in sample_rows
    }


def evaluate(
    gold: list[dict], mentions: pd.DataFrame, weights: dict[str, float] | None = None
) -> tuple[pd.DataFrame, list[dict]]:
    """Per channel: place precision/recall (predicted place with coordinates vs gold place, by name), and,
    on matched pairs, kind / count / oblast accuracy (also as precision/recall over all mentions).
    ``w_precision``/``w_recall`` re-weight the stratified sample to the whole stream (see :func:`weights_for`)."""
    pred = mentions.assign(id=_ids(mentions))
    pred = pred[pred["lat"].notna()]
    by_id = {i: g for i, g in pred.groupby("id")}
    scores: dict[tuple[str, str], FieldScore] = {}
    errors = []

    def add(ch, f, kind, w):
        scores.setdefault((ch, f), FieldScore()).add(kind, w)

    for g in gold:
        ch = g["id"].split(":")[0]
        w = (weights or {}).get(g["id"], 1.0)
        gm = list(g.get("mentions") or [])
        pm = by_id.get(g["id"])
        pm = [] if pm is None else pm.to_dict("records")
        unmatched = list(range(len(pm)))
        for gmen in gm:
            gk = _place_key(gmen.get("place"))
            j = next((j for j in unmatched if _place_key(pm[j]["place_norm"]) == gk), None)
            if j is None:
                for f in ("place", "kind", "count", "oblast"):
                    add(ch, f, "fn", w)
                errors.append({"id": g["id"], "error": "missed", "gold": gmen, "pred": None})
                continue
            unmatched.remove(j)
            p = pm[j]
            add(ch, "place", "tp", w)
            checks = {
                "kind": (gmen.get("kind") or "unknown") == p["kind"],
                "count": int(gmen.get("count") or 1) == int(p["count"] if pd.notna(p["count"]) else 1),
                "oblast": _oblast(gmen.get("oblast")) in (None, _oblast(p["oblast"])),
            }
            for f, ok in checks.items():
                if ok:
                    add(ch, f, "tp", w)
                else:
                    add(ch, f, "fp", w)
                    add(ch, f, "fn", w)
                    errors.append({"id": g["id"], "error": f, "gold": gmen, "pred": _brief(p)})
        for j in unmatched:
            for f in ("place", "kind", "count", "oblast"):
                add(ch, f, "fp", w)
            errors.append({"id": g["id"], "error": "spurious", "gold": gm, "pred": _brief(pm[j])})
    rows = []
    for (ch, f), s in sorted(scores.items()):
        wp, wr = s.weighted
        rows.append(
            {
                "channel": ch,
                "field": f,
                "tp": s.tp,
                "fp": s.fp,
                "fn": s.fn,
                "precision": round(s.precision, 3),
                "recall": round(s.recall, 3),
                "w_precision": round(wp, 3),
                "w_recall": round(wr, 3),
            }
        )
    return pd.DataFrame(rows), errors


def _brief(p: dict) -> dict:
    return {
        k: (None if pd.isna(p[k]) else p[k])
        for k in ("place_raw", "place_norm", "oblast", "kind", "count", "match", "rel")
    }


def meets_targets(table: pd.DataFrame) -> list[str]:
    """Human-readable list of missed targets (empty = all met)."""
    missed = []
    for ch, t in TARGETS.items():
        row = table[(table["channel"] == ch) & (table["field"] == "place")]
        if row.empty:
            missed.append(f"{ch}: no gold labels")
            continue
        p, r = row["w_precision"].iloc[0], row["w_recall"].iloc[0]  # population-weighted
        if not p >= t["place_precision"]:
            missed.append(f"{ch}: place precision {p:.3f} < {t['place_precision']}")
        if not r >= t["place_recall"]:
            missed.append(f"{ch}: place recall {r:.3f} < {t['place_recall']}")
    return missed


def error_summary(errors: list[dict]) -> Counter:
    return Counter((e["id"].split(":")[0], e["error"]) for e in errors)


def md_table(df: pd.DataFrame) -> str:
    rows = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    rows += ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)
