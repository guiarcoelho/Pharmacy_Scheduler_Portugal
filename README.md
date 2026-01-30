# 🏥 Pharmacy Scheduler (Portugal)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![OR-Tools](https://img.shields.io/badge/Solver-OR--Tools-orange.svg)](https://developers.google.com/optimization)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Stop fighting with Excel.** This tool generates optimal monthly schedules for Portuguese pharmacies using Google's CP-SAT solver. It handles labor laws, special service periods, and fairness distribution that make manual scheduling a nightmare.

---

## ✨ Key Features

- **⚖️ Legal Compliance**: Enforces mandatory 11h daily rest periods and Sunday compensation rules.
- **🔄 Service Periods**: Supports configurable special-day periods (e.g., service weeks).
- **🛡️ Portuguese Labor Law**: Built-in support for bank holidays and weekly hour limits (40h).
- **🤝 Fairness Optimization**: Balances weekend work and holiday shifts across all core staff.
- **📊 Professional Exports**: Generates color-coded Excel sheets and detailed CSV metrics.

---

## ⚡ Quick Start (3 Minutes)

### 1. Requirements
- **Python 3.11+**
- [uv](https://github.com/astral-sh/uv) (recommended for 10x faster setup) or `pip`.

### 2. Installation & Setup
Clone the repo and install dependencies:

```bash
# Using uv (fastest)
uv venv
source .venv/bin/activate
uv pip install -e .

# Using pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Generate Your First Schedule
Everything is pre-configured for a demo run. Just execute:

```bash
python run.py
```

Check the `out/` folder for your `schedule.xlsx`!

Optional helpers:

```bash
# Validate config (no solving)
python run.py --check

# Explain who works on a specific day (requires out/schedule.csv)
python run.py --explain 2026-02-15
```

---

## ⚙️ How to Customize

All scheduling logic is controlled via the scenario files referenced from
`config/scenario.yaml` (default points to `config/scenarios/pharmacy_pt/`):

- `calendar.yaml`: report range, buffer days, holiday locale
- `special_days.yaml`: special periods (e.g., service weeks) as date ranges
- `workers.yaml`: worker database + groups + capabilities + optional vacations
- `shifts.yaml`: shift times, coverage min/max, and JSONLogic `allowed_when`
- `constraints.yaml`: primitive rulebook of hard/soft constraints (JSONLogic filters + fairness_items)
- `solver.yaml`: solver limits and logging

Vacations are supported per worker in `workers.yaml` as `{start, days}` ranges
(inclusive), and are treated as hard unavailability.

If you change the service-cycle parameters in `calendar.yaml`, regenerate
`special_days.yaml` with:

```bash
python3 scripts/generate_special_days.py \
  --calendar config/scenarios/pharmacy_pt/calendar.yaml \
  --out config/scenarios/pharmacy_pt/special_days.yaml \
  --name service
```

---

## 📖 Deep Dive

For those interested in the underlying algorithms, check the [LOGIC.md](LOGIC.md) file. It explains:
- How the 10-day Sunday compensation window works.
- The weighting system for fairness vs. cost.

For details on the config-driven rulebook format, see `LOGIC.md`.

## 📜 License
Published under the MIT License. Feel free to use and adapt!
