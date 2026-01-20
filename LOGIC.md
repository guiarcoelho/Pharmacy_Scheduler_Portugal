# Pharmacy Scheduler - Logic and Flow Documentation

This document provides a comprehensive explanation of the pharmacy scheduling system's architecture, algorithms, constraints, and optimization logic.

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture and Flow](#architecture-and-flow)
3. [Calendar Management](#calendar-management)
4. [Shift Definitions](#shift-definitions)
5. [Workers and Eligibility](#workers-and-eligibility)
6. [Coverage Demand](#coverage-demand)
7. [CP-SAT Model Variables](#cp-sat-model-variables)
8. [Hard Constraints](#hard-constraints)
9. [Soft Constraints](#soft-constraints)
10. [Objective Function](#objective-function)
11. [Solution Extraction](#solution-extraction)
12. [Key Algorithms](#key-algorithms)

---

## System Overview

The pharmacy scheduler solves a complex staff rostering problem for Portuguese pharmacies using Google OR-Tools CP-SAT solver. The system must:

- Schedule 6 workers (A, B, C, D, E, F) over a monthly period
- Respect Portuguese labor law (11h daily rest, weekend compensation)
- Handle service weeks (extended hours every 4th week)
- Minimize weekend/holiday work costs
- Maintain fairness across workers
- Satisfy exact coverage demands for each shift

### Problem Characteristics

- **Time horizon**: Typically 1 month (report period) + 14 days (buffer for Sunday compensation)
- **Workers**: 5 core workers (A-E) + 1 service weekend extra (F)
- **Shifts**: 15 different shift types across 4 day type categories
- **Constraints**: Mix of hard (must satisfy) and soft (penalized if violated)
- **Objective**: Multi-component cost minimization with fairness

---

## Architecture and Flow

### High-Level Flow

```
1. Load Configuration (YAML files)
   ↓
2. Build Calendar (service weeks, holidays, day types)
   ↓
3. Parse Shifts (clock vs paid minutes)
   ↓
4. Create CP-SAT Model
   ├── Create Variables (x[w,d,s], works[w,d], metrics)
   ├── Add Hard Constraints (coverage, rest, coupling, compensation)
   ├── Add Soft Constraints (weekly rest, fairness)
   └── Build Objective Function
   ↓
5. Solve with CP-SAT
   ↓
6. Extract Solution
   ↓
7. Calculate Statistics
   ↓
8. Export Results (CSV/Excel)
```

### Module Organization

- **calendar.py**: Date range, service weeks, holidays, day typing
- **shifts.py**: Shift definitions, eligibility, demand, time calculations
- **model.py**: CP-SAT variable creation, constraints, objective
- **solver.py**: Solver execution, solution extraction, statistics
- **export.py**: CSV/Excel generation, console output
- **cli.py**: Command-line interface (solve, check, explain)

---

## Calendar Management

### Date Range

The system operates on two date ranges:

1. **Report Range**: The actual period to schedule (e.g., Feb 1-28, 2026)
2. **Solve Range**: Report range + buffer days (default 14) to handle Sunday compensation that extends into next month

Only the report range is included in the final output and objective function.

### Day Type Classification

Each date is classified into one of four day types:

1. **NORMAL_WEEKDAY**: Monday-Friday, not in service week, not a holiday
2. **NORMAL_WEEKEND_OR_HOLIDAY**: Saturday/Sunday or bank holiday, not in service week
3. **SERVICE_WEEKDAY**: Monday-Friday in a service week
4. **SERVICE_WEEKEND_OR_HOLIDAY**: Saturday/Sunday or bank holiday in a service week

### Service Week Calculation

Service weeks follow a repeating 4-week cycle. The algorithm:

```python
def is_service_week(date, anchor_monday, cycle_weeks=4, service_week_in_cycle=4):
    """
    anchor_monday: 2026-01-05 (must be a Monday)
    cycle_weeks: 4
    service_week_in_cycle: 4 (the 4th week in each cycle)
    """
    # Get the Monday of the week containing 'date'
    monday = date - timedelta(days=date.weekday())
    
    # Calculate weeks since anchor
    weeks_since_anchor = (monday - anchor_monday).days // 7
    
    # Determine position in cycle (1-indexed)
    cycle_position = (weeks_since_anchor % cycle_weeks) + 1
    
    # Check if this is the service week
    return cycle_position == service_week_in_cycle
```

**Example**: With anchor Monday 2026-01-05:
- Week of Jan 5-11: cycle position 1 (normal)
- Week of Jan 12-18: cycle position 2 (normal)
- Week of Jan 19-25: cycle position 3 (normal)
- Week of Jan 26-Feb 1: cycle position 4 (SERVICE)
- Week of Feb 2-8: cycle position 1 (normal)
- ...repeats...

### Bank Holidays

Bank holidays are detected using the `holidays` library for Portugal:

```python
import holidays
pt_holidays = holidays.Portugal(years=[2026])
is_holiday = date in pt_holidays
```

**Important**: Bank holidays are treated like weekends for coverage and pay, but do NOT trigger Sunday compensation (only actual Sundays do).

### Helper Functions

The calendar module provides:

- `get_week_id(date)`: Returns Monday date for the week containing date (for aggregation)
- `get_weekend_pairs()`: Returns list of (Saturday, Sunday) tuples
- `get_sundays()`: Returns list of all Sunday dates
- `get_sunday_comp_weekdays(sunday)`: Returns candidate weekdays for Sunday compensation
- `get_next_weekend(sunday)`: Returns (next_saturday, next_sunday) tuple
- `get_report_mask()`: Boolean array indicating which days are in report range

---

## Shift Definitions

### Shift Structure

Each shift has:
- **code**: Unique identifier (e.g., "M", "TS", "FSW")
- **start**: Start time (HH:MM)
- **end**: End time for payment (HH:MM)
- **clock_end**: End time for rest calculations (optional override)
- **tags**: Categorization (weekday, weekend, service, night)

### Clock Minutes vs Paid Minutes

**Critical distinction** for TS and TSW shifts:

```
TS (Service weekday late shift):
  start: 16:00
  end: 00:00 (paid until midnight)
  clock_end: 23:59 (for rest calculations)
  
  paid_minutes = 480 (8 hours: 16:00 to 00:00)
  clock_minutes = 479 (16:00 to 23:59)
```

**Why?** Portuguese labor law requires 11 hours rest between shifts. If TS ended at 00:00 for rest calculations, the next shift could start at 11:00. By using 23:59, we enforce that the next shift cannot start before 10:59, ensuring proper rest.

### Midnight Boundary Handling

For shifts ending at 00:00:

```python
def calculate_duration(start_time, end_time):
    """Calculate minutes between start and end on same day."""
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    
    # If end is 00:00, treat as 24:00 (1440 minutes)
    if end_minutes == 0:
        end_minutes = 1440
    
    return end_minutes - start_minutes
```

### Shift Types by Day Type

**Normal Weekdays** (Mon-Fri, not service week):
- **M** (Manhã): 08:30-17:30 (540 min)
- **I** (Intermédio): 10:30-19:30 (540 min)
- **T** (Tarde): 11:30-20:30 (540 min)

**Normal Weekends/Holidays**:
- **MW**: 08:30-13:30 (300 min)
- **IW**: 09:30-16:30 (420 min)
- **TW**: 15:30-20:30 (300 min)

**Service Weekdays**:
- **MS**: 09:00-18:00 (540 min)
- **IS**: 13:00-22:00 (540 min)
- **TS**: 16:00-00:00 (480 paid min, 479 clock min)
- **NS**: 00:00-08:30 (510 min)

**Service Weekends/Holidays**:
- **MSW**: 08:30-13:30 (300 min)
- **ISW**: 14:00-22:00 (480 min)
- **TSW**: 16:00-00:00 (480 paid min, 479 clock min)
- **NSW**: 00:00-08:30 (510 min)
- **FSW**: 09:30-16:30 (420 min) - Extra line option

---

## Workers and Eligibility

### Worker Groups

- **Core workers**: A, B, C, D, E
  - Can work all shifts except night shifts (only E can do nights)
  - Subject to weekend coupling and Sunday compensation
  - Included in fairness calculations

- **Night-capable**: E only
  - Can work NS and NSW in addition to all other shifts

- **Service extra**: F only
  - Only works service weekend Saturday and Sunday
  - Must work both days
  - Each day chooses MSW or FSW
  - Not subject to weekend coupling or Sunday compensation
  - Not included in fairness calculations

### Eligibility Rules

```python
def is_eligible(worker, shift, day_type):
    # Night shifts: only E
    if shift in ['NS', 'NSW']:
        return worker == 'E'
    
    # Worker F: only MSW/FSW on service weekends
    if worker == 'F':
        is_service_weekend = day_type in ['SERVICE_WEEKEND_OR_HOLIDAY']
        is_saturday_or_sunday = # check if date is Sat or Sun
        return shift in ['MSW', 'FSW'] and is_service_weekend and is_saturday_or_sunday
    
    # Core workers: all non-night shifts on appropriate day types
    return shift_allowed_for_day_type(shift, day_type)
```

---

## Coverage Demand

### Demand by Day Type

**Normal Weekdays**:
- 1 × M
- 1 × I
- 2 × T

**Normal Weekends/Holidays**:
- 1 × MW
- 1 × IW
- 1 × TW

**Service Weekdays**:
- 1 × MS
- 1 × IS
- 1 × TS
- 1 × NS

**Service Weekends/Holidays**:
- 1 × MSW (base, from core workers)
- 1 × ISW
- 1 × TSW
- 1 × NSW
- 1 × extra line (MSW or FSW, from worker F)

### Service Weekend Extra Line

**Critical design**: On service weekend Sat/Sun, there are TWO MSW slots:
1. **Base MSW**: Filled by one core worker (A-E)
2. **Extra line**: Filled by worker F (can choose MSW or FSW)

This is implemented with separate constraints:
```python
# Base MSW from core workers
sum(x[w, d, 'MSW'] for w in ['A','B','C','D','E']) == 1

# Extra line from F
x['F', d, 'MSW'] + x['F', d, 'FSW'] == 1
```

---

## CP-SAT Model Variables

### Primary Variables

**x[w, d, s]**: Boolean
- Worker `w` is assigned to shift `s` on day `d`
- Only created for eligible (worker, day, shift) combinations

**works[w, d]**: Boolean
- Worker `w` works on day `d` (any shift)
- Defined as: `works[w, d] = sum(x[w, d, s] for all shifts s)`

### Aggregated Variables

**Paid minutes by worker-day**:
```python
paid_minutes[w, d] = sum(x[w, d, s] * shift[s].paid_minutes for all shifts s)
```

**Weekend/Holiday minutes** (for objective):
```python
sat_minutes[w] = sum(paid_minutes[w, d] for d in Saturdays)
sun_minutes[w] = sum(paid_minutes[w, d] for d in Sundays)
holiday_minutes[w] = sum(paid_minutes[w, d] for d in Holidays)
weekend_minutes[w] = sat_minutes[w] + sun_minutes[w]
```

**Weekday minutes by week**:
```python
weekday_minutes[w, week] = sum(paid_minutes[w, d] for d in weekdays_of_week)
```

**Excess over 40h per week**:
```python
excess40[w, week] = IntVar(0, 10000)
model.Add(excess40[w, week] >= weekday_minutes[w, week] - 2400)  # 40h = 2400min
model.Add(excess40[w, week] >= 0)
```

**Shift counts**:
```python
shift_count[w, shift_code] = sum(x[w, d, s] for all days d where shift s has code shift_code)
```

### Soft Constraint Variables

**Weekly rest penalty**:
```python
no_day_off[w, week] = BoolVar()
# Channeling constraints (explained in soft constraints section)
```

**Fairness deviation**:
```python
fairness_diff[w, metric] = IntVar(0, large_value)
# Absolute value constraints (explained in fairness section)
```

---

## Hard Constraints

### 1. One Shift Per Day

Each worker can work at most one shift per day:

```python
for worker in all_workers:
    for day in all_days:
        model.Add(sum(x[worker, day, shift] for shift in eligible_shifts) <= 1)
```

This is implicitly enforced by the `works[w, d]` definition.

### 2. Coverage Constraints

Exact demand must be met for each shift on each day:

```python
for day in all_days:
    day_type = calendar.get_day_type(day)
    demand = get_demand_for_day_type(day_type)
    
    for shift_code, count in demand.items():
        if is_service_weekend(day) and shift_code == 'MSW':
            # Special case: base MSW from core workers
            model.Add(sum(x[w, day, 'MSW'] for w in core_workers) == 1)
        else:
            # Normal coverage
            model.Add(sum(x[w, day, shift_code] for w in eligible_workers) == count)
```

**Service weekend extra line**:
```python
if is_service_weekend_day(day):
    # F must work and choose MSW or FSW
    model.Add(x['F', day, 'MSW'] + x['F', day, 'FSW'] == 1)
```

### 3. Eligibility Constraints

Set ineligible variables to 0:

```python
for worker in all_workers:
    for day in all_days:
        for shift in all_shifts:
            if not is_eligible(worker, shift, day):
                model.Add(x[worker, day, shift] == 0)
```

**Worker F forced off non-service-weekend days**:
```python
for day in all_days:
    if not is_service_weekend_day(day):
        model.Add(works['F', day] == 0)
```

### 4. Daily Rest (11 hours minimum)

Calculate forbidden shift transitions:

```python
def get_forbidden_transitions(shifts, min_rest_hours=11):
    """Returns list of (shift1, shift2) pairs that violate rest."""
    forbidden = []
    
    for s1 in shifts:
        for s2 in shifts:
            # Use clock_end for s1 (23:59 for TS/TSW)
            end1 = s1.clock_end
            start2 = s2.start
            
            # Calculate rest hours (handle midnight wraparound)
            rest_hours = (start2 - end1) % 24
            
            if rest_hours < min_rest_hours:
                forbidden.append((s1.code, s2.code))
    
    return forbidden
```

Apply constraints:

```python
forbidden = get_forbidden_transitions(all_shifts, min_rest_hours=11)

for worker in all_workers:
    for day in range(len(all_days) - 1):
        day1 = all_days[day]
        day2 = all_days[day + 1]
        
        for (shift1, shift2) in forbidden:
            # Cannot work shift1 on day1 and shift2 on day2
            if is_eligible(worker, shift1, day1) and is_eligible(worker, shift2, day2):
                model.Add(x[worker, day1, shift1] + x[worker, day2, shift2] <= 1)
```

**Example forbidden transitions**:
- TS (ends 23:59) → M (starts 08:30): rest = 8h 31min ❌
- TS (ends 23:59) → I (starts 10:30): rest = 10h 31min ❌
- TS (ends 23:59) → T (starts 11:30): rest = 11h 31min ✓

### 5. Weekend Coupling

Core workers must work both Saturday and Sunday or neither:

```python
weekend_pairs = calendar.get_weekend_pairs()

for worker in core_workers:  # A, B, C, D, E only
    for (saturday, sunday) in weekend_pairs:
        model.Add(works[worker, saturday] == works[worker, sunday])
```

Worker F is excluded (must work both service weekend days).

### 6. Sunday Compensation

For each Sunday and each core worker:

```python
sundays = calendar.get_sundays()

for worker in core_workers:
    for sunday in sundays:
        sun_work = works[worker, sunday]
        
        # (a) Extra weekday off in candidate set
        candidate_weekdays = calendar.get_sunday_comp_weekdays(sunday)
        # candidate_weekdays = Mon-Fri of week before + Mon-Fri of week of Sunday
        
        total_work_in_candidates = sum(works[worker, d] for d in candidate_weekdays)
        # Must have at least one day off: work <= |C| - 1
        model.Add(total_work_in_candidates <= len(candidate_weekdays) - 1).OnlyEnforceIf(sun_work)
        
        # (b) Next weekend fully off
        (next_sat, next_sun) = calendar.get_next_weekend(sunday)
        model.Add(works[worker, next_sat] == 0).OnlyEnforceIf(sun_work)
        model.Add(works[worker, next_sun] == 0).OnlyEnforceIf(sun_work)
```

**Candidate weekdays calculation**:
```python
def get_sunday_comp_weekdays(sunday):
    """Get Mon-Fri of week before Sunday + Mon-Fri of week of Sunday."""
    # Week of Sunday
    monday_of = sunday - timedelta(days=sunday.weekday())
    week_of_weekdays = [monday_of + timedelta(days=i) for i in range(5)]  # Mon-Fri
    
    # Week before Sunday
    monday_before = monday_of - timedelta(days=7)
    week_before_weekdays = [monday_before + timedelta(days=i) for i in range(5)]
    
    # Union (typically 10 days, unless Sunday is Monday then 9, etc.)
    return list(set(week_before_weekdays + week_of_weekdays))
```

**Important**: Only actual Sundays trigger compensation. Bank holidays that fall on other days do NOT.

---

## Soft Constraints

### 1. Weekly Rest Penalty

Penalize workers who work all 7 days in a week:

```python
weeks = calendar.get_all_weeks()

for worker in core_workers:
    for week in weeks:
        days_in_week = calendar.get_days_in_week(week)
        
        # Create boolean variable
        no_day_off = model.NewBoolVar(f'no_day_off_{worker}_{week}')
        
        # Channeling constraints
        total_work_days = sum(works[worker, d] for d in days_in_week)
        
        # If no_day_off is true, then total_work_days == 7
        model.Add(total_work_days == 7).OnlyEnforceIf(no_day_off)
        
        # If no_day_off is false, then total_work_days <= 6
        model.Add(total_work_days <= 6).OnlyEnforceIf(no_day_off.Not())
        
        # Add to objective with penalty weight
        weekly_rest_penalty += 2500 * no_day_off
```

### 2. Fairness Constraints

Use **mean-scaled fairness** to balance metrics across core workers:

```python
def add_fairness_constraint(model, metric_values, weight, name):
    """
    metric_values: dict {worker: IntVar or LinearExpr}
    weight: fairness weight
    
    Minimizes: sum over workers of |n * metric[w] - Total|
    where n = number of workers, Total = sum of all metrics
    """
    n = len(metric_values)  # 5 for core workers
    workers = list(metric_values.keys())
    
    # Total = sum of metric across all workers
    total = sum(metric_values[w] for w in workers)
    
    fairness_cost = 0
    for worker in workers:
        # Create variable for absolute deviation
        diff = model.NewIntVar(0, 1000000, f'fairness_diff_{name}_{worker}')
        
        # diff = |n * metric[worker] - total|
        model.AddAbsEquality(diff, n * metric_values[worker] - total)
        
        fairness_cost += weight * diff
    
    return fairness_cost
```

**Applied to**:

1. **Weekend minutes fairness** (weight = 2):
   ```python
   weekend_fairness = add_fairness_constraint(
       model, 
       {w: weekend_minutes[w] for w in core_workers},
       weight=2,
       name='weekend_minutes'
   )
   ```

2. **Holiday minutes fairness** (weight = 2):
   ```python
   holiday_fairness = add_fairness_constraint(
       model,
       {w: holiday_minutes[w] for w in core_workers},
       weight=2,
       name='holiday_minutes'
   )
   ```

3. **Weekday excess fairness** (weight = 1):
   ```python
   excess_fairness = add_fairness_constraint(
       model,
       {w: sum(excess40[w, week] for week in weeks) for w in core_workers},
       weight=1,
       name='weekday_excess'
   )
   ```

4. **Shift count fairness** (weight = 50):
   ```python
   # For common shift types (exclude NS/NSW)
   common_shifts = ['M', 'I', 'T', 'MW', 'IW', 'TW', 'MS', 'IS', 'TS', 'MSW', 'ISW', 'TSW', 'FSW']
   
   for shift_code in common_shifts:
       shift_fairness += add_fairness_constraint(
           model,
           {w: shift_count[w, shift_code] for w in core_workers},
           weight=50,
           name=f'shift_{shift_code}'
       )
   ```

**Why mean-scaled?** 
- Traditional fairness: minimize max - min (range)
- Mean-scaled: minimize sum of deviations from mean
- More granular: penalizes any imbalance, not just extremes
- Better for CP-SAT: linear objective term

---

## Objective Function

The objective minimizes a weighted sum of costs:

```python
objective = work_cost + weekday_excess_cost + weekly_rest_cost + fairness_cost
```

### 1. Work Cost (Weekend/Holiday Premium)

```python
work_cost = 0

for worker in all_workers:
    # Saturday premium: weight = 10
    work_cost += 10 * sat_minutes[worker]
    
    # Sunday premium: weight = 14
    work_cost += 14 * sun_minutes[worker]
    
    # Holiday premium: weight = 16
    work_cost += 16 * holiday_minutes[worker]
```

**Note**: Only count days in the report range (exclude buffer days).

### 2. Weekday Excess Cost

Penalize weekday minutes above 40h per week:

```python
weekday_excess_cost = 0

for worker in core_workers:
    for week in weeks:
        # excess40[w, week] = max(0, weekday_minutes - 2400)
        weekday_excess_cost += 1 * excess40[worker, week]
```

### 3. Weekly Rest Cost

```python
weekly_rest_cost = 0

for worker in core_workers:
    for week in weeks:
        weekly_rest_cost += 2500 * no_day_off[worker, week]
```

### 4. Fairness Cost

```python
fairness_cost = (
    weekend_fairness +      # weight 2
    holiday_fairness +      # weight 2
    excess_fairness +       # weight 1
    shift_count_fairness    # weight 50 per shift type
)
```

### Objective Weights Summary

| Component | Weight | Purpose |
|-----------|--------|---------|
| Saturday minutes | 10 | Minimize weekend work |
| Sunday minutes | 14 | Strongly minimize Sunday work |
| Holiday minutes | 16 | Most expensive: minimize holiday work |
| Weekday excess (>40h) | 1 | Soft limit on weekly hours |
| Weekly rest violation | 2500 | Strong penalty for no days off |
| Weekend fairness | 2 | Balance weekend work |
| Holiday fairness | 2 | Balance holiday work |
| Excess fairness | 1 | Balance overtime |
| Shift count fairness | 50 | Balance shift type distribution |

**Tuning**: Adjust weights to change optimization priorities. Higher weights = stronger preference.

---

## Solution Extraction

After solving:

```python
solver = cp_model.CpSolver()
status = solver.Solve(model)

if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    # Extract assignments
    schedule = []
    for worker in all_workers:
        for day in all_days:
            for shift in all_shifts:
                if solver.Value(x[worker, day, shift]) == 1:
                    schedule.append({
                        'date': day,
                        'worker': worker,
                        'shift': shift,
                        'day_type': calendar.get_day_type(day)
                    })
    
    # Calculate statistics
    stats = calculate_worker_stats(schedule, calendar, shifts)
    
    # Export
    export_csv(schedule, stats, output_dir)
```

### Worker Statistics

For each worker, calculate:

```python
def calculate_worker_stats(schedule, calendar, shifts):
    stats = {}
    
    for worker in all_workers:
        worker_schedule = [s for s in schedule if s['worker'] == worker]
        
        stats[worker] = {
            'total_paid_minutes': sum(shifts[s['shift']].paid_minutes for s in worker_schedule),
            'weekend_minutes': sum(... for s in worker_schedule if is_weekend(s['date'])),
            'saturday_minutes': sum(... for s in worker_schedule if is_saturday(s['date'])),
            'sunday_minutes': sum(... for s in worker_schedule if is_sunday(s['date'])),
            'holiday_minutes': sum(... for s in worker_schedule if is_holiday(s['date'])),
            'weekday_minutes_by_week': {...},
            'excess_40h_by_week': {...},
            'shift_counts': Counter(s['shift'] for s in worker_schedule),
            'sundays_worked': len([s for s in worker_schedule if is_sunday(s['date'])]),
            'full_weekends_off': count_full_weekends_off(worker_schedule, calendar),
        }
    
    return stats
```

---

## Key Algorithms

### Algorithm 1: Service Week Detection

```python
def is_service_week(date: datetime.date, 
                    anchor_monday: datetime.date,
                    cycle_weeks: int = 4,
                    service_week_in_cycle: int = 4) -> bool:
    """
    Determine if a date falls in a service week.
    
    Args:
        date: Date to check
        anchor_monday: Reference Monday (must be a Monday)
        cycle_weeks: Length of cycle (default 4)
        service_week_in_cycle: Which week in cycle is service (default 4)
    
    Returns:
        True if date is in a service week
    """
    # Get Monday of the week containing date
    monday = date - timedelta(days=date.weekday())
    
    # Calculate weeks since anchor
    weeks_since_anchor = (monday - anchor_monday).days // 7
    
    # Determine position in cycle (1-indexed)
    cycle_position = (weeks_since_anchor % cycle_weeks) + 1
    
    return cycle_position == service_week_in_cycle
```

### Algorithm 2: Forbidden Transition Calculation

```python
def calculate_forbidden_transitions(shifts: List[Shift], 
                                    min_rest_hours: int = 11) -> List[Tuple[str, str]]:
    """
    Calculate which shift pairs violate minimum rest requirement.
    
    Args:
        shifts: List of shift definitions
        min_rest_hours: Minimum rest hours required (default 11)
    
    Returns:
        List of (shift1_code, shift2_code) forbidden pairs
    """
    forbidden = []
    
    for s1 in shifts:
        # Use clock_end (23:59 for TS/TSW, regular end for others)
        end1_minutes = s1.clock_end.hour * 60 + s1.clock_end.minute
        
        for s2 in shifts:
            start2_minutes = s2.start.hour * 60 + s2.start.minute
            
            # Calculate rest minutes (handle midnight wraparound)
            if start2_minutes >= end1_minutes:
                rest_minutes = start2_minutes - end1_minutes
            else:
                # Wraparound: e.g., end 23:59, start 08:30
                rest_minutes = (1440 - end1_minutes) + start2_minutes
            
            rest_hours = rest_minutes / 60
            
            if rest_hours < min_rest_hours:
                forbidden.append((s1.code, s2.code))
    
    return forbidden
```

### Algorithm 3: Sunday Compensation Weekdays

```python
def get_sunday_compensation_weekdays(sunday: datetime.date) -> List[datetime.date]:
    """
    Get candidate weekdays for Sunday compensation.
    
    Returns Mon-Fri of the week before the Sunday + Mon-Fri of the week of the Sunday.
    
    Args:
        sunday: The Sunday date
    
    Returns:
        List of weekday dates (Mon-Fri) from two weeks
    """
    # Week containing Sunday
    monday_of_sunday = sunday - timedelta(days=sunday.weekday())
    week_of_weekdays = [monday_of_sunday + timedelta(days=i) for i in range(5)]
    
    # Week before Sunday
    monday_before = monday_of_sunday - timedelta(days=7)
    week_before_weekdays = [monday_before + timedelta(days=i) for i in range(5)]
    
    # Combine and deduplicate (in case Sunday is Monday, there's overlap)
    all_weekdays = week_before_weekdays + week_of_weekdays
    return sorted(set(all_weekdays))
```

### Algorithm 4: Mean-Scaled Fairness

```python
def add_mean_scaled_fairness(model: cp_model.CpModel,
                             metrics: Dict[str, IntVar],
                             weight: int,
                             name: str) -> IntVar:
    """
    Add mean-scaled fairness constraint.
    
    Minimizes: sum_w |n * metric[w] - Total|
    where n = number of workers, Total = sum of all metrics
    
    Args:
        model: CP-SAT model
        metrics: Dict mapping worker to metric variable
        weight: Fairness weight
        name: Constraint name for debugging
    
    Returns:
        Total fairness cost variable
    """
    workers = list(metrics.keys())
    n = len(workers)
    
    # Total across all workers
    total = sum(metrics[w] for w in workers)
    
    # Create deviation variables
    fairness_cost = 0
    for worker in workers:
        # Deviation from mean: |n * metric[w] - Total|
        deviation = model.NewIntVar(0, 10000000, f'{name}_dev_{worker}')
        model.AddAbsEquality(deviation, n * metrics[worker] - total)
        fairness_cost += weight * deviation
    
    return fairness_cost
```

---

## Debugging and Troubleshooting

### Infeasibility

If the solver returns INFEASIBLE:

1. **Check service week alignment**: Verify anchor Monday and cycle match your expectations
2. **Review coverage vs workers**: Ensure enough eligible workers for each shift
3. **Sunday compensation**: May need more buffer days if many Sundays in report period
4. **Daily rest**: Check if shift transitions are too tight (especially with TS/TSW)

Use `pharma-schedule check` to validate configuration before solving.

### Suboptimal Solutions

If solution quality is poor:

1. **Increase time limit**: Give solver more time to find better solutions
2. **Adjust weights**: Tune objective weights to match priorities
3. **Reduce fairness**: Lower fairness weights for faster solving
4. **Simplify constraints**: Temporarily disable soft constraints to test

### Performance

For faster solving:

1. **Reduce horizon**: Solve shorter periods (2 weeks instead of 1 month)
2. **Increase search workers**: Use more CPU cores (`num_search_workers`)
3. **Simplify fairness**: Remove shift count fairness (most expensive)
4. **Reduce buffer**: Use 7 days instead of 14 if few Sundays

---

## Summary

This pharmacy scheduler demonstrates advanced constraint programming techniques:

- **Complex calendar logic**: Service weeks, holidays, day typing
- **Dual time accounting**: Clock vs paid minutes for legal compliance
- **Sophisticated constraints**: Rest periods, weekend coupling, Sunday compensation
- **Multi-objective optimization**: Cost minimization + fairness
- **Practical design**: Configurable, testable, maintainable

The system balances mathematical rigor with real-world practicality, providing an optimal schedule while respecting all legal and operational constraints.
