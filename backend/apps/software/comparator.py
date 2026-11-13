"""Software version classification (P1-07). Pure functions; no database access.

States (docs/REPORTING.md):

* ``excluded``    — an active, unexpired approved exception covers the product (and asset, if scoped).
* ``unsupported`` — no approved alias maps the raw name/publisher to a catalogued product.
* ``unknown``     — product identified, but a safe comparison is impossible (reason code says why).
* ``current`` / ``outdated`` / ``newer`` — installed version equal to / lower than / higher than the
  reviewed reference version of the *same* product line (channel/edition/architecture).

This is **version comparison only**. It is never evidence of a missing third-party patch or a vulnerability.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

ALGORITHM_VERSION = "1.0.0"

_DOTTED = re.compile(r"^[vV]?(\d{1,9}(?:\.\d{1,9}){0,5})$")
_PRERELEASE = re.compile(r"(?i)(alpha|beta|preview|rc|pre|dev|nightly|canary|\d[ab]\d)")


class Reason:
    EXCLUDED = "approved_exception"
    NO_ALIAS = "no_approved_alias"
    AMBIGUOUS_ALIAS = "ambiguous_alias"
    NO_REVISION = "no_published_reference"
    AMBIGUOUS_REVISION = "ambiguous_reference"
    ARCH_UNVERIFIABLE = "architecture_unverifiable"
    MISSING_VERSION = "missing_version"
    PRERELEASE_VERSION = "prerelease_version"
    UNPARSEABLE_VERSION = "unparseable_version"
    UNSUPPORTED_SCHEME = "unsupported_version_scheme"
    UNPARSEABLE_REFERENCE = "unparseable_reference"
    EQUAL = "equal_to_reference"
    LOWER = "lower_than_reference"
    HIGHER = "higher_than_reference"


@dataclass(frozen=True)
class AliasRule:
    product_id: str
    name_pattern: str
    publisher_pattern: str
    match_type: str  # exact | prefix


@dataclass(frozen=True)
class ProductInfo:
    id: str
    architecture: str  # any | x64 | x86 | arm64


@dataclass(frozen=True)
class RevisionInfo:
    id: str
    product_id: str
    reference_version: str
    version_scheme: str
    effective_at: datetime


@dataclass(frozen=True)
class ExceptionInfo:
    id: str
    product_id: str
    asset_id: str | None


@dataclass(frozen=True)
class Classification:
    state: str
    reason_code: str
    product_id: str | None = None
    revision_id: str | None = None
    exception_id: str | None = None


def parse_dotted(version: str) -> tuple[int, ...] | None:
    match = _DOTTED.fullmatch((version or "").strip())
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 1.2 == 1.2.0 == 1.2.0.0
        parts.pop()
    return tuple(parts)


def compare_versions(installed: str, reference: str) -> int:
    """-1 / 0 / 1. Callers must have validated both with ``parse_dotted``."""
    a, b = parse_dotted(installed), parse_dotted(reference)
    if a is None or b is None:  # internal contract; explicit so it survives python -O
        raise ValueError("compare_versions requires dotted numeric versions")
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return (a > b) - (a < b)


def match_products(name: str, publisher: str, aliases: Iterable[AliasRule]) -> set[str]:
    name_l, pub_l = name.strip().casefold(), publisher.strip().casefold()
    matched = set()
    for alias in aliases:
        pattern = alias.name_pattern.strip().casefold()
        if alias.match_type == "exact":
            hit = name_l == pattern
        elif alias.match_type == "prefix":
            hit = name_l.startswith(pattern)
        else:
            hit = False
        if hit and alias.publisher_pattern and alias.publisher_pattern.strip().casefold() != pub_l:
            hit = False
        if hit:
            matched.add(alias.product_id)
    return matched


def select_revision(product_id: str, revisions: Sequence[RevisionInfo], at: datetime) -> list[RevisionInfo]:
    """Latest effective published revision(s); more than one at the same instant is ambiguous."""
    candidates = [r for r in revisions if r.product_id == product_id and r.effective_at <= at]
    if not candidates:
        return []
    latest = max(r.effective_at for r in candidates)
    return [r for r in candidates if r.effective_at == latest]


def classify(
    *,
    name: str,
    publisher: str,
    version: str,
    asset_id: str,
    aliases: Sequence[AliasRule],
    products: dict[str, ProductInfo],
    revisions: Sequence[RevisionInfo],
    exceptions: Sequence[ExceptionInfo],
    at: datetime,
) -> Classification:
    product_ids = match_products(name, publisher, aliases)
    if not product_ids:
        return Classification("unsupported", Reason.NO_ALIAS)
    if len(product_ids) > 1:
        return Classification("unknown", Reason.AMBIGUOUS_ALIAS)
    product_id = next(iter(product_ids))

    for exc in exceptions:
        if exc.product_id == product_id and (exc.asset_id is None or exc.asset_id == asset_id):
            return Classification("excluded", Reason.EXCLUDED, product_id=product_id, exception_id=exc.id)

    product = products.get(product_id)
    if product is None:
        return Classification("unknown", Reason.NO_REVISION, product_id=product_id)
    if product.architecture != "any":
        # VSA X InstalledSoftware does not report architecture, so an arch-specific reference can't be applied.
        return Classification("unknown", Reason.ARCH_UNVERIFIABLE, product_id=product_id)

    selected = select_revision(product_id, revisions, at)
    if not selected:
        return Classification("unknown", Reason.NO_REVISION, product_id=product_id)
    if len(selected) > 1:
        return Classification("unknown", Reason.AMBIGUOUS_REVISION, product_id=product_id)
    revision = selected[0]
    if revision.version_scheme != "dotted_numeric":
        return Classification("unknown", Reason.UNSUPPORTED_SCHEME, product_id=product_id, revision_id=revision.id)
    if parse_dotted(revision.reference_version) is None:
        return Classification("unknown", Reason.UNPARSEABLE_REFERENCE, product_id=product_id, revision_id=revision.id)

    if not version.strip():
        return Classification("unknown", Reason.MISSING_VERSION, product_id=product_id, revision_id=revision.id)
    if parse_dotted(version) is None:
        reason = Reason.PRERELEASE_VERSION if _PRERELEASE.search(version) else Reason.UNPARSEABLE_VERSION
        return Classification("unknown", reason, product_id=product_id, revision_id=revision.id)

    cmp = compare_versions(version, revision.reference_version)
    state, reason = {-1: ("outdated", Reason.LOWER), 0: ("current", Reason.EQUAL), 1: ("newer", Reason.HIGHER)}[cmp]
    return Classification(state, reason, product_id=product_id, revision_id=revision.id)
