from typing import Any

from checks.restricted_prefix_guard import RestrictedPrefixCheck

BRANCHED_FROM = "2026-09-08T10:00:00Z"
BEFORE = "2026-09-08T09:00:00+00:00"
AFTER = "2026-09-08T11:00:00+00:00"

ADMIN = {"id": "admin-id", "display_label": "Admin"}
JOHN = {"id": "john-id", "display_label": "John"}


def build_data(*, updated_at: str, updated_by: dict[str, str], is_default: bool = False) -> dict[str, Any]:
    return {
        "Branch": [
            {"name": "main", "is_default": True, "branched_from": BRANCHED_FROM},
            {"name": "change-01", "is_default": is_default, "branched_from": BRANCHED_FROM},
        ],
        "authorized_accounts": [ADMIN["id"]],
        "IpamPrefix": {
            "edges": [
                {
                    "node": {
                        "id": "prefix-id",
                        "display_label": "10.10.0.0/24",
                        "prefix": {"updated_at": BEFORE, "updated_by": ADMIN},
                        "status": {"updated_at": updated_at, "updated_by": updated_by},
                    }
                }
            ]
        },
    }


def run(data: dict[str, Any], branch: str = "change-01") -> list[dict[str, Any]]:
    check = RestrictedPrefixCheck(branch=branch)
    check.validate(data=data)
    errors: list[dict[str, Any]] = check.errors
    return errors


def test_unauthorized_change_on_branch_is_rejected() -> None:
    errors = run(build_data(updated_at=AFTER, updated_by=JOHN))
    assert len(errors) == 1
    assert "'John' changed status" in errors[0]["message"]
    assert errors[0]["object_id"] == "prefix-id"


def test_authorized_change_on_branch_passes() -> None:
    assert run(build_data(updated_at=AFTER, updated_by=ADMIN)) == []


def test_change_predating_the_branch_is_ignored() -> None:
    assert run(build_data(updated_at=BEFORE, updated_by=JOHN)) == []


def test_default_branch_is_skipped() -> None:
    assert run(build_data(updated_at=AFTER, updated_by=JOHN, is_default=True)) == []


def test_unknown_branch_fails_closed() -> None:
    errors = run(build_data(updated_at=AFTER, updated_by=ADMIN), branch="does-not-exist")
    assert len(errors) == 1
    assert "was not found" in errors[0]["message"]
