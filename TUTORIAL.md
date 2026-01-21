# 📖 Pharmacy Scheduler Tutorial

This guide explains how to use the Pharmacy Scheduler with a single simple command.

## 🛠 1. Quick Setup

If you haven't already, ensure your environment is ready:
1.  **Activate your environment**: `source .venv/bin/activate`
2.  **Install project**: `pip install -e .`

---

## 🚀 2. The "Everything" Command

I have created a helper script that handles the configuration check, the solve, and the export all at once.

To run the entire workflow, simply type:
```bash
./pharma
```

This will:
1.  **Check** your `config/instance.yaml` for errors.
2.  **Generate** the optimal schedule.
3.  **Produce** all reports (`schedule.csv`, `worker_stats.csv`, and the Excel `schedule.xlsx`).

---

## ⚙️ 3. Modifying Your Data

The system reads from two files:

### `config/instance.yaml`
- **Dates**: Change `report_start` and `report_end` to schedule a different month.
- **Workers**: Add or remove staff in the `workers` list.
- **Demand**: Change how many people work each shift.

### `config/shifts.yaml`
- Change start/end times if shift hours change.

---

## 📊 4. Understanding Results

After running `./pharma`, look in the **`out/`** folder:
1.  **`schedule.xlsx`**: The best way to view the result.
    - **Grid Sheet**: Calendar-style view (Workers vs. Dates).
    - **Worker Statistics**: Totals for hours, days off, and shift counts.
2.  **`schedule.csv`**: Detailed list of assignments.

---

## 💡 5. Pro Tips

- **Infeasibility**: If the script says "INFEASIBLE", it means your staffing demand is too high for the available workers. Try reducing demand or allowing Worker F to cover more shifts.
- **Fairness**: The system balances everyone's hours, weekends, and unpopular shifts. If one person has an "easier" week, the solver will likely give them a "harder" one later to catch up.
- **Deep Search**: If the solution isn't "perfect," try increasing `time_limit_seconds` in `config/instance.yaml`.
- **Advanced CLI**:
  - `pharma-schedule check`: Detailed validation of your YAML files.
  - `pharma-schedule explain --date YYYY-MM-DD`: See the exact reasoning and assignments for any day.
  - `pharma-schedule solve --out out/`: Run the solver directly without the wrapper script.
