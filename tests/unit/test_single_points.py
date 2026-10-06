"""Unit tests for the Single points of failure figures.

The fixture is the seed-shaped query data of `test_blast_radius.py`: five active Gold
services, each with one path through a switch and an edge router.
"""

from __future__ import annotations

from decimal import Decimal

from service_catalog.business_impact.blast_radius import parse_devices
from service_catalog.business_impact.single_points import (
    FAILED,
    failure_headline,
    failure_impact,
    single_points,
    with_device_failed,
)

from .test_blast_radius import build_q1


def test_every_gold_service_has_a_single_point_of_failure() -> None:
    points = single_points(build_q1())

    assert (points.gold_single_point, points.gold_total) == (5, 5)
    assert points.headline == "5 of 5 Gold services have a single point of failure"


def test_devices_are_ranked_by_the_gold_value_that_depends_on_them() -> None:
    rows = [
        (row.label, row.role, row.gold_services, row.customers, row.gold_annual, row.gold_monthly_credit)
        for row in single_points(build_q1()).devices
    ]

    assert rows == [
        ("Paris edge router 1", "Edge router", ("DI-1001", "DI-1002"), ("Northbank",), 123_120, Decimal(2565)),
        ("Paris switch 1", "Switch", ("DI-1001", "DI-1002"), ("Northbank",), 123_120, Decimal(2565)),
        ("Brussels edge router 1", "Edge router", ("DI-2001",), ("Helix Health",), 97_200, Decimal(2025)),
        ("Brussels switch 1", "Switch", ("DI-2001",), ("Helix Health",), 97_200, Decimal(2025)),
        ("Brussels edge router 2", "Edge router", ("DI-2002",), ("Northbank",), 25_920, Decimal(540)),
        ("Brussels switch 2", "Switch", ("DI-2002",), ("Northbank",), 25_920, Decimal(540)),
        ("Paris edge router 2", "Edge router", ("DI-1003",), ("Helix Health",), 25_920, Decimal(540)),
        ("Paris switch 2", "Switch", ("DI-1003",), ("Helix Health",), 25_920, Decimal(540)),
    ]


def test_a_device_already_out_of_service_still_counts_its_gold_services() -> None:
    """The view reads the current network; a device's own status does not change who depends on it."""
    points = single_points(build_q1({"rb01-par01": "maintenance"}))

    assert points.gold_single_point == 5
    assert points.devices[0].label == "Paris edge router 1"


def test_with_device_failed_changes_only_the_selected_device_and_leaves_the_input() -> None:
    data = build_q1()

    failed = with_device_failed(data, "rb01-par01")

    statuses = {device.name: device.status for device in parse_devices(failed)}
    assert statuses["rb01-par01"] == FAILED
    assert {name for name, status in statuses.items() if status != "active"} == {"rb01-par01"}
    assert all(device.status == "active" for device in parse_devices(data))


def test_failure_of_paris_edge_router_1_matches_the_paris_maintenance_figures() -> None:
    result = failure_impact(build_q1(), "rb01-par01")

    assert failure_headline("Paris edge router 1", result) == (
        "If Paris edge router 1 failed now, 2 Gold services for Northbank would have no path"
    )
    assert {tile.label: tile.value for tile in result.tiles} == {
        "Customers affected": "3",
        "Gold services affected": "2 of 5",
        "Gold SLA credit exposure, per month": "€2,565",
    }
    assert [row.service for row in result.affected_rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]


def test_failure_headline_for_one_gold_service_and_for_a_device_without_services() -> None:
    brussels = failure_impact(build_q1(), "sw01-bru01")
    new_york = failure_impact(build_q1(), "rb01-nyc01")

    assert failure_headline("Brussels switch 1", brussels) == (
        "If Brussels switch 1 failed now, 1 Gold service for Helix Health would have no path"
    )
    assert failure_headline("rb01-nyc01", new_york) == "If rb01-nyc01 failed now, every service would keep its path"
