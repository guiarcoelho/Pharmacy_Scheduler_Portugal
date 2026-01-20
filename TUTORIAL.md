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

- **Infeasibility**: If the script tells you it's "INFEASIBLE", it means your demand is higher than what the workers can handle according to legal rest rules. Try reducing demand or adding workers.
- **Fairness**: The system automatically balances hours and weekends between workers A, B, C, D, and E.
