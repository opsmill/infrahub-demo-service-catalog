"""Guard restricted prefixes against changes by unauthorised accounts.

Infrahub grants object permissions per *kind*, not per instance, so "only these people may
touch our regulated networks" has no direct RBAC expression. Routing writes through a branch
closes the gap: the change lands on a branch first, this check reads the ``updated_by``
Infrahub recorded against each attribute on that branch, and a logged error blocks the merge.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from infrahub_sdk.checks import InfrahubCheck

if TYPE_CHECKING:
    from collections.abc import Iterator

AUTHORIZED_GROUP = "restricted-network-admins"


def _parse(timestamp: str) -> datetime:
    """Parse an Infrahub timestamp -- "Z" on branch fields, "+00:00" on attribute ones."""
    return datetime.fromisoformat(timestamp)


class RestrictedPrefixCheck(InfrahubCheck):
    query = "restricted_prefixes"

    async def collect_data(self) -> dict:
        """Add the allowlist, read from the default branch rather than the proposal's branch.

        A branch sees the default branch as it was when the branch opened, so a membership
        change made after that point would be invisible to the stored query -- the wrong
        semantics for an authority list.
        """
        response: dict[str, Any] = await super().collect_data()
        group = await self.client.get(
            kind="CoreAccountGroup",
            name__value=AUTHORIZED_GROUP,
            branch=self.client.default_branch,
            include=["members"],
            raise_when_missing=False,
        )
        payload = response.get("data") or response
        payload["authorized_accounts"] = [member.id for member in group.members.peers] if group else []
        return response

    def validate(self, data: dict[str, Any]) -> None:
        branch = self._branch(data)
        if branch is None:
            self.log_error(message=f"Branch '{self.branch_name}' was not found, refusing to pass the check")
            return

        if branch["is_default"]:
            # Nothing to block on the default branch -- the change is already authoritative.
            return

        branched_from = _parse(branch["branched_from"])
        authorized = set(data.get("authorized_accounts", []))

        for edge in data.get("IpamPrefix", {}).get("edges", []):
            prefix = edge["node"]
            # One error per offending account, not per attribute -- a single create touches every one.
            offenders: dict[str, set[str]] = defaultdict(set)
            for attribute, account_id, account_name in self._changed_since(prefix, branched_from):
                if account_id not in authorized:
                    offenders[account_name].add(attribute)

            for account_name, attributes in offenders.items():
                self.log_error(
                    message=(
                        f"'{account_name}' changed {', '.join(sorted(attributes))} on restricted prefix "
                        f"'{prefix['display_label']}' but is not a member of '{AUTHORIZED_GROUP}'"
                    ),
                    object_id=prefix["id"],
                    object_type="IpamPrefix",
                )

    def _branch(self, data: dict[str, Any]) -> dict[str, Any] | None:
        return next((branch for branch in data.get("Branch", []) if branch["name"] == self.branch_name), None)

    @staticmethod
    def _changed_since(prefix: dict[str, Any], branched_from: datetime) -> Iterator[tuple[str, str, str]]:
        """Yield (attribute, account id, account name) for every attribute written on this branch."""
        for name, attribute in prefix.items():
            if not isinstance(attribute, dict) or "updated_by" not in attribute:
                continue
            if _parse(attribute["updated_at"]) < branched_from:
                continue
            account = attribute["updated_by"] or {}
            yield name, account.get("id", ""), account.get("display_label", "An unknown account")
