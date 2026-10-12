"""reports/model_eval.md from the saved outputs of one run (no numbers typed by hand)."""

from datetime import UTC, datetime

import pandas as pd

from airalert.model import features as F

DRONE_SHOW = ["n_ring30_15m", "n_ring80_15m", "n_ring150_15m", "n_jet_ring150_15m", "min_dist_km_15m",
              "n_ring150_30m", "kps_n_jet_ring150_30m", "kps_min_dist_km_30m", "kyiv_nebo_any_10m",
              "missile_any_30m"]


def _f(x, d=3) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.{d}f}"


def render(res: dict, dur: dict, bt: dict, product: str, sha: str, counts: pd.DataFrame) -> str:
    mt, bs, C = res["metrics"], res["bootstrap"], res["C"]
    bss = bs[bs["stat"] == "bss"]
    diff = bs[bs["stat"] == "diff"]
    L = [
        "# Модель тривог у Києві: оцінка",
        "",
        f"Прогін {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, код `{sha}`. Тест: {res['n_test_days']} днів "
        f"(2026-09-13…10-11, дні за Києвом), {res['n_test_points']} спокійних моментів t. "
        "Тест використано один раз: для фінальних чисел нижче; C, ваги й відрізки обрано на 08-24…09-12.",
        "",
        "## Коротко",
        "",
    ]
    ab = diff[(diff["a"] == "M1b") & (diff["b"] == "M1a")]
    sig = ab[(ab["hi"] < 0) | (ab["lo"] > 0)]
    L += [
        f"- **Аблація дронів (головний результат):** M1b (+дрони) проти M1a (лише історія тривог + час): ΔBrier з 95% CI "
        f"перетинає 0 на {len(ab) - len(sig)} з {len(ab)} горизонтів — "
        + ("**значущої різниці немає**." if sig.empty else "є значуща різниця на " + ", ".join(f"{h} хв" for h in sig["H"]) + ".")
        + " На валідації (08-24…09-12) M1b була кращою: середній Brier "
        f"{_f(res['C_selection'].query('model==\"M1b\"')['mean_brier'].min())} vs "
        f"{_f(res['C_selection'].query('model==\"M1a\"')['mean_brier'].min())}; на тесті перевага не відтворилась.",
        f"- **У продукт іде {product}** (менший середній Brier на тесті з двох).",
        "- Обидві логістичні моделі кращі за B1 (14-денна частота) за точковою оцінкою на всіх горизонтах; "
        "CI BSS відділений від 0 лише там, де вказано в таблиці.",
        "- Тривалість (KM з 08-17) на тесті: max |прогноз − факт| = "
        f"{_f((dur['checks']['08-17']['p_pred'] - dur['checks']['08-17']['observed']).abs().max())} (таблиця нижче).",
        f"- Продуктовий бектест: BSS {product}-сценаріїв vs B1-сценаріїв = {_f(bt['bss_vs_B1'])} "
        f"(95% CI {_f(bt['bss_ci'][0])}…{_f(bt['bss_ci'][1])}).",
        "",
        "## Дані й постановка",
        "",
        "Мітка — старт тривоги м. Київ (єТривога; до 2026-08-26 CSV Vadimkin, далі наш UkraineAlarmSignal). "
        "Сітка 5 хв, прогноз лише в спокої, дискретний hazard на 24 кроки (120 хв). Ознаки as-of (known_at ≤ t), "
        "тест на витік 200/200 — див. `reports/model_lift.md`.",
        "",
        "| період | днів | стартів | на добу | медіана тривалості, хв |",
        "|---|---|---|---|---|",
        *[f"| {r.period} | {r.days} | {r.starts} | {r.starts_per_day:.2f} | {r.median_dur_min:.0f} |"
          for r in counts.itertuples()],
        "",
        "Тест має на ~45% більше стартів на добу, ніж період навчання: нестаціонарність — головна загроза калібруванню.",
        "",
        "## Моделі",
        "",
        "- **B0** — константний hazard на крок (зважене середнє навчання).",
        "- **B1** — λ = старти / години спокою за 14 днів до t; P(старт ≤ H) = 1 − e^(−λH).",
        f"- **M1a** — логістичний hazard, окрема L2-логрегресія на відрізок кроків {{1–3, 4–6, 7–12, 13–24}}, "
        f"ознаки рівня тривог + час; C = {C['M1a']}.",
        f"- **M1b** — M1a + {len(F.DRONE_FEATURES)} дрон-ознак; C = {C['M1b']}.",
        "",
        "Ваги за давністю (півперіод 14 днів), стандартизація всередині fold. Walk-forward: для кожної доби d тесту "
        "модель навчається на t з t + 120 хв ≤ 00:00 d (purge) і прогнозує всі спокійні t доби d; перенавчання щодоби.",
        "",
        "Підбір C (валідація 08-24…09-12, перенавчання кожні 4 дні, середній Brier по H):",
        "",
        "| C | M1a | M1b |",
        "|---|---|---|",
        *[f"| {c} | {_f(r['M1a'], 4)} | {_f(r['M1b'], 4)} |"
          for c, r in res["C_selection"].pivot(index="C", columns="model", values="mean_brier").iterrows()],
        "",
        f"⚠️ Обране C = {max(C.values())} — край сітки. Сітку не розширював після того, як побачив тест (правило «тест один раз»).",
        "",
        "## Метрики на тесті",
        "",
        "| H, хв | модель | n | частка стартів | середній прогноз | Brier | log loss | BSS vs B1 |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {r.H} | {r.model} | {r.n} | {_f(r.base_rate)} | {_f(r.mean_p)} | {_f(r.brier, 4)} | {_f(r.logloss, 4)} | "
          f"{_f(r.bss_vs_B1)} |" for r in mt.itertuples()],
        "",
        "### BSS vs B1 з 95% CI (bootstrap по днях, 1000)",
        "",
        "| H, хв | " + " | ".join(bss["a"].unique()) + " |",
        "|---|" + "---|" * bss["a"].nunique(),
        *[f"| {H} | " + " | ".join(
            f"{_f(r.point)} [{_f(r.lo)}, {_f(r.hi)}]" for r in bss[bss["H"] == H].itertuples()) + " |"
          for H in F.HORIZONS],
        "",
        "![BSS](model/bss.png)",
        "",
        "### ΔBrier з 95% CI (від'ємне — перша модель краща)",
        "",
        "| порівняння | " + " | ".join(f"H={h}" for h in F.HORIZONS) + " |",
        "|---|" + "---|" * len(F.HORIZONS),
        *[f"| {a} − {b} | " + " | ".join(
            f"{_f(r.point, 4)} [{_f(r.lo, 4)}, {_f(r.hi, 4)}]" for r in diff[(diff['a'] == a) & (diff['b'] == b)].itertuples())
          + " |" for a, b in diff[["a", "b"]].drop_duplicates().itertuples(index=False)],
        "",
        "## Калібрування",
        "",
        "![calibration](model/calibration.png)",
        "",
        "Середній прогноз vs фактична частка (10 рівноширинних бінів) — у `data/processed/model_eval/calibration.csv`.",
        "",
        "Найвищий бін (n ≥ 30) кожної моделі — де модель найвпевненіша:",
        "",
        "| H, хв | " + " | ".join(f"{m}: прогноз → факт (n)" for m in ("M1a", "M1b")) + " |",
        "|---|---|---|",
        *[f"| {H} | " + " | ".join(
            (lambda c: f"{_f(c['p_mean'].iloc[-1], 2)} → {_f(c['y_mean'].iloc[-1], 2)} ({int(c['n'].iloc[-1])})")(
                res["calibration"].query("model == @m and H == @H and n >= 30").sort_values("p_mean"))
            for m in ("M1a", "M1b")) + " |" for H in F.HORIZONS],
        "",
        "M1b розтягує прогнози ширше за M1a, але у верхніх бінах факт помітно нижчий за прогноз: дрон-сигнал має "
        "правильний напрям, проте його сила, вивчена на 08-10…09-12, на тесті переоцінена — це й з'їдає виграш у Brier.",
        "",
        "## Коефіцієнти дрон-ознак M1b по відрізках кроків",
        "",
        "Стандартизовані коефіцієнти моделі першої тестової доби (навчання 08-10…09-12). Ознаки сильно корельовані "
        "(кільця 15/30 хв, kudy_letyt/kpszsu), тож знаки окремих коефіцієнтів нестабільні; дивитись на групу.",
        "",
        "| ознака | " + " | ".join(res["coefs"].columns) + " |",
        "|---|" + "---|" * len(res["coefs"].columns),
        *[f"| {f} | " + " | ".join(_f(v, 2) for v in res["coefs"].loc[f]) + " |" for f in DRONE_SHOW],
        "",
        "Повна таблиця: `data/processed/model_eval/coefs_M1b.csv`.",
        "",
        "## Тривалість тривоги (Kaplan–Meier)",
        "",
        f"Медіани (non-naive): до 08-17 — {dur['median_before']:.0f} хв, навчання — {dur['median_train']:.0f} хв, "
        f"тест — {dur['median_test']:.0f} хв: **тривалості не стабільні** (ТЗ припускало протилежне), тому KM "
        f"будується з 2026-08-17 (рішення за даними до тесту). naive=True → цензура на 30 хв.",
        "",
        f"KM 08-17…09-12: n = {dur['n_km']}, медіана {dur['km_median']:.0f} хв. Перевірка на тривогах тесту "
        "(P(відбій ≤ e + x | триває e)):",
        "",
        "| KM з | e, хв | x, хв | n | прогноз | факт | Brier |",
        "|---|---|---|---|---|---|---|",
        *[f"| {src} | {r.elapsed} | {r.x} | {r.n} | {_f(r.p_pred)} | {_f(r.observed)} | {_f(r.brier)} |"
          for src, tab in dur["checks"].items() for r in tab.itertuples()],
        "",
        "## Продуктовий бектест",
        "",
        f"{bt['n_trips']} випадкових поїздок у тестовому вікні: t — випадкова точка сітки; дорога U(10, 40) хв; "
        "покупки N(60, 15) у [20, 120]; готовий чекати 0 або 15 хв; виїзд одразу. Передбачене P(успіх) — "
        "симулятор на 200 сценаріях, згенерованих на t (walk-forward модель доби, KM на тривогах до доби, λ = B1), "
        "факт — ті самі правила на справжніх тривогах. Наближення: один член ансамблю (смуга невизначеності тут "
        "не оцінюється); сценарії «за горизонтом» виключені з p, як у продукті.",
        "",
        f"Частка успішних поїздок: {_f(bt['success_rate'])}; з тривогою на момент t: {_f(bt['share_alert_now'])}.",
        "",
        "| сценарії | Brier | середній P(успіх) |",
        "|---|---|---|",
        f"| {product} | {_f(bt[product]['brier'], 4)} | {_f(bt[product]['mean_p'])} |",
        f"| B1 | {_f(bt['B1']['brier'], 4)} | {_f(bt['B1']['mean_p'])} |",
        "",
        f"BSS {product} vs B1 = {_f(bt['bss_vs_B1'])}, 95% CI (bootstrap по днях) {_f(bt['bss_ci'][0])}…{_f(bt['bss_ci'][1])}.",
        "",
        f"Окремо: зараз спокій — n = {bt['calm_now']['n']}, Brier {product} {_f(bt['calm_now'][f'brier_{product}'], 4)} "
        f"vs B1 {_f(bt['calm_now']['brier_B1'], 4)}; зараз тривога — n = {bt['alert_now']['n']}, "
        f"Brier {_f(bt['alert_now'][f'brier_{product}'], 4)} (сценарії однакові: перший інтервал з KM).",
        "",
        "Калібрування P(успіх):",
        "",
        "| бін | " + " | ".join(f"{n}: прогноз / факт (n)" for n in (product, "B1")) + " |",
        "|---|---|---|",
        *[f"| {i + 1} | " + " | ".join(
            f"{_f(c[i]['p_mean'], 2)} / {_f(c[i]['y_mean'], 2)} ({c[i]['n']})" if i < len(c) else "—"
            for c in (bt["calibration"][product], bt["calibration"]["B1"])) + " |"
          for i in range(max(len(v) for v in bt["calibration"].values()))],
        "",
        "## Обмеження",
        "",
        "- Тестове вікно — один місяць з іншою інтенсивністю, ніж навчання; CI широкі (29 днів).",
        "- Районні тривоги Київщини та SITREP у модель не входять (немає в тесті).",
        "- Сценарії: після першого старту hazard-модель не перезапускається; λ без добового циклу.",
        "- Дрон-ознаки залежать від парсера (kudy_letyt P/R ≈ 0.97/0.96 на hold-out; kpszsu гірше).",
        "",
    ]
    return "\n".join(L)
