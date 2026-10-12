"""Data-quality checks. Each check returns a ``Check`` with status PASS / WARN / FAIL (or SKIP when
its input, e.g. Telegram data, is not available yet)."""

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd
import pandera.pandas as pa

from airalert import clean
from airalert.config import KYIV
from airalert.dataset import OFFICIAL_COLUMNS, VOLUNTEER_COLUMNS

STATUS_ORDER = {"PASS": 0, "SKIP": 1, "WARN": 2, "FAIL": 3}


@dataclass
class Check:
    id: int
    scope: str
    name: str
    status: str
    value: Any
    summary: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def worst(statuses: list[str]) -> str:
    return max(statuses, key=STATUS_ORDER.__getitem__) if statuses else "PASS"


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 3) if b else 0.0


# 1. Schema ---------------------------------------------------------------------------------------

_ALERT_SCHEMA = pa.DataFrameSchema(
    {
        "location": pa.Column(str, pa.Check.str_length(min_value=1)),
        "level": pa.Column(str, pa.Check.isin(clean.LEVELS)),
        "raion": pa.Column(str),
        "hromada": pa.Column(str),
        "started_at": pa.Column(clean.TS_DTYPE, nullable=False),
        "finished_at": pa.Column(clean.TS_DTYPE, nullable=True),
        "source": pa.Column(str),
        "flags": pa.Column(str),
    },
    strict=False,
)


def check_schema(raw: pd.DataFrame, norm: pd.DataFrame, scope: str, expected: list[str]) -> Check:
    problems: dict[str, Any] = {}
    if list(raw.columns) != expected:
        problems["columns"] = {"expected": expected, "actual": list(raw.columns)}
    try:
        _ALERT_SCHEMA.validate(norm, lazy=True)
    except pa.errors.SchemaErrors as e:
        fc = e.failure_cases
        problems["schema"] = (
            fc.groupby(["column", "check"]).size().astype(int).reset_index(name="n").to_dict("records")
        )
    bad_end = int((raw["finished_at"] != "").sum() - norm["finished_at"].notna().sum())
    if bad_end:
        problems["unparseable_finished_at"] = bad_end
    status = "FAIL" if problems else "PASS"
    summary = (
        "Колонки, типи (tz-aware UTC) і допустимі level — коректні."
        if not problems
        else "Є порушення схеми — див. details."
    )
    return Check(1, scope, "Схема й типи", status, len(problems), summary, problems)


# 2. Positive durations ---------------------------------------------------------------------------


def check_positive_duration(norm: pd.DataFrame, scope: str) -> Check:
    closed = norm[norm["finished_at"].notna()]
    bad = closed[closed["finished_at"] <= closed["started_at"]]
    share = _pct(len(bad), len(closed))
    status = "FAIL" if share > 0.1 else ("WARN" if len(bad) else "PASS")
    examples = bad.head(10)[["location", "level", "raion", "started_at", "finished_at"]].astype(str)
    return Check(
        2,
        scope,
        "started_at < finished_at",
        status,
        len(bad),
        f"{len(bad)} закритих тривог з нульовою/від'ємною тривалістю ({share}% з {len(closed)}).",
        {"share_pct": share, "examples": examples.to_dict("records")},
    )


# 3. Exact duplicates -----------------------------------------------------------------------------


def _duplicate_layout(raw: pd.DataFrame) -> dict:
    """Where do duplicated rows sit in the file? Detects 'whole prefix appended again'."""
    dup = raw.duplicated()
    if not dup.any():
        return {}
    first = int(dup.idxmax())
    n = first
    block = raw.iloc[first : first + n].reset_index(drop=True)
    head = raw.iloc[:n].reset_index(drop=True)
    m = min(len(block), len(head))
    same = float((block.iloc[:m].values == head.iloc[:m].values).all(axis=1).mean()) if m else 0.0
    return {
        "first_duplicate_row": first,
        "last_duplicate_row": int(dup[::-1].idxmax()),
        "prefix_rows": n,
        "prefix_last_started_at": raw.iloc[first - 1]["started_at"] if first else None,
        "rows_after_prefix_equal_to_prefix_share": round(same, 5),
        "duplicate_rows_by_year": raw.loc[dup, "started_at"].str[:4].value_counts().sort_index().to_dict(),
    }


def check_duplicates(raw: pd.DataFrame, loc_col: str, scope: str) -> Check:
    n, n_dedup = len(raw), len(raw.drop_duplicates())
    kyiv = raw[raw[loc_col] == KYIV]
    k, k_dedup = len(kyiv), len(kyiv.drop_duplicates())
    details = {
        "rows": n,
        "rows_after_dedup": n_dedup,
        "kyiv_rows": k,
        "kyiv_rows_after_dedup": k_dedup,
        "kyiv_duplicate_share_pct": _pct(k - k_dedup, k),
        "layout": _duplicate_layout(raw),
    }
    status = "WARN" if n_dedup < n else "PASS"
    summary = (
        f"{n} → {n_dedup} рядків ({_pct(n - n_dedup, n)}% дублів); Київ {k} → {k_dedup} "
        f"({details['kyiv_duplicate_share_pct']}%). Дублі прибираємо в clean.dedup."
    )
    lay = details["layout"]
    if lay:
        summary += (
            f" Дублі — суцільний блок: рядки {lay['first_duplicate_row']}…{lay['last_duplicate_row']} "
            f"повторюють перші {lay['prefix_rows']} рядків файлу (історія до "
            f"{lay['prefix_last_started_at']}), частка збігу "
            f"{lay['rows_after_prefix_equal_to_prefix_share']}."
        )
    return Check(3, scope, "Точні дублікати", status, n - n_dedup, summary, details)


# 4. Overlaps ---------------------------------------------------------------------------------------


def check_overlaps(dedup: pd.DataFrame, merged: pd.DataFrame, scope: str) -> Check:
    removed = len(dedup) - len(merged)
    kyiv_removed = int((dedup["location"] == KYIV).sum() - (merged["location"] == KYIV).sum())
    status = "WARN" if removed else "PASS"
    return Check(
        4,
        scope,
        "Перекриття інтервалів однієї локації",
        status,
        removed,
        f"Після дедупу злито {removed} рядків у перекриті інтервали (Київ: {kyiv_removed}); "
        "результат позначено прапорцем merged_overlap.",
        {
            "rows_before_merge": len(dedup),
            "rows_after_merge": len(merged),
            "kyiv_rows_merged_away": kyiv_removed,
            "merged_intervals": int(merged["flags"].str.contains("merged_overlap").sum()),
        },
    )


# 5. Durations ------------------------------------------------------------------------------------


def check_durations(dedup: pd.DataFrame, scope: str, naive: pd.Series | None = None) -> Check:
    closed = dedup[dedup["finished_at"].notna()]
    dur = (closed["finished_at"] - closed["started_at"]).dt.total_seconds()
    kyiv = closed["location"] == KYIV
    counts = {
        "lt_60s": int((dur < 60).sum()),
        "gt_12h": int((dur > 12 * 3600).sum()),
        "eq_3600s": int((dur == clean.AUTHOR_IMPUTED_SECONDS).sum()),
        "eq_1800s": int((dur == clean.VOLUNTEER_NAIVE_SECONDS).sum()),
        "kyiv_lt_60s": int(((dur < 60) & kyiv).sum()),
        "kyiv_gt_12h": int(((dur > 12 * 3600) & kyiv).sum()),
        "kyiv_eq_3600s": int(((dur == clean.AUTHOR_IMPUTED_SECONDS) & kyiv).sum()),
        "kyiv_eq_1800s": int(((dur == clean.VOLUNTEER_NAIVE_SECONDS) & kyiv).sum()),
        "rows": len(closed),
        "median_minutes": round(float(dur.median() / 60), 1),
        "p99_hours": round(float(dur.quantile(0.99) / 3600), 2),
    }
    if naive is not None:
        counts["naive_true"] = int(naive.sum())
        counts["kyiv_naive_true"] = int((naive & kyiv).sum())
        suspicious = counts["naive_true"]
        summary = (
            f"naive=True (кінець домальовано як старт+30 хв): {counts['naive_true']} "
            f"({_pct(counts['naive_true'], len(closed))}%), з них Київ {counts['kyiv_naive_true']}; "
        )
    else:
        suspicious = counts["eq_3600s"]
        summary = (
            f"Рівно 3600 с (імпутація автора): {counts['eq_3600s']}, з них Київ {counts['kyiv_eq_3600s']}; "
        )
    summary += (
        f"< 60 с: {counts['lt_60s']}; > 12 год: {counts['gt_12h']}; рівно 1800 с: {counts['eq_1800s']}."
    )
    share = _pct(suspicious + counts["lt_60s"] + counts["gt_12h"], len(closed))
    status = "WARN" if share > 0.1 else "PASS"
    counts["suspicious_share_pct"] = share
    return Check(5, scope, "Тривалості", status, share, summary, counts)


# 6. Freshness ------------------------------------------------------------------------------------


def check_freshness(dedup: pd.DataFrame, scope: str, now: pd.Timestamp, max_lag_days: float = 3) -> Check:
    last = dedup["started_at"].max()
    lag_days = round((now - last).total_seconds() / 86400, 2)
    status = "WARN" if lag_days > max_lag_days else "PASS"
    summary = f"Останній старт {last.isoformat()}, відставання {lag_days} дн."
    if status == "WARN":
        summary += (
            " Джерело застаріло: діру після цієї дати добираємо з Telegram air_alert_ua (шов C = 2026-09-01)."
        )
    return Check(
        6,
        scope,
        "Свіжість",
        status,
        lag_days,
        summary,
        {"max_started_at": last.isoformat(), "now": now.isoformat(), "lag_days": lag_days},
    )


# 7. Coverage gaps --------------------------------------------------------------------------------


def check_coverage(dedup: pd.DataFrame, scope: str) -> Check:
    days = dedup["started_at"].dt.floor("D")
    present = set(days.unique())
    full = pd.date_range(days.min(), days.max(), freq="D", tz="UTC")
    missing = [d.date().isoformat() for d in full if d not in present]
    status = "WARN" if missing else "PASS"
    return Check(
        7,
        scope,
        "Дні без жодної тривоги по Україні",
        status,
        len(missing),
        f"{len(missing)} днів (UTC) з {len(full)} без жодного запису."
        + (f" Перші: {', '.join(missing[:15])}" if missing else ""),
        {"missing_days": missing, "range": [full[0].date().isoformat(), full[-1].date().isoformat()]},
    )


# 8. Kyiv: official vs volunteer --------------------------------------------------------------------


def _hours(df: pd.DataFrame) -> pd.Series:
    return (df["finished_at"] - df["started_at"]).dt.total_seconds() / 3600


def kyiv_agreement(official: pd.DataFrame, volunteer: pd.DataFrame, tol: str = "2min") -> dict:
    """Monthly and yearly agreement for Kyiv between two cleaned (dedup+merged) sources."""
    o = official[official["location"] == KYIV].sort_values("started_at")
    v = volunteer[volunteer["location"] == KYIV].sort_values("started_at")
    end = min(o["started_at"].max(), v["started_at"].max())
    start = max(o["started_at"].min(), v["started_at"].min())
    o = o[(o["started_at"] >= start) & (o["started_at"] <= end)].copy()
    v = v[(v["started_at"] >= start) & (v["started_at"] <= end)].copy()

    m = pd.merge_asof(
        o[["started_at"]],
        v[["started_at"]].rename(columns={"started_at": "v_start"}),
        left_on="started_at",
        right_on="v_start",
        direction="nearest",
        tolerance=pd.Timedelta(tol),
    )
    o["matched"] = m["v_start"].notna().to_numpy()
    o["hours"] = _hours(o)
    v["hours"] = _hours(v)

    def agg(period: str) -> pd.DataFrame:
        po = o.groupby(o["started_at"].dt.tz_localize(None).dt.to_period(period))
        pv = v.groupby(v["started_at"].dt.tz_localize(None).dt.to_period(period))
        t = pd.DataFrame(
            {
                "n_official": po.size(),
                "n_volunteer": pv.size(),
                "hours_official": po["hours"].sum().round(1),
                "hours_volunteer": pv["hours"].sum().round(1),
                "median_min_official": (po["hours"].median() * 60).round(1),
                "median_min_volunteer": (pv["hours"].median() * 60).round(1),
                "start_match_pct": (po["matched"].mean() * 100).round(1),
            }
        ).fillna(0)
        t["hours_diff"] = (t["hours_official"] - t["hours_volunteer"]).round(1)
        t.index = t.index.astype(str)
        return t

    # Pair intervals by their END (±tol) to see how the two sources disagree on the START.
    e = pd.merge_asof(
        o[["finished_at", "started_at"]].dropna().sort_values("finished_at"),
        v[["finished_at", "started_at"]]
        .dropna()
        .sort_values("finished_at")
        .rename(columns={"finished_at": "v_end", "started_at": "v_start"}),
        left_on="finished_at",
        right_on="v_end",
        direction="nearest",
        tolerance=pd.Timedelta(tol),
    ).dropna()
    lag_min = (e["v_start"] - e["started_at"]).dt.total_seconds() / 60
    by_year = lag_min.groupby(e["started_at"].dt.year)
    end_pairing = {
        "end_match_pct": round(len(e) / len(o) * 100, 1) if len(o) else 0.0,
        "volunteer_start_later_than_2min_pct": round(float((lag_min > 2).mean() * 100), 1),
        "volunteer_start_lag_min_median": round(float(lag_min.median()), 2),
        "by_year": pd.DataFrame(
            {
                "pairs": by_year.size(),
                "vol_start_later_gt2min_pct": (by_year.apply(lambda s: (s > 2).mean()) * 100).round(1),
                "lag_min_p75": by_year.quantile(0.75).round(1),
                "lag_min_p90": by_year.quantile(0.9).round(1),
            }
        )
        .reset_index(names="year")
        .to_dict("records"),
    }

    monthly, yearly = agg("M"), agg("Y")
    top = monthly.reindex(monthly["hours_diff"].abs().sort_values(ascending=False).index).head(10)
    return {
        "window": [start.isoformat(), end.isoformat()],
        "tolerance": tol,
        "overall_start_match_pct": round(float(o["matched"].mean() * 100), 1),
        "total_hours_official": round(float(o["hours"].sum()), 1),
        "total_hours_volunteer": round(float(v["hours"].sum()), 1),
        "end_pairing": end_pairing,
        "yearly": yearly.reset_index(names="period").to_dict("records"),
        "monthly": monthly.reset_index(names="period").to_dict("records"),
        "top10_months_by_hours_diff": top.reset_index(names="period").to_dict("records"),
    }


def check_kyiv_agreement(official: pd.DataFrame, volunteer: pd.DataFrame) -> Check:
    a = kyiv_agreement(official, volunteer)
    hours_gap = _pct(abs(a["total_hours_official"] - a["total_hours_volunteer"]), a["total_hours_official"])
    status = "PASS" if a["overall_start_match_pct"] >= 90 and hours_gap <= 10 else "WARN"
    summary = (
        f"Вікно {a['window'][0][:10]}…{a['window'][1][:10]}: збіг стартів ±2 хв "
        f"{a['overall_start_match_pct']}%; сумарні години official {a['total_hours_official']} vs volunteer "
        f"{a['total_hours_volunteer']} (розрив {hours_gap}%). Якщо зіставити за КІНЦЕМ (±2 хв, "
        f"{a['end_pairing']['end_match_pct']}% тривог), волонтерський старт пізніший за офіційний більш ніж на "
        f"2 хв у {a['end_pairing']['volunteer_start_later_than_2min_pct']}% пар — розрив годин пояснюється "
        "запізнілими стартами eTryvoga, а не офіційним джерелом."
    )
    a["hours_gap_pct"] = hours_gap
    return Check(
        8,
        "kyiv: official vs volunteer",
        "Перехресна згода по Києву",
        status,
        a["overall_start_match_pct"],
        summary,
        a,
    )


# Runner ------------------------------------------------------------------------------------------


@dataclass
class DatasetFrames:
    official_raw: pd.DataFrame
    volunteer_raw: pd.DataFrame
    official: pd.DataFrame  # normalised, not deduplicated
    volunteer: pd.DataFrame
    official_dedup: pd.DataFrame
    volunteer_dedup: pd.DataFrame
    official_clean: pd.DataFrame  # dedup + merged overlaps
    volunteer_clean: pd.DataFrame


def prepare(official_raw: pd.DataFrame, volunteer_raw: pd.DataFrame) -> DatasetFrames:
    official = clean.normalize_official(official_raw)
    volunteer = clean.normalize_volunteer(volunteer_raw)
    od, vd = clean.dedup(official), clean.dedup(volunteer)
    return DatasetFrames(
        official_raw,
        volunteer_raw,
        official,
        volunteer,
        od,
        vd,
        clean.merge_overlaps(od),
        clean.merge_overlaps(vd),
    )


def run_dataset_checks(f: DatasetFrames, now: pd.Timestamp | None = None) -> list[Check]:
    now = now or pd.Timestamp.now(tz="UTC")
    naive = f.volunteer_dedup["flags"].str.contains("naive_end")
    return [
        check_schema(f.official_raw, f.official, "dataset_official", OFFICIAL_COLUMNS),
        check_schema(f.volunteer_raw, f.volunteer, "dataset_volunteer", VOLUNTEER_COLUMNS),
        check_positive_duration(f.official_dedup, "dataset_official"),
        check_positive_duration(f.volunteer_dedup, "dataset_volunteer"),
        check_duplicates(f.official_raw, "oblast", "dataset_official"),
        check_duplicates(f.volunteer_raw, "region", "dataset_volunteer"),
        check_overlaps(f.official_dedup, f.official_clean, "dataset_official"),
        check_overlaps(f.volunteer_dedup, f.volunteer_clean, "dataset_volunteer"),
        check_durations(f.official_dedup, "dataset_official"),
        check_durations(f.volunteer_dedup, "dataset_volunteer", naive=naive),
        check_freshness(f.official_dedup, "dataset_official", now),
        check_freshness(f.volunteer_dedup, "dataset_volunteer", now),
        check_coverage(f.official_dedup, "dataset_official"),
        check_coverage(f.volunteer_dedup, "dataset_volunteer"),
        check_kyiv_agreement(f.official_clean, f.volunteer_clean),
    ]


def pending_telegram_checks(reason: str) -> list[Check]:
    names = {
        9: "Парсер vs датасет на перекритті 2026-08-25…2026-09-07 (ціль ≥ 95%)",
        10: "parse_errors: кількість і топ причин (< 1%)",
        11: "Ідемпотентність backfill",
        12: "Live-затримка received_at − posted_at",
        13: "Шов C = 2026-09-01: немає дублів/пропусків",
    }
    return [Check(i, "telegram", n, "SKIP", None, reason) for i, n in names.items()]


# 9–13. Telegram ------------------------------------------------------------------------------------

PARSER_CHECK_LOCATIONS = [
    KYIV,
    "Kyivska oblast",
    "Zhytomyrska oblast",
    "Chernihivska oblast",
    "Cherkaska oblast",
    "Poltavska oblast",
]
OVERLAP = (pd.Timestamp("2026-08-25T06:00Z"), pd.Timestamp("2026-09-07T06:00Z"))


def _match_rate(
    ref: pd.DataFrame, test: pd.DataFrame, tol_s: float, keys: list[str]
) -> tuple[pd.Series, pd.DataFrame]:
    """For each ``ref`` interval: is there a ``test`` interval with the same keys and start/end within tol?"""
    m = ref.reset_index().merge(test, on=keys, suffixes=("", "_t"))
    ok = ((m["started_at_t"] - m["started_at"]).dt.total_seconds().abs() <= tol_s) & (
        (m["finished_at_t"] - m["finished_at"]).dt.total_seconds().abs() <= tol_s
    )
    matched = pd.Series(False, index=ref.index)
    matched.loc[m.loc[ok, "index"].unique()] = True
    return matched, m


def check_parser_vs_dataset(
    dataset_clean: pd.DataFrame, tg_official: pd.DataFrame, outages: list, tg_volunteer: pd.DataFrame
) -> Check:
    lo, hi = OVERLAP
    ref = dataset_clean[
        dataset_clean["location"].isin(PARSER_CHECK_LOCATIONS)
        & (dataset_clean["started_at"] >= lo)
        & (dataset_clean["finished_at"] <= hi)
    ]
    touches_outage = pd.Series(False, index=ref.index)
    for w in outages:
        touches_outage |= (ref["started_at"] < w.end) & (ref["finished_at"] > w.start)
    test = tg_official[
        (tg_official["alert_type"] == "air_raid") & ~tg_official["flags"].str.contains("source_gap")
    ]
    matched, _ = _match_rate(ref, test, 60, clean.LOCATION_KEYS)
    main = ref[~touches_outage]
    rate = _pct(matched[~touches_outage].sum(), len(main))
    rate_all = _pct(matched.sum(), len(ref))
    misses = ref[~matched][["location", "level", "raion", "started_at", "finished_at", "flags"]]
    misses = misses.assign(touches_outage=touches_outage[~matched]).astype(str)

    # Bonus: our єТривога parser vs our air_alert_ua parser for Kyiv (same window, ±1 min).
    k_off = test[(test["location"] == KYIV) & (test["started_at"] >= lo) & (test["finished_at"] <= hi)]
    k_vol = tg_volunteer[(tg_volunteer["alert_type"] == "air_raid") & (tg_volunteer["location"] == KYIV)]
    k_matched, km = _match_rate(k_off, k_vol, 60, clean.LOCATION_KEYS)
    km = km[(km["started_at_t"] - km["started_at"]).abs() <= pd.Timedelta("2min")]
    lag = (km["started_at_t"] - km["started_at"]).dt.total_seconds()

    status = "PASS" if rate >= 95 else "FAIL"
    return Check(
        9,
        "telegram: air_alert_ua vs dataset",
        "Парсер vs датасет на перекритті (±1 хв, ціль ≥ 95%)",
        status,
        rate,
        f"{rate}% з {len(main)} інтервалів датасету ({', '.join(PARSER_CHECK_LOCATIONS)}) знайдено в Telegram зі "
        f"стартом і кінцем ±1 хв; з урахуванням {int(touches_outage.sum())} інтервалів, що зачіпають збій "
        f"каналу, — {rate_all}%. Київ, єТривога vs air_alert_ua: {_pct(k_matched.sum(), len(k_off))}% "
        f"збігів ±1 хв, медіанне запізнення старту єТривоги {lag.median():.0f} с.",
        {
            "window": [lo.isoformat(), hi.isoformat()],
            "rate_excluding_outage_pct": rate,
            "rate_all_pct": rate_all,
            "dataset_intervals": len(ref),
            "touching_outage": int(touches_outage.sum()),
            "by_location": {
                loc: f"{int(matched[(ref['location'] == loc) & ~touches_outage].sum())}/"
                f"{int(((ref['location'] == loc) & ~touches_outage).sum())}"
                for loc in PARSER_CHECK_LOCATIONS
            },
            "misses": misses.to_dict("records"),
            "kyiv_volunteer_vs_official": {
                "official_intervals": len(k_off),
                "matched_pct": _pct(k_matched.sum(), len(k_off)),
                "volunteer_start_lag_s_median": round(float(lag.median()), 1) if len(lag) else None,
                "volunteer_start_lag_s_p95": round(float(lag.quantile(0.95)), 1) if len(lag) else None,
            },
        },
    )


def check_parse_errors(conn, channels: list[str]) -> Check:
    details, statuses, parts = {}, [], []
    for ch in channels:
        n_msg = conn.execute("SELECT COUNT(*) FROM raw_messages WHERE channel=?", (ch,)).fetchone()[0]
        rows = conn.execute("SELECT reason, msg_id FROM parse_errors WHERE channel=?", (ch,)).fetchall()
        parse_level = {m for r, m in rows if r not in ("end_without_start",)}
        reasons: dict[str, int] = {}
        for r, _ in rows:
            reasons[r.split(":")[0]] = reasons.get(r.split(":")[0], 0) + 1
        share = _pct(len(parse_level), n_msg)
        statuses.append("PASS" if share < 1 else "FAIL")
        top = conn.execute(
            "SELECT reason, COUNT(*) c FROM parse_errors WHERE channel=? GROUP BY reason ORDER BY c DESC LIMIT 10",
            (ch,),
        ).fetchall()
        details[ch] = {
            "messages": n_msg,
            "messages_unrecognised": len(parse_level),
            "unrecognised_pct": share,
            "errors_by_reason": reasons,
            "top_reasons": [{"reason": r, "n": c} for r, c in top],
        }
        parts.append(f"{ch}: нерозпізнаних {share}% з {n_msg}, причини {reasons}")
    return Check(
        10,
        "telegram",
        "parse_errors (нерозпізнані < 1%)",
        worst(statuses),
        max(d["unrecognised_pct"] for d in details.values()),
        "; ".join(parts)
        + ". end_without_start — відбої тривог, що почались до початку вибірки або під час збою каналу.",
        details,
    )


def check_idempotency(conn, channels: list[str], rebuild_fn) -> Check:
    """Re-insert every stored message (what a repeated backfill does) and rebuild twice."""
    from airalert.tg import store

    before = store.count(conn, "raw_messages")
    rows = [
        store.RawMessage(*r)
        for r in conn.execute(
            "SELECT channel, msg_id, posted_at, edited_at, text, received_at, ingest_mode FROM raw_messages"
        )
    ]
    inserted = store.insert_messages(conn, rows)
    after = store.count(conn, "raw_messages")
    snap = []
    for _ in range(2):
        for ch in channels:
            rebuild_fn(conn, ch)
        snap.append(
            conn.execute(
                "SELECT * FROM alerts ORDER BY channel, started_at, location, level, raion, hromada, alert_type"
            ).fetchall()
        )
    same = snap[0] == snap[1]
    ok = inserted == 0 and before == after and same
    return Check(
        11,
        "telegram",
        "Ідемпотентність backfill і детермінізм rebuild",
        "PASS" if ok else "FAIL",
        inserted,
        f"Повторна вставка {len(rows)} повідомлень додала {inserted} рядків ({before} → {after}); "
        f"два rebuild поспіль дають {'однакові' if same else 'РІЗНІ'} alerts.",
        {"raw_before": before, "raw_after": after, "reinserted": len(rows), "rebuild_identical": same},
    )


def check_live_latency(conn) -> Check:
    df = pd.read_sql_query(
        "SELECT channel, posted_at, received_at FROM raw_messages WHERE ingest_mode='live'", conn
    )
    if df.empty:
        return Check(
            12,
            "telegram",
            "Live-затримка received_at − posted_at",
            "SKIP",
            None,
            "Live-повідомлень ще немає (колектор не запускався).",
        )
    lat = (clean.to_utc(df["received_at"]) - clean.to_utc(df["posted_at"])).dt.total_seconds()
    # Catch-up after downtime is legitimately late; report steady state separately.
    steady = lat[lat <= 300]
    details = {
        "messages": len(df),
        "all": {
            "median_s": float(lat.median()),
            "p95_s": float(lat.quantile(0.95)),
            "max_s": float(lat.max()),
        },
        "steady_state_le_5min": {
            "messages": len(steady),
            "median_s": round(float(steady.median()), 1) if len(steady) else None,
            "p95_s": round(float(steady.quantile(0.95)), 1) if len(steady) else None,
        },
        "by_channel": {
            ch: {"messages": len(g), "median_s": float(g.median()), "p95_s": float(g.quantile(0.95))}
            for ch, g in lat.groupby(df["channel"])
        },
    }
    p95 = details["steady_state_le_5min"]["p95_s"]
    status = "PASS" if p95 is not None and p95 <= 30 else "WARN"
    return Check(
        12,
        "telegram",
        "Live-затримка received_at − posted_at",
        status,
        p95,
        f"{len(df)} live-повідомлень; медіана {lat.median():.1f} с, p95 {lat.quantile(0.95):.1f} с "
        f"(усталений режим ≤ 5 хв: p95 {p95} с; довші — дочитування після простою).",
        details,
    )


def check_seams(raw: pd.DataFrame, seam: pd.Timestamp) -> Check:
    """No interval of one location overlaps another one from a different source (double counting)."""
    keys = [*clean.LOCATION_KEYS, "alert_type"]
    d = raw.sort_values([*keys, "started_at"], kind="mergesort").reset_index(drop=True)
    prev_end = d.groupby(keys, sort=False)["finished_at"].shift()
    prev_src = d.groupby(keys, sort=False)["source"].shift()
    prev_end = prev_end.fillna(pd.Timestamp("2262-01-01", tz="UTC")).where(prev_src.notna())
    overlap = prev_src.notna() & (d["started_at"] < prev_end)
    cross = overlap & (prev_src != d["source"])
    examples = (
        d[cross][["location", "level", "raion", "alert_type", "source", "started_at"]].head(10).astype(str)
    )
    kyiv = d[(d["location"] == KYIV) & (d["alert_type"] == "air_raid")]
    near = kyiv[
        (kyiv["started_at"] >= seam - pd.Timedelta(hours=12))
        & (kyiv["started_at"] < seam + pd.Timedelta(hours=12))
    ]
    return Check(
        13,
        "build",
        "Шви між джерелами: немає дублів",
        "PASS" if not cross.any() else "FAIL",
        int(cross.sum()),
        f"Перекриттів між інтервалами різних джерел однієї локації: {int(cross.sum())} "
        f"(в межах одного джерела: {int((overlap & ~cross).sum())}). Біля шва {seam.isoformat()} у Києві "
        f"{len(near)} тривог: {', '.join(near['source'] + ' ' + near['started_at'].astype(str))}.",
        {
            "cross_source_overlaps": int(cross.sum()),
            "same_source_overlaps": int((overlap & ~cross).sum()),
            "examples": examples.to_dict("records"),
            "kyiv_near_seam": near[["source", "started_at", "finished_at"]].astype(str).to_dict("records"),
        },
    )
