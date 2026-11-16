"""Workflow run health per customer and the tenant-wide automation catalog (read-only)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from .models import (
    AutomationCollection,
    AutomationScope,
    AutomationTask,
    AutomationWorkflow,
    PatchGlobalRules,
    WorkflowExecution,
)

TASK_LIMITATION = (
    "VSA X does not offer a read-only way to list scheduled task runs, so task results are not shown; "
    "workflow results are."
)


def _collections(instance_ids: set[Any]) -> list[dict[str, Any]]:
    return [
        {
            "integration": c.integration_instance.name,
            "status": c.status,
            "error_code": c.error_code,
            "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
        }
        for c in AutomationCollection.objects.filter(integration_instance_id__in=instance_ids).select_related(
            "integration_instance"
        )
    ]


class CustomerAutomationViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/automation/?days=7&status=Failed&workflow=`` - workflow runs on this customer's devices."""

    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from apps.customers.models import CustomerSourceMapping
        from apps.inventory.queries import current_observations

        customer = self.get_customer()
        try:
            days = int(request.query_params.get("days", 7))
        except ValueError as exc:
            raise ValidationError({"days": "Use a number of days."}) from exc
        if not 1 <= days <= 90:
            raise ValidationError({"days": "Use 1 to 90 days."})
        runs = list(
            WorkflowExecution.objects.filter(customer=customer, created_at__gte=timezone.now() - timedelta(days=days))
        )
        names = {
            (str(w.integration_instance_id), w.external_id): w.name
            for w in AutomationWorkflow.objects.filter(
                integration_instance_id__in={r.integration_instance_id for r in runs}
            )
        }
        hosts = dict(current_observations(customer.id).values_list("asset_id", "hostname"))
        per: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"runs": 0, "failed": 0, "last_failure_at": None}
        )
        for r in runs:
            p = per[(str(r.integration_instance_id), r.workflow_external_id)]
            p["runs"] += 1
            if r.status == "Failed":
                p["failed"] += 1
                if p["last_failure_at"] is None or r.created_at > p["last_failure_at"]:
                    p["last_failure_at"] = r.created_at
        workflows = sorted(
            (
                {
                    "workflow_id": wid,
                    "name": names.get((iid, wid), f"Workflow {wid}"),
                    "runs": p["runs"],
                    "failed": p["failed"],
                    "success_pct": round(100 * (p["runs"] - p["failed"]) / p["runs"], 1) if p["runs"] else None,
                    "last_failure_at": p["last_failure_at"].isoformat() if p["last_failure_at"] else None,
                }
                for (iid, wid), p in per.items()
            ),
            key=lambda w: (-w["failed"], w["name"].casefold()),
        )
        status = request.query_params.get("status", "Failed")
        workflow = request.query_params.get("workflow", "")
        shown = [
            r
            for r in runs
            if (not status or r.status == status) and (not workflow or r.workflow_external_id == workflow)
        ]
        executions = [
            {
                "id": str(r.id),
                "workflow_id": r.workflow_external_id,
                "workflow": names.get(
                    (str(r.integration_instance_id), r.workflow_external_id), f"Workflow {r.workflow_external_id}"
                ),
                "asset_id": str(r.asset_id) if r.asset_id else None,
                "hostname": hosts.get(r.asset_id, r.target_id),
                "status": r.status,
                "trigger_type": r.trigger_type,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "failed_step": r.failed_step,
            }
            for r in shown[:500]
        ]
        instances = set(
            CustomerSourceMapping.objects.filter(customer=customer, mapping_status="approved").values_list(
                "integration_instance_id", flat=True
            )
        )
        return Response(
            {
                "days": days,
                "totals": {
                    "runs": len(runs),
                    "failed": sum(1 for r in runs if r.status == "Failed"),
                    "devices_with_failures": len({r.asset_id for r in runs if r.status == "Failed"}),
                },
                "workflows": workflows,
                "executions": executions,
                "collection": _collections(instances),
                "task_limitation": TASK_LIMITATION,
            }
        )


def _scopes(workflows: Any, tasks: Any) -> list[dict[str, Any]]:
    """Scopes with criteria, device count and the named tasks/workflows that use them."""
    names = {("Workflow", w.integration_instance_id, w.external_id): w.name for w in workflows}
    names |= {("Task", t.integration_instance_id, t.external_id): t.name for t in tasks}
    return [
        {
            "integration": s.integration_instance.name,
            "id": s.external_id,
            "name": s.name,
            "description": s.description,
            "criteria": s.criteria,
            "total_devices": s.total_devices,
            "used_by": [
                {**u, "name": names.get((u.get("type"), s.integration_instance_id, u.get("id")), "")} for u in s.used_by
            ],
        }
        for s in AutomationScope.objects.select_related("integration_instance").order_by("name")
    ]


class AutomationCatalogView(APIView):
    """``GET /automation/catalog/`` - tenant-wide workflows and tasks (super admin). Definitions only."""

    permission_classes = [IsSystemAdmin]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        wf = AutomationWorkflow.objects.select_related("integration_instance").order_by("name")
        tasks = AutomationTask.objects.select_related("integration_instance").order_by("name")
        return Response(
            {
                "workflows": [
                    {
                        "integration": w.integration_instance.name,
                        "id": w.external_id,
                        "name": w.name,
                        "enabled": w.enabled,
                        "trigger": " / ".join(x for x in (w.trigger_type, w.trigger_subtype) if x),
                        "context": w.context_type,
                        "folder": w.folder_path,
                        "updated": w.updated_at_raw,
                    }
                    for w in wf
                ],
                "tasks": [
                    {
                        "integration": t.integration_instance.name,
                        "id": t.external_id,
                        "name": t.name,
                        "enabled": t.enabled,
                        "scheduled": t.scheduled,
                        "scope": t.scope_name,
                        "state": t.execution_state,
                        "scripts": t.total_scripts,
                        "built_in": t.built_in,
                        "folder": t.folder_path,
                        "updated": t.updated_at_raw,
                    }
                    for t in tasks
                ],
                "scopes": _scopes(wf, tasks),
                "global_rules": [
                    {
                        "integration": g.integration_instance.name,
                        "os_rules": g.os_rules,
                        "software_rules": g.software_rules,
                        "fetched_at": g.fetched_at,
                    }
                    for g in PatchGlobalRules.objects.select_related("integration_instance")
                ],
                "collection": _collections(
                    set(AutomationCollection.objects.values_list("integration_instance_id", flat=True))
                ),
                "task_limitation": TASK_LIMITATION,
            }
        )
