# Drone pressure-field features

`data/processed/drone_features.parquet`: 18289 rows (5-min UTC grid, 2026-08-10 … 2026-10-12 12:00), as-of: row t uses only mentions with known_at ≤ t. Main source kudy_letyt; kpszsu only as auxiliary counters (parser recall 0.66 raw on the hold-out); motion model σ_θ=0.35, σ_v=1.0 (fitted on 2026-08-10…09-12).

## Leakage check

5 random busy grid points recomputed from data truncated at t: **5/5 bit-identical**.

## Lift on the calibration period (2026-08-10 … 2026-09-12)

Lift = P(Kyiv City alert starts within H | feature on) / P(… | off), grid points outside an alert only. Baseline: a raion alert in Kyiv oblast is on (as known at t). No modelling, single features.

| feature | share on | lift 15 | lift 30 | lift 60 | lift 120 |
|---|---|---|---|---|---|
| raion alert in Kyiv oblast (baseline) | 21.4% | 17.5 | 8.5 | 4.3 | 2.9 |
| n_tracks_r30+r80 > 0 | 11.4% | 5.0 | 4.0 | 3.1 | 2.5 |
| n_tracks_r150 > 0 | 10.6% | 4.4 | 3.7 | 2.7 | 2.1 |
| n_heading_kyiv > 0 | 18.0% | 4.4 | 3.6 | 2.8 | 2.2 |
| n_target_kyiv_ring > 0 | 3.2% | 3.1 | 2.3 | 2.0 | 1.9 |
| p_any_reach_60 > 0.2 | 9.6% | 5.8 | 4.6 | 3.3 | 2.4 |
| kyiv_nebo_over_city | 0.4% | 2.1 | 2.2 | 1.7 | 1.8 |
| mentions_last_15m > 0 | 24.1% | 3.3 | 2.9 | 2.3 | 1.9 |

### Incremental: only grid points with **no raion alert** in Kyiv oblast

Does the feature say something the raion alerts do not (yet)?

| feature | lift 15 | lift 30 | lift 60 | lift 120 |
|---|---|---|---|---|
| n_tracks_r30+r80 > 0 | 5.0 | 3.9 | 3.1 | 2.9 |
| n_tracks_r150 > 0 | 5.2 | 3.7 | 2.8 | 2.1 |
| n_heading_kyiv > 0 | 3.0 | 2.8 | 2.7 | 2.1 |
| n_target_kyiv_ring > 0 | 0.0 | 0.8 | 1.6 | 2.2 |
| p_any_reach_60 > 0.2 | 5.1 | 3.6 | 3.0 | 2.7 |
| kyiv_nebo_over_city | 10.0 | 3.0 | 1.1 | 1.7 |
| mentions_last_15m > 0 | 2.7 | 2.5 | 2.4 | 2.0 |

