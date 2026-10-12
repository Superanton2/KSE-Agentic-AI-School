# Phase 4 · step 1: grid, labels, features, quick lift

Run 2026-10-12 14:39 UTC, code `cce58dd`. Grid: 5-min UTC, 2026-08-10 00:00 … 2026-10-12 14:35 (18320 points, 13551 calm). Data end (last collector heartbeat) 2026-10-12 14:35 UTC.

## Label source

Kyiv City air raids from eTryvoga only: Vadimkin volunteer CSV before 2026-08-26 00:00 UTC, our `UkraineAlarmSignal` backfill/live after (it starts 2026-08-25 20:54 UTC). Overlaps merged. In the CSV part known_at = event time (train only).

Robustness vs official (starts outside official outages, ±2 min):

| window | eTryvoga starts | official starts | eTryvoga matched | official matched |
|---|---|---|---|---|
| 08-10…08-26 | 42 | 41 | 22 | 22 |
| 08-26…09-07 | 50 | 50 | 47 | 47 |

Before the seam only 22 of 42 match within ±2 min (±10 min: 26): the CSV times are coarser/shifted, the counts agree.

## Starts per period (Kyiv days)

| period | days | starts | starts/day | median duration, min (non-naive) | naive ends |
|---|---|---|---|---|---|
| before regime change (2026-06-01…08-16) | 77 | 159 | 2.06 | 20 | 33 |
| train/selection (08-10…09-12) | 34 | 173 | 5.09 | 30 | 7 |
| test (09-13…10-11) | 29 | 213 | 7.34 | 35 | 0 |
| after test (10-12…) | 1 | 2 | 2.00 | 67 | 0 |

## Leakage test

200 random grid points: all sources cut at known_at ≤ t, features recomputed — **200/200 bit-identical**.

## Quick lift on the training period (08-10…09-12, calm grid points)

Base rates (calm t): P(start ≤ 15) = 0.065, P(start ≤ 30) = 0.122, P(start ≤ 60) = 0.220, P(start ≤ 120) = 0.351; n = 7766.

P(start ≤ H | feature > 0) / P(start ≤ H | feature = 0); in brackets P(… | > 0).

| feature | share > 0 | n > 0 | H=15 | H=30 | H=60 | H=120 |
|---|---|---|---|---|---|---|
| n_ring30_15m | 3.3% | 255 | 3.33 (0.20) | 2.56 (0.30) | 2.15 (0.45) | 2.06 (0.70) |
| n_ring80_15m | 6.3% | 486 | 5.18 (0.27) | 3.73 (0.39) | 2.62 (0.52) | 2.27 (0.74) |
| n_ring150_15m | 11.5% | 896 | 5.34 (0.23) | 4.56 (0.40) | 3.01 (0.54) | 2.33 (0.71) |
| n_ring300_15m | 14.4% | 1117 | 2.97 (0.15) | 2.86 (0.28) | 2.26 (0.42) | 1.94 (0.60) |
| n_target_ring30_15m | 3.2% | 252 | 3.30 (0.20) | 2.56 (0.30) | 2.16 (0.46) | 2.07 (0.70) |
| n_jet_ring150_15m | 11.1% | 859 | 5.60 (0.24) | 4.66 (0.41) | 3.20 (0.57) | 2.52 (0.76) |
| n_ring30_30m | 7.1% | 553 | 3.04 (0.17) | 2.59 (0.28) | 2.16 (0.44) | 2.08 (0.68) |
| n_ring80_30m | 10.1% | 782 | 4.14 (0.20) | 3.42 (0.34) | 2.60 (0.49) | 2.35 (0.73) |
| n_ring150_30m | 16.5% | 1280 | 5.49 (0.20) | 4.44 (0.35) | 3.03 (0.50) | 2.45 (0.69) |
| n_ring300_30m | 20.0% | 1554 | 3.12 (0.14) | 2.90 (0.26) | 2.35 (0.41) | 2.00 (0.58) |
| n_target_ring30_30m | 7.1% | 548 | 3.07 (0.17) | 2.61 (0.29) | 2.18 (0.44) | 2.09 (0.68) |
| n_jet_ring150_30m | 16.0% | 1239 | 5.06 (0.20) | 4.20 (0.34) | 3.09 (0.51) | 2.63 (0.73) |
| kps_n_ring30_30m | 7.7% | 596 | 3.42 (0.19) | 2.80 (0.30) | 2.44 (0.48) | 2.29 (0.73) |
| kps_n_ring80_30m | 9.8% | 762 | 5.23 (0.24) | 4.04 (0.38) | 2.96 (0.55) | 2.48 (0.76) |
| kps_n_ring150_30m | 14.8% | 1147 | 3.43 (0.16) | 2.69 (0.26) | 2.11 (0.40) | 1.69 (0.54) |
| kps_n_ring300_30m | 27.1% | 2107 | 2.15 (0.11) | 2.09 (0.20) | 1.67 (0.31) | 1.45 (0.45) |
| kps_n_target_ring30_30m | 7.2% | 558 | 3.38 (0.19) | 2.80 (0.30) | 2.43 (0.48) | 2.30 (0.74) |
| kps_n_jet_ring150_30m | 18.2% | 1417 | 6.18 (0.21) | 4.57 (0.34) | 3.22 (0.50) | 2.55 (0.70) |
| kyiv_nebo_any_10m | 2.7% | 209 | 3.82 (0.23) | 3.01 (0.35) | 2.11 (0.45) | 2.21 (0.75) |
| missile_any_30m | 2.4% | 185 | 1.79 (0.11) | 1.43 (0.17) | 1.24 (0.27) | 1.58 (0.55) |
| near80_30m | 12.7% | 989 | 4.32 (0.20) | 3.29 (0.31) | 2.61 (0.48) | 2.36 (0.70) |

