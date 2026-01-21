# Pharmacy Scheduler

A Python-based pharmacy staff scheduling system using Google OR-Tools CP-SAT solver. Generates optimal monthly schedules for Portuguese pharmacies while respecting complex legal constraints, service week patterns, and fairness objectives.

## Features

- **Complex Constraint Handling**: Daily rest periods (11h), weekend coupling, selective Sunday compensation
- **Extended Service Week**: Automatic 4-week cycle with 8-day service periods (Monday-to-Monday)
- **Portuguese Labor Law**: Bank holidays, weekend premiums, 40h weekly limits
- **Soft Target Optimization**: Configurable penalties for preferred coverage levels (e.g., Target 2 for Shift M)
- **Fairness Optimization**: Balanced workloads and weekend distribution across core workers
- **Excel & CSV Export**: Detailed daily schedules and worker metrics

## Installation

### Prerequisites
- Python 3.11 or higher
- `uv` (recommended) or `pip`

### Setup

```bash
cd Pharmacy_Scheduler_Portugal
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

### 1. Unified Run Script
The easiest way to generate a schedule is using the helper script:

```bash
./pharma
```

This runs the `run.py` script, which:
1. Validates `config/instance.yaml`
2. Solves the scheduling problem
3. Exports results to `out/` as CSV and Excel

### 2. Individual Commands
You can also use the `pharma-schedule` CLI directly:

```bash
# Validate config
pharma-schedule check

# Solve and explain
pharma-schedule solve --out out/
pharma-schedule explain --date 2026-02-15
```

## Scheduling Logic

### Service Weeks
Every 4th week is a service week. It is an **8-day period** starting Monday morning and ending the following Monday morning. Use `anchor_monday` in `instance.yaml` to sync the cycle.

### Sunday Compensation (Modified)
When a core worker (A-E) works a Sunday:
- **Normal Sunday**: Must have a compensatory day off in the **same week** (Mon-Fri).
- **Service Sunday**: Can have a rest day in the same week **or the following week** (to allow for night-shift coverage).
- **Next Weekend Off**: The worker is penalized if they work the following weekend (Soft Constraint).

### Staffing Targets
- **Shift M**: Minimum 1 worker (Hard), Target 2 workers (Soft).
- **Shift I**: Minimum 0 workers (Hard), Target 1 worker (Soft).

## Output Files

Located in the `out/` directory:
- `schedule.csv`: Daily assignment list.
- `schedule.xlsx`: Color-coded Excel report with worker statistics.
- `worker_stats.csv`: Detailed monthly metrics for auditing fairness and hours.

## Troubleshooting

- **Infeasible**: Check if staffing demand exceeds your worker pool (5 core + 1 weekend extra).
- **Slow Solver**: Increase `time_limit_seconds` or decrease `num_search_workers` if hardware is limited.
- **Unexpected Shifts**: Use the `explain` command to see exactly how constraints are interacting on a specific date.

## License
MIT License
