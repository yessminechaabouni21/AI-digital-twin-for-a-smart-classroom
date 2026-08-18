"""Focused tests for classroom_skill_priority_demo's roster-truncation reporting."""

from __future__ import annotations

from scripts.classroom_skill_priority_demo import _roster_status_line


def test_roster_status_line_reports_capped_roster() -> None:
    assert _roster_status_line(15, 148) == "students used: 15 / 148 eligible (capped)"


def test_roster_status_line_reports_complete_roster() -> None:
    assert _roster_status_line(5, 5) == "students used: 5 / 5 eligible"


def test_roster_status_line_reports_empty_class() -> None:
    assert _roster_status_line(0, 0) == "students used: 0 / 0 eligible"
