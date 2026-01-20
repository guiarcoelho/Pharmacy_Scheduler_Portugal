from __future__ import annotations


def test_sunday_comp_next_weekend_off(solved_small_instance) -> None:
    _, data, result = solved_small_instance
    assert result.status in {"OPTIMAL", "FEASIBLE"}

    works = {}
    for entry in result.schedule:
        works[(entry["worker"], entry["date"])] = True

    for sunday_index in data.calendar.sundays():
        day = data.calendar.days[sunday_index]
        if not day.in_report:
            continue
        next_weekend = data.calendar.next_weekend(sunday_index)
        if next_weekend is None:
            continue
        next_sat, next_sun = next_weekend
        next_sat_day = data.calendar.days[next_sat]
        next_sun_day = data.calendar.days[next_sun]
        if not (next_sat_day.in_report and next_sun_day.in_report):
            continue
        for worker in data.worker_groups.core:
            if works.get((worker, day.date.isoformat()), False):
                assert not works.get((worker, next_sat_day.date.isoformat()), False)
                assert not works.get((worker, next_sun_day.date.isoformat()), False)
