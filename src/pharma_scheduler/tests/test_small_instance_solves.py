from __future__ import annotations

from collections import defaultdict

from pharma_scheduler.domain.calendar import DayType


def test_small_instance_solves(solved_small_instance) -> None:
    _, data, result = solved_small_instance
    assert result.status in {"OPTIMAL", "FEASIBLE"}

    by_day_shift: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in result.schedule:
        key = (entry["date"], entry["shift_code"])
        by_day_shift[key].append(entry["worker"])

    core = set(data.worker_groups.core)
    extra = set(data.worker_groups.service_extra)

    for day in data.calendar.days:
        if not day.in_report:
            continue
        demand = data.demand.demand_for(day.day_type)
        if day.day_type == DayType.SERVICE_WEEKEND_OR_HOLIDAY:
            for code, needed in demand.items():
                workers = [w for w in by_day_shift.get((day.date.isoformat(), code), []) if w in core]
                assert len(workers) == needed
            if day.is_saturday or day.is_sunday:
                extra_workers = [
                    w
                    for code in ("MSW", "FSW")
                    for w in by_day_shift.get((day.date.isoformat(), code), [])
                    if w in extra
                ]
                assert len(extra_workers) == 1
            else:
                for code in ("MSW", "FSW"):
                    workers = [
                        w
                        for w in by_day_shift.get((day.date.isoformat(), code), [])
                        if w in extra
                    ]
                    assert len(workers) == 0
        else:
            for code, needed in demand.items():
                workers = by_day_shift.get((day.date.isoformat(), code), [])
                assert len(workers) == needed
            for code in ("MSW", "FSW"):
                workers = [
                    w
                    for w in by_day_shift.get((day.date.isoformat(), code), [])
                    if w in extra
                ]
                assert len(workers) == 0
