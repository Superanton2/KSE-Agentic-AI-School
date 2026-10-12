# Parser labels

`sample.jsonl` — `airalert drones-sample --n 300`: a stratified sample of parsed lines (60% kudy_letyt,
25% kpszsu, 15% kyiv_nebo; rare line kinds / unresolved places over-sampled). Parser output is deliberately
not included. Fields: `id`, `channel`, `msg_id`, `version`, `line_no`, `posted_at`, `message` (whole message,
for context such as the oblast header), `line` (the line to label), `stratum` (for bookkeeping only).

`gold.jsonl` — one JSON object per sample `id`:

```json
{"id": "kudy_letyt:122375:0:3",
 "mentions": [{"place": "Олександрія", "oblast": "Кіровоградська", "kind": "drone_jet", "count": 1,
               "role": "target", "via": null}]}
```

Rules:
- `mentions: []` when the line names no place of a threat (headers, statuses like «Мінус», «Відбій», ads).
- `place` — the place in the nominative as on a map: «на Бровари» → «Бровари», «Шулявку» → «Шулявка»,
  «Умані» → «Умань». Kyiv districts by district name («Борщагівки» → «Борщагівка», «на Правому» → «Правий берег»).
  An oblast as the target («на Чернігівщину») → the oblast adjective: «Чернігівська».
  «повз X курсом на Y» → `place` = Y, `via` = X; only «повз X» → `place` = X, `role` = "via".
  Several targets on one line (kyiv_nebo «Бровари, Бориспіль») → several mentions.
- `oblast` — the oblast the place is in (header «Київщина:» → «Київська»; Kyiv city → «м. Київ»); for
  real-world exceptions use the true one (Славутич → «Київська» even under «Чернігівщина:»).
- `kind` — drone_jet («Реактивний БпЛА», 🏍), drone («БпЛА», 🛵, Молнія, Ланцет), missile («Бандероль», КР,
  ракета, «Швидкісна ціль», Циркон), ballistic, kab, unknown (kyiv_nebo bare names).
- `count` — the stated number («2х» → 2, «3 реактивних» → 3), else 1.

## Files

- `sample.jsonl` + `gold.jsonl` (300 lines) — labelled blind to the parser, then used to **fix** the parser
  (so metrics on it are optimistic; `reports/drone_parse_eval.md`).
- `holdout.jsonl` + `holdout_gold.jsonl` (150 different lines, `drones-sample --seed 20261012 --exclude
  data/labels/sample.jsonl`) — labelled blind *after* the fixes and not used for tuning: the honest estimate
  (`airalert drones-eval --gold data/labels/holdout_gold.jsonl --sample data/labels/holdout.jsonl
  --report drone_parse_eval_holdout`).
- Labeller for both: Claude (session of 2026-10-12), one known correction in gold.jsonl («Бромля» → Боромля).
