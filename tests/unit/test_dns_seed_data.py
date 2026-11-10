"""The DNS seed data in data/dns/dns.yml covers the retirement cases the demo shows, and its references resolve."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

DNS_DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "dns" / "dns.yml"


def _objects_by_kind() -> dict[str, list[dict[str, Any]]]:
    objects: dict[str, list[dict[str, Any]]] = {}
    for document in yaml.safe_load_all(DNS_DATA_FILE.read_text(encoding="utf-8")):
        if not document:
            continue
        assert document["apiVersion"] == "infrahub.app/v1"
        assert document["kind"] == "Object"
        objects.setdefault(document["spec"]["kind"], []).extend(document["spec"]["data"])
    return objects


@pytest.fixture(scope="module")
def objects() -> dict[str, list[dict[str, Any]]]:
    return _objects_by_kind()


def _by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in items}


def _record(objects: dict[str, list[dict[str, Any]]], name: str, record_type: str) -> dict[str, Any]:
    matches = [r for r in objects["DnsRecord"] if r["name"] == name and r["record_type"] == record_type]
    assert len(matches) == 1, f"expected one {name} {record_type} record, found {len(matches)}"
    return matches[0]


def _owner_status(objects: dict[str, list[dict[str, Any]]], application: str) -> str:
    teams = _by_name(objects["DnsTeam"])
    return str(teams[_by_name(objects["DnsApplication"])[application]["owner"]]["status"])


def _application_statuses(objects: dict[str, list[dict[str, Any]]], record: dict[str, Any]) -> list[str]:
    applications = _by_name(objects["DnsApplication"])
    return [applications[name]["status"] for name in record.get("applications", [])]


def test_eight_active_records_in_one_zone(objects: dict[str, list[dict[str, Any]]]) -> None:
    assert [zone["name"] for zone in objects["DnsZone"]] == ["example.net"]
    records = objects["DnsRecord"]
    assert len(records) == 8
    assert {record["zone"] for record in records} == {"example.net"}
    assert {record["status"] for record in records} == {"active"}


def test_record_human_friendly_ids_are_unique(objects: dict[str, list[dict[str, Any]]]) -> None:
    keys = [(r["zone"], r["name"], r["record_type"]) for r in objects["DnsRecord"]]
    assert len(keys) == len(set(keys))


def test_active_application_with_active_team(objects: dict[str, list[dict[str, Any]]]) -> None:
    record = _record(objects, "portal", "A")
    assert record["applications"] == ["Customer portal"]
    assert _application_statuses(objects, record) == ["active"]
    assert _owner_status(objects, "Customer portal") == "active"


def test_active_application_with_disbanded_team(objects: dict[str, list[dict[str, Any]]]) -> None:
    record = _record(objects, "invoices", "A")
    assert record["applications"] == ["Invoice archive"]
    assert _application_statuses(objects, record) == ["active"]
    assert _owner_status(objects, "Invoice archive") == "disbanded"


def test_only_a_retired_application(objects: dict[str, list[dict[str, Any]]]) -> None:
    record = _record(objects, "intranet", "A")
    assert record["applications"] == ["Legacy intranet"]
    assert _application_statuses(objects, record) == ["retired"]


def test_no_application(objects: dict[str, list[dict[str, Any]]]) -> None:
    assert not _record(objects, "old-ftp", "A").get("applications")


def test_cname_names_another_seeded_record(objects: dict[str, list[dict[str, Any]]]) -> None:
    cname = _record(objects, "www", "CNAME")
    seeded_hosts = {f"{r['name']}.{r['zone']}." for r in objects["DnsRecord"] if r["record_type"] != "CNAME"}
    assert cname["value"] in seeded_hosts


def test_relationship_values_name_seeded_objects(objects: dict[str, list[dict[str, Any]]]) -> None:
    zones = set(_by_name(objects["DnsZone"]))
    teams = set(_by_name(objects["DnsTeam"]))
    applications = set(_by_name(objects["DnsApplication"]))
    for application in objects["DnsApplication"]:
        assert application["owner"] in teams
    for record in objects["DnsRecord"]:
        assert record["zone"] in zones
        assert set(record.get("applications", [])) <= applications
