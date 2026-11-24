# Route.it — Executed Multi-Solver Benchmark Report

- **Engine Specification**: `Q-HGALS-5.0-REV-2026-11-16`
- **Canonical Evaluation Budget**: `120` evaluations per run
- **Independent Seeds**: `[42, 101]`
- **Methodology Note**: All algorithms evaluated through the identical CanonicalEvaluator under matched canonical evaluation budgets (120 evaluations per run) across independent seeds (42, 101). No global optimality or unconditional algorithmic superiority is claimed.

## Instance: `Vadodara_TD_CVRPTW_8` (Best Observed Reference: `148236` paise)

| Solver Strategy | Feasibility Rate | Best Cost (paise) | Mean Cost (paise) | Std Dev (paise) | Gap vs Best Observed | Mean Runtime (ms) |
|---|---:|---:|---:|---:|---:|---:|
| `CONSTRUCTIVE` | 100.0% | 154785 | 154785 | 0.0 | +4.42% | 54.9 ms |
| `LOCAL_SEARCH` | 100.0% | 148236 | 148236 | 0.0 | +0.0% | 37.11 ms |
| `ALNS` | 100.0% | 153736 | 153736 | 0.0 | +3.71% | 42.32 ms |
| `GA` | 100.0% | 150728 | 152055.5 | 1327.5 | +1.68% | 63.11 ms |
| `QPSO` | 100.0% | 150728 | 152071 | 1343.0 | +1.68% | 47.97 ms |
| `ORTOOLS_ADAPTER` | 100.0% | 153084 | 153084 | 0.0 | +3.27% | 1548.78 ms |

## Instance: `Solomon_C101_12` (Best Observed Reference: `328431` paise)

| Solver Strategy | Feasibility Rate | Best Cost (paise) | Mean Cost (paise) | Std Dev (paise) | Gap vs Best Observed | Mean Runtime (ms) |
|---|---:|---:|---:|---:|---:|---:|
| `CONSTRUCTIVE` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 68.62 ms |
| `LOCAL_SEARCH` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 88.58 ms |
| `ALNS` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 123.54 ms |
| `GA` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 257.15 ms |
| `QPSO` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 224.0 ms |
| `ORTOOLS_ADAPTER` | 100.0% | 328431 | 328431 | 0.0 | +0.0% | 1568.78 ms |
