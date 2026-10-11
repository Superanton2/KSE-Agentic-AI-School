"""Render checks into reports/data_quality.{md,json}."""

import copy
import json
from pathlib import Path

import pandas as pd

from airalert.validate import Check, worst

_ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏸"}


def _table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return "_порожньо_\n"
    df = pd.DataFrame(rows)
    if columns:
        df = df[columns]
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    body = "".join("| " + " | ".join(str(v) for v in r) + " |\n" for r in df.itertuples(index=False))
    return head + body


def render_markdown(checks: list[Check], meta: dict, notes: list[str]) -> str:
    out = ["# Звіт якості даних — фаза 1\n"]
    out.append(
        f"Згенеровано: `{meta['generated_at']}` · загальний статус: **{worst([c.status for c in checks])}**\n"
    )
    for k, v in meta.items():
        if k != "generated_at":
            out.append(f"- **{k}**: `{v}`")
    out.append("\n## Зведення\n")
    out.append(
        "| # | Область перевірки | Перевірка | Статус | Значення | Коротко |\n|---|---|---|---|---|---|"
    )
    for c in sorted(checks, key=lambda c: (c.id, c.scope)):
        summary = c.summary.replace("|", "\\|")
        out.append(
            f"| {c.id} | {c.scope} | {c.name} | {_ICON[c.status]} {c.status} | {c.value} | {summary} |"
        )

    if notes:
        out.append("\n## Ключові висновки\n")
        out.extend(f"- {n}" for n in notes)

    out.append("\n## Деталі\n")
    for c in sorted(checks, key=lambda c: (c.id, c.scope)):
        out.append(f"### {c.id}. {c.name} — {c.scope} ({c.status})\n")
        out.append(c.summary + "\n")
        d = copy.deepcopy(c.details)
        if c.id == 8 and d:
            out.append("**По роках (Київ):**\n")
            out.append(_table(d.pop("yearly")))
            out.append("**Топ-10 місяців за розбіжністю сумарних годин:**\n")
            out.append(_table(d.pop("top10_months_by_hours_diff")))
            out.append(
                "**Зіставлення за кінцем тривоги: запізнення волонтерського старту (хв), по роках:**\n"
            )
            out.append(_table(d["end_pairing"].pop("by_year")))
            d.pop("monthly")
            out.append("Повна помісячна таблиця — у `data_quality.json`.\n")
        if c.id == 7 and d.get("missing_days"):
            days = d.pop("missing_days")
            out.append(f"Дні без записів ({len(days)}): {', '.join(days)}\n")
        if d:
            out.append("```json\n" + json.dumps(d, ensure_ascii=False, indent=2, default=str) + "\n```\n")
    return "\n".join(out) + "\n"


def write(
    checks: list[Check], meta: dict, reports_dir: Path, notes: list[str] | None = None
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    md, js = reports_dir / "data_quality.md", reports_dir / "data_quality.json"
    md.write_text(render_markdown(checks, meta, notes or []), encoding="utf-8")
    payload = {
        "meta": meta,
        "status": worst([c.status for c in checks]),
        "checks": [c.to_dict() for c in checks],
    }
    js.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return md, js
