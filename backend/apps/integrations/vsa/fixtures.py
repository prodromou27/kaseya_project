"""Offline VSA X emulation for fixture instances and contract tests. Never touches the network.

Implements only the documented behaviour the adapter relies on: ``$top`` (capped at 100), ``$skip``,
``$filter=OrganizationId eq <int>``, ``$orderby=Identifier`` and the ``{Data, Meta}`` envelope. Anything else
returns HTTP 400, so an adapter change that depends on undocumented behaviour fails the tests.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_FILTER = re.compile(r"^OrganizationId eq ([0-9]+)$")


@dataclass
class FakeResponse:
    status_code: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if isinstance(self.body, Exception):
            raise self.body
        return copy.deepcopy(self.body)


class FixtureVsaTransport:
    def __init__(
        self,
        assets: list[dict[str, Any]],
        organizations: list[dict[str, Any]] | None = None,
        *,
        scripted: list[FakeResponse | Exception] | None = None,
        on_request: Callable[[str, Mapping[str, str]], None] | None = None,
    ):
        self.assets = assets
        self.organizations = organizations or []
        self.scripted = list(scripted or [])  # responses returned (in order) before normal behaviour
        self.on_request = on_request
        self.calls: list[tuple[str, dict[str, str]]] = []

    @classmethod
    def for_instance(cls, instance: Any) -> FixtureVsaTransport:
        from .demo_data import demo_tenant

        tenant = demo_tenant()
        return cls(tenant["assets"], tenant["organizations"])

    def get(self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str], auth: Any) -> FakeResponse:
        params = dict(params)
        path = re.sub(r"^https://[^/]+", "", url)
        self.calls.append((path, params))
        if self.on_request:
            self.on_request(path, params)
        if self.scripted:
            item = self.scripted.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        try:
            top = int(params.get("$top", "100"))
            skip = int(params.get("$skip", "0"))
        except ValueError:
            return FakeResponse(400)
        if top < 1 or skip < 0:
            return FakeResponse(400)
        top = min(top, 100)
        if path == "/api/v3/assets":
            rows = self.assets
            flt = params.get("$filter")
            if flt is not None:
                match = _FILTER.fullmatch(flt)
                if not match:
                    return FakeResponse(400)
                rows = [a for a in rows if str(a.get("OrganizationId")) == match.group(1)]
            if params.get("$orderby") not in (None, "Identifier"):
                return FakeResponse(400)
            rows = sorted(rows, key=lambda a: str(a.get("Identifier", "")))
            return FakeResponse(
                200, {"Data": rows[skip : skip + top], "Meta": {"TotalCount": len(rows), "ResponseCode": 200}}
            )
        if path == "/api/v3/organizations":
            rows = self.organizations
            return FakeResponse(
                200, {"Data": rows[skip : skip + top], "Meta": {"TotalCount": len(rows), "ResponseCode": 200}}
            )
        return FakeResponse(404)
