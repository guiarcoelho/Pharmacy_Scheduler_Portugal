from __future__ import annotations

from datetime import date

from pharma_scheduler.domain.calendar import Calendar, ServiceCycle


def test_service_week_tagging() -> None:
    calendar = Calendar(
        report_start=date(2026, 1, 1),
        report_end=date(2026, 2, 15),
        buffer_days=0,
        service_cycle=ServiceCycle(
            anchor_monday=date(2026, 1, 5),
            cycle_weeks=4,
            service_week_in_cycle=4,
        ),
        locale="PT",
    )

    service_week_start = date(2026, 1, 26)
    non_service_week_start = date(2026, 2, 2)

    assert calendar.days[calendar.date_to_index[service_week_start]].is_service_week
    assert not calendar.days[calendar.date_to_index[non_service_week_start]].is_service_week
