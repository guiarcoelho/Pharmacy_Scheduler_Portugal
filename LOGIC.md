# Logic & Rulebook (Config-First Scheduler)

This project is designed so that **most “business rules” live in YAML config files**, not in Python code.
The Python code acts mainly as a **processing layer**:

- Loads scenario YAML
- Builds a calendar (dates + holidays + “special day” tags)
- Builds decision variables (who can work what shift, on what day)
- Interprets the rulebook to create solver constraints + objective terms
- Runs the OR-Tools CP-SAT solver and exports results

The goal is that you can reuse the same code for a different context (factory, store, etc.) by swapping the scenario configs.

## 1) Where “logic” is used

There are two main places where we use logic conditions:

1. **Shift existence / availability**
   - In `config/**/shifts.yaml`, each shift can include `allowed_when` (JSONLogic).
   - If `allowed_when` is false for a date, that shift is treated as “does not exist” on that date.

2. **Filtering (“where”) inside constraints**
   - In `config/**/constraints.yaml` (the rulebook), many rules can include a `where` clause (JSONLogic).
   - This lets you apply a rule only to specific days, shifts, workers, groups, tags, etc.

## 2) JSONLogic (the conditional language)

JSONLogic is a small JSON-based language to express boolean logic like:

- “Is this day a Sunday?”
- “Is this shift one of [M, T]?”
- “Does this day have tag ‘service’?”

In this repository, JSONLogic is intentionally implemented as a **small subset** (so it’s easy to validate and keep safe).
The supported operators are implemented in `src/pharma_scheduler/jsonlogic.py`.

### Example: shift exists only on weekdays

In `shifts.yaml`:

```yaml
allowed_when:
  "in":
    - { "var": "day.weekday" }
    - [0, 1, 2, 3, 4]
```

Meaning: the shift exists only when `day.weekday` is in `[0..4]` (Mon–Fri).

## 3) What data JSONLogic can “see”

When JSONLogic runs, it evaluates against a small context object.
The exact available fields are documented below (and may grow over time), but conceptually:

- `day.*` information about the date (weekday, ISO date string, tags like holidays/special days)
- `shift.*` information about the shift definition (id, coverage min/max, etc.)
- `worker.*` information about a worker (id, group, capabilities, etc.)

The key point: JSONLogic is **only a filter** (“does this rule/shift apply here?”).
It does not create solver constraints by itself; the rulebook interpreter does.

## 4) The rulebook (what it is and why it exists)

The **rulebook** is a YAML file (usually `constraints.yaml`) that lists constraints in a consistent vocabulary.

- Some rules are **hard** (must be satisfied, otherwise the schedule is invalid).
- Some rules are **soft** (the schedule can violate them, but each violation adds a cost/penalty).

This gives you a clean separation:

- The **scenario** defines *what exists* (workers, shifts, dates, tags).
- The **rulebook** defines *how to judge a schedule* (requirements + preferences).

See the **Rulebook reference** section below for the exact primitive schema and expressions.

## 5) Special days (replacing “service week” hardcoding)

Instead of hardcoding “service week” rules in code, we store **special-day periods** in YAML:

- A period has `start` and `days` (length)
- The system expands it into a set of dates
- Those dates get a configurable tag name (e.g. `service`)

That tag can then be referenced in JSONLogic (`day.tags`) and in rulebook filters (`where`).

## 6) What to read next

- `config/scenario.yaml`: scenario “manifest” that points to the scenario folder
- `config/scenarios/pharmacy_pt/`: concrete example scenario (workers, shifts, calendar, special days, solver, rulebook)

## 7) Rulebook reference (constraints.yaml)

The rulebook is the single configuration file that defines *all* scheduling rules:

- **Hard constraints**: must always hold (otherwise the model is infeasible)
- **Soft constraints**: preferences; violations add cost to the objective

The engine reads `constraints.yaml` and translates each rule into CP-SAT constraints and objective terms.

### Shape (primitive rules)

```yaml
rulebook_version: 1
rules:
  - id: one_shift_per_day
    for_each:
      - { var: day, type: day }
      - { var: worker, type: worker }
    let:
      worked_today:
        count_assignments:
          select:
            dims:
              day: { from: "i.day" }
              worker: { from: "i.worker" }
    hard:
      - { lhs: { ref: "worked_today" }, op: "<=", rhs: { const: 1 } }

  - id: soft_fill_to_shift_max
    for_each:
      - { var: day, type: day }
      - var: shift
        type: shift
        where: { "in": ["soft_fill", { "var": "this.labels" }] }
    let:
      assigned:
        count_assignments:
          select:
            dims:
              day: { from: "i.day" }
              shift: { from: "i.shift" }
    soft:
      - units:
          max0:
            sub:
              - { var: "i.shift.coverage.max" }
              - { ref: "assigned" }
        penalty_per_unit: { var: "i.shift.soft_fill_penalty" }
```

### JSONLogic contexts

Rules are evaluated with a context dictionary that may include:

- `day`:
  - `date` (ISO string)
  - `weekday` (0=Mon … 6=Sun)
  - `is_holiday` (bool)
  - `is_weekend`, `is_saturday`, `is_sunday` (bools)
  - `has_next_day` (bool)
  - `special_tags` (list of strings)
  - `in_report_range` (bool)
- `shift`:
  - `code`
  - `labels` (list)
  - `coverage.min`, `coverage.max`
- `worker`:
  - `id`
  - `groups` (list)
  - `caps` (list)

### Primitive expressions (summary)

- **Selectors**: `count_assignments`, `sum_assignment_attr` with `select` and optional JSONLogic `where`.
- **Arithmetic**: `sum`, `sub`, `mul`, `max0`, `abs`.
- **Conditions**: `cmp` inside `only_if`, `bool_as_int` for soft penalties.
- **Loops**: `for_each` over `day`, `week`, `worker`, `shift`, `shift_transition`, and `list` (from top-level lists like `fairness_items`).
- **Ranges**: `day_range` with windows/filters and `range_size`.
- **Meta**: `eval` (evaluate an expression stored in config) and `with` (temporary variable bindings).
