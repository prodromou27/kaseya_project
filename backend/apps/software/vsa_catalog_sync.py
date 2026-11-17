"""CAT-02: keep reference versions current from the public VSA 10 Application Catalog page, daily.

* One HTTPS GET of the fixed catalog page (no credentials, TLS verified, no redirects, size-capped, destination must
  resolve to a public address). The URL is a constant, never configurable, so this cannot be pointed elsewhere.
* The table is matched to installed programs exactly as the paste import does (``vsa_catalog.build``).
* **Applied automatically** (product owner decision, 2026-11-17): a *higher* catalog version for a product that already
  has an approved reference, with no warning. Recorded as an approved import by the "VSA catalog (automatic)"
  account and audited.
* **Waits for approval:** new products, decreases and anything with a warning, as one pending import. A newer check
  supersedes the previous automatic pending import instead of piling them up.
* New installed names for an existing product are added as *proposed* aliases (reviewed before they classify).
"""

from __future__ import annotations

import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.integrations.http import RequestsTransport, check_resolved_addresses, default_resolver

from .catalog import ImportRowSerializer, _product_key, schedule_reevaluation
from .models import CatalogImport, CatalogRevision, ReviewStatus, SoftwareAlias, SoftwareProduct, VsaCatalogCheck
from .vsa_catalog import CATALOG_URL, build

logger = logging.getLogger("portal.catalog")

SYSTEM_EMAIL = "vsa-catalog@system.invalid"
MAX_BYTES = 5 * 1024 * 1024
_LAST_UPDATED = re.compile(r"Last updated:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")


class CatalogFetchError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _TableText(HTMLParser):
    """Collects every table row as tab-joined cell text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.lines.append("\t".join(self._row))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def page_to_text(html: str) -> tuple[str, str]:
    """(tab-separated table text, 'Last updated' date as stated on the page)."""
    parser = _TableText()
    parser.feed(html)
    plain = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    match = _LAST_UPDATED.search(plain)
    return "\n".join(parser.lines), match.group(1) if match else ""


def fetch(transport: Any = None, resolver: Any = None) -> str:
    host = urlsplit(CATALOG_URL).hostname or ""
    try:
        check_resolved_addresses(host, "vsa_catalog", resolver or default_resolver)
    except Exception as exc:  # EgressBlocked / VendorUnavailable
        raise CatalogFetchError("egress_blocked" if "blocked" in type(exc).__name__.lower() else "unreachable") from exc
    try:
        response = (transport or RequestsTransport()).get(
            CATALOG_URL, params={}, headers={"Accept": "text/html", "User-Agent": "odyssey-portal-catalog"}, auth=None
        )
    except Exception as exc:
        raise CatalogFetchError("unreachable") from exc
    if response.status_code != 200:
        raise CatalogFetchError(f"http_{response.status_code}")
    content = response.content or b""
    if len(content) > MAX_BYTES:
        raise CatalogFetchError("too_large")
    return content.decode(response.encoding or "utf-8", errors="replace")


def system_user() -> Any:
    from apps.accounts.models import User

    user = User.objects.filter(email=SYSTEM_EMAIL).first()
    if user is None:
        user = User(email=SYSTEM_EMAIL, display_name="VSA catalog (automatic)", is_active=False)
        user.set_unusable_password()
        user.save()
    return user


def _row_identity(rows: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return sorted((r["vendor"], r["product"], r["reference_version"]) for r in rows)


def _apply(rows: list[dict[str, Any]], preview: list[dict[str, Any]], actor: Any) -> CatalogImport:
    """Publish version increases for already-approved products. New aliases are only proposed."""
    now = timezone.now()
    imp = CatalogImport.objects.create(
        rows=rows,
        preview=preview,
        created_by=actor,
        state=CatalogImport.State.APPROVED,
        reviewed_by=actor,
        reviewed_at=now,
        review_note="Applied automatically: higher version in the VSA application catalog for an approved product.",
    )
    for raw in rows:
        s = ImportRowSerializer(data=raw)
        s.is_valid(raise_exception=True)
        row = s.validated_data
        product = SoftwareProduct.objects.get(**_product_key(row))
        CatalogRevision.objects.create(
            product=product,
            reference_version=row["reference_version"],
            version_scheme=row["version_scheme"],
            vendor_url=row["vendor_url"],
            source_type=row["source_type"],
            source_checked_at=row["source_checked_at"],
            effective_at=now,
            catalog_import=imp,
            created_by=actor,
            reviewed_by=actor,
            reviewed_at=now,
        )
        for alias in row["aliases"]:
            SoftwareAlias.objects.get_or_create(
                product=product,
                name_pattern=alias["name_pattern"].strip(),
                publisher_pattern=alias["publisher_pattern"].strip(),
                match_type=alias["match_type"],
                defaults={"review_status": ReviewStatus.PROPOSED, "created_by": actor},
            )
    return imp


def _pending(rows: list[dict[str, Any]], preview: list[dict[str, Any]], actor: Any) -> CatalogImport | None:
    """One pending automatic import at a time; an identical one is kept, an older different one superseded."""
    open_imports = list(CatalogImport.objects.filter(created_by=actor, state=CatalogImport.State.PENDING))
    for existing in open_imports:
        if rows and _row_identity(existing.rows) == _row_identity(rows):
            return existing
    for existing in open_imports:
        existing.state, existing.reviewed_at = CatalogImport.State.REJECTED, timezone.now()
        existing.review_note = "Superseded by a newer automatic check of the VSA application catalog."
        existing.save(update_fields=["state", "reviewed_at", "review_note"])
    if not rows:
        return None
    return CatalogImport.objects.create(rows=rows, preview=preview, created_by=actor)


def run(*, trigger: str = "schedule", user: Any = None, transport: Any = None, resolver: Any = None) -> VsaCatalogCheck:
    check = VsaCatalogCheck.objects.create(trigger=trigger, triggered_by=user)
    if not settings.VSA_APP_CATALOG_AUTO_UPDATE and trigger == "schedule":
        return _finish(check, VsaCatalogCheck.Outcome.DISABLED)
    try:
        text, last_updated = page_to_text(fetch(transport, resolver))
        check.catalog_last_updated = last_updated
        result = build(text)
    except CatalogFetchError as exc:
        return _finish(check, VsaCatalogCheck.Outcome.FAILED, exc.code)
    except Exception as exc:  # the page changed shape, or nothing matched the expected table
        logger.warning("vsa_catalog_parse_failed", extra={"error": type(exc).__name__})
        return _finish(check, VsaCatalogCheck.Outcome.FAILED, "page_format_changed")

    auto, review = [], []
    for row, meta, prev in zip(result["rows"], result["matched"], result["preview"], strict=True):
        safe = prev.get("change") == "version_up" and not prev.get("warnings") and not meta["warnings"]
        (auto if safe else review).append((row, prev))
    actor = system_user()
    with transaction.atomic():
        if auto:
            check.applied_import = _apply([r for r, _ in auto], [p for _, p in auto], actor)
            check.applied = len(auto)
            schedule_reevaluation()
        check.pending_import = _pending([r for r, _ in review], [p for _, p in review], actor)
        check.stats = {
            **result["stats"],
            "applied": len(auto),
            "waiting_for_review": len(review),
            "skipped_list": result["skipped"][:200],
            "not_installed_list": result["not_installed_programs"],
        }
        outcome = VsaCatalogCheck.Outcome.UPDATED if auto or review else VsaCatalogCheck.Outcome.NO_CHANGE
        _finish(check, outcome)
    record_event(
        action="catalog.vsa_auto_update",
        outcome="success",
        actor=user or actor,
        target_type="vsa_catalog_check",
        target_id=str(check.id),
        metadata={
            "trigger": trigger,
            "applied": [f"{r['product']} {r['reference_version']}" for r, _ in auto][:50],
            "waiting_for_review": len(review),
            "catalog_last_updated": check.catalog_last_updated,
        },
    )
    return check


def _finish(check: VsaCatalogCheck, outcome: str, error_code: str = "") -> VsaCatalogCheck:
    check.outcome, check.error_code, check.finished_at = outcome, error_code, timezone.now()
    check.save()
    if outcome == VsaCatalogCheck.Outcome.FAILED:
        record_event(
            action="catalog.vsa_auto_update",
            outcome="failure",
            actor=check.triggered_by,
            target_type="vsa_catalog_check",
            target_id=str(check.id),
            metadata={"error_code": error_code},
        )
    return check
