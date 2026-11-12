"""Software reference catalog import: validate → preview → reviewer approval → immutable revisions (P1-06).

Poisoned reference versions are a listed threat (SECURITY.md §1), so approval requires a reviewer different from
the importer (``CATALOG_REQUIRE_SEPARATE_REVIEWER``, default on) and version *decreases* are flagged in preview.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .comparator import compare_versions, parse_dotted
from .models import CatalogImport, CatalogRevision, ReviewStatus, SoftwareAlias, SoftwareProduct

MAX_ROWS = 500
SOURCE_TYPES = ["vendor_release_notes", "vendor_feed", "manual_verification"]


class AliasInputSerializer(serializers.Serializer):
    name_pattern = serializers.CharField(max_length=255)
    publisher_pattern = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    match_type = serializers.ChoiceField(choices=SoftwareAlias.MatchType.choices, default="exact")


class ImportRowSerializer(serializers.Serializer):
    vendor = serializers.CharField(max_length=120)
    product = serializers.CharField(max_length=160)
    edition = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    platform = serializers.CharField(max_length=32, required=False, default="windows")
    channel = serializers.CharField(max_length=32, required=False, default="stable")
    architecture = serializers.ChoiceField(choices=SoftwareProduct.Architecture.choices, default="any")
    reference_version = serializers.CharField(max_length=64)
    version_scheme = serializers.ChoiceField(choices=CatalogRevision.Scheme.choices, default="dotted_numeric")
    vendor_url = serializers.URLField(max_length=500)
    source_type = serializers.ChoiceField(choices=SOURCE_TYPES)
    source_checked_at = serializers.DateTimeField()
    effective_at = serializers.DateTimeField(required=False)
    aliases = AliasInputSerializer(many=True, required=False, default=list)

    def validate_vendor_url(self, value: str) -> str:
        if not value.startswith("https://"):
            raise serializers.ValidationError("Evidence URL must be https.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["version_scheme"] == "dotted_numeric" and parse_dotted(attrs["reference_version"]) is None:
            raise serializers.ValidationError({"reference_version": "Not a dotted numeric version."})
        if attrs["source_checked_at"] > timezone.now():
            raise serializers.ValidationError({"source_checked_at": "Cannot be in the future."})
        return attrs


def _product_key(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in ("vendor", "product", "edition", "platform", "channel", "architecture")}


def build_preview(rows: list[Any]) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(rows, list) or not rows:
        raise serializers.ValidationError({"rows": "Provide a non-empty list of rows."})
    if len(rows) > MAX_ROWS:
        raise serializers.ValidationError({"rows": f"At most {MAX_ROWS} rows per import."})
    preview, valid = [], True
    for index, raw in enumerate(rows):
        s = ImportRowSerializer(data=raw)
        if not s.is_valid():
            valid = False
            preview.append({"index": index, "status": "error", "errors": s.errors})
            continue
        row = s.validated_data
        product = SoftwareProduct.objects.filter(**_product_key(row)).first()
        current = None
        if product:
            current = (
                CatalogRevision.objects.filter(product=product, state="published", effective_at__lte=timezone.now())
                .order_by("-effective_at")
                .first()
            )
        change, warnings = "new_product" if product is None else "new_reference", []
        if current is not None and current.version_scheme == row["version_scheme"] == "dotted_numeric":
            cmp = compare_versions(row["reference_version"], current.reference_version)
            change = {1: "version_up", 0: "same_version", -1: "version_down"}[cmp]
            if cmp < 0:
                warnings.append("Reference version is LOWER than the current published reference.")
        if row["architecture"] != "any":
            warnings.append("Architecture-specific products cannot be compared: VSA X does not report architecture.")
        if not row["aliases"] and product is None:
            warnings.append("New product without aliases will not match any installation.")
        preview.append(
            {
                "index": index,
                "status": "ok",
                "change": change,
                "warnings": warnings,
                "product": " ".join(v for v in _product_key(row).values() if v),
                "current_reference": current.reference_version if current else None,
                "new_reference": row["reference_version"],
                "aliases": len(row["aliases"]),
            }
        )
    return preview, valid


def check_reviewer(created_by_id: Any, reviewer: Any) -> None:
    if getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True) and created_by_id == reviewer.pk:
        raise serializers.ValidationError({"detail": "A different reviewer must approve catalog changes."})


def approve_import(catalog_import: CatalogImport, reviewer: Any) -> list[CatalogRevision]:
    check_reviewer(catalog_import.created_by_id, reviewer)
    created: list[CatalogRevision] = []
    with transaction.atomic():
        locked = CatalogImport.objects.select_for_update().get(pk=catalog_import.pk)
        if locked.state != CatalogImport.State.PENDING:
            raise serializers.ValidationError({"state": f"Import is {locked.state}."})
        now = timezone.now()
        for raw in locked.rows:
            s = ImportRowSerializer(data=raw)
            s.is_valid(raise_exception=True)
            row = s.validated_data
            product, _ = SoftwareProduct.objects.get_or_create(**_product_key(row))
            created.append(
                CatalogRevision.objects.create(
                    product=product,
                    reference_version=row["reference_version"],
                    version_scheme=row["version_scheme"],
                    vendor_url=row["vendor_url"],
                    source_type=row["source_type"],
                    source_checked_at=row["source_checked_at"],
                    effective_at=row.get("effective_at") or now,
                    catalog_import=locked,
                    created_by_id=locked.created_by_id,
                    reviewed_by=reviewer,
                    reviewed_at=now,
                )
            )
            for alias in row["aliases"]:
                SoftwareAlias.objects.get_or_create(
                    product=product,
                    name_pattern=alias["name_pattern"].strip(),
                    publisher_pattern=alias["publisher_pattern"].strip(),
                    match_type=alias["match_type"],
                    defaults={
                        "review_status": ReviewStatus.APPROVED,
                        "created_by_id": locked.created_by_id,
                        "reviewed_by": reviewer,
                        "reviewed_at": now,
                    },
                )
        locked.state, locked.reviewed_by, locked.reviewed_at = CatalogImport.State.APPROVED, reviewer, now
        locked.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        schedule_reevaluation()
    return created


def schedule_reevaluation(customer_id: Any = None) -> None:
    from .tasks import reevaluate_compliance

    arg = str(customer_id) if customer_id else None
    transaction.on_commit(lambda: reevaluate_compliance.delay(arg))
