from __future__ import annotations


def test_weekend_coupling(solved_small_instance) -> None:
    _, data, result = solved_small_instance
    assert result.status in {"OPTIMAL", "FEASIBLE"}

    works = {}
    for entry in result.schedule:
        works[(entry["worker"], entry["date"])] = True

    for sat_idx, sun_idx in data.calendar.saturday_sunday_pairs():
        sat = data.calendar.days[sat_idx]
        sun = data.calendar.days[sun_idx]
        if not (sat.in_report and sun.in_report):
            continue
        for worker in data.worker_groups.core:
            sat_work = works.get((worker, sat.date.isoformat()), False)
            sun_work = works.get((worker, sun.date.isoformat()), False)
            assert sat_work == sun_work
