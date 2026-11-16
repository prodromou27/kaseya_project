"""Collect VSA X automation inventory and recent workflow executions for one integration (read-only, throttled)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    AutomationCollection,
    AutomationScript,
    AutomationTask,
    AutomationWorkflow,
    DeviceScriptValue,
    ScriptCollector,
    WorkflowExecution,
)

logger = logging.getLogger(__name__)
MIN_INTERVAL = timedelta(minutes=30)
WINDOW = timedelta(days=30)
DETAIL_BUDGET = 25  # failed executions whose step outcome is fetched per collection


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else timezone.make_aware(parsed, UTC)


def _text(value: Any, limit: int = 255) -> str:
    return str(value)[:limit] if value is not None else ""


def collect(instance: Any, adapter: Any, *, force: bool = False) -> str:
    """Returns the collection status. Never raises: automation is optional context, not inventory."""
    from apps.integrations.http import ConnectorError, VendorAuthError, VendorClientError
    from apps.inventory.models import Asset

    state, _ = AutomationCollection.objects.get_or_create(integration_instance=instance)
    now = timezone.now()
    if not force and state.last_attempt_at and now - state.last_attempt_at < MIN_INTERVAL:
        return "skipped"
    state.last_attempt_at = now
    try:
        for row in adapter.list_workflows():
            if row.get("Id") is None:
                continue
            AutomationWorkflow.objects.update_or_create(
                integration_instance=instance,
                external_id=_text(row["Id"], 20),
                defaults={
                    "name": _text(row.get("Name")) or f"Workflow {row['Id']}",
                    "enabled": row.get("IsEnabled") if isinstance(row.get("IsEnabled"), bool) else None,
                    "trigger_type": _text(row.get("TriggerType"), 64),
                    "trigger_subtype": _text(row.get("TriggerSubType"), 128),
                    "context_type": _text(row.get("ContextType"), 32),
                    "folder_path": _text(row.get("FolderPath"), 500),
                    "updated_at_raw": _text(row.get("UpdatedAt"), 40),
                    "seen_at": now,
                },
            )
        for row in adapter.list_tasks():
            if row.get("Id") is None:
                continue

            def flag(key: str, r: dict[str, Any] = row) -> bool | None:
                return r.get(key) if isinstance(r.get(key), bool) else None

            AutomationTask.objects.update_or_create(
                integration_instance=instance,
                external_id=_text(row["Id"], 20),
                defaults={
                    "name": _text(row.get("Name")) or f"Task {row['Id']}",
                    "enabled": flag("IsEnabled"),
                    "scheduled": flag("IsScheduled"),
                    "scope_id": _text(row.get("ScopeId"), 20),
                    "scope_name": _text(row.get("ScopeName")),
                    "execution_state": _text(row.get("ExecutionState"), 32),
                    "total_scripts": row.get("TotalScripts") if isinstance(row.get("TotalScripts"), int) else None,
                    "built_in": flag("IsBuiltIn"),
                    "folder_path": _text(row.get("FolderPath"), 500),
                    "updated_at_raw": _text(row.get("UpdatedAt"), 40),
                    "seen_at": now,
                },
            )
        for row in adapter.list_scripts():
            if row.get("Id") is None:
                continue
            AutomationScript.objects.update_or_create(
                integration_instance=instance,
                external_id=_text(row["Id"], 64),
                defaults={
                    "name": _text(row.get("Name")) or f"Script {row['Id']}",
                    "category": _text(row.get("CategoryName")),
                    "platforms": [str(x)[:20] for x in row.get("Platforms") or [] if isinstance(x, str)][:5],
                    "built_in": row.get("IsBuiltIn") if isinstance(row.get("IsBuiltIn"), bool) else None,
                    "folder_path": _text(row.get("FolderPath"), 500),
                    "seen_at": now,
                },
            )
        assets = dict(Asset.objects.filter(integration_instance=instance).values_list("external_id", "id"))
        customers = dict(Asset.objects.filter(integration_instance=instance).values_list("id", "customer_id"))
        cutoff = now - WINDOW
        done = False
        for records in adapter.iter_workflow_executions():
            for row in records:
                created = _dt(row.get("CreatedAt"))
                if created is None or row.get("Id") is None:
                    continue
                if created < cutoff:
                    done = True
                    break
                target = _text(row.get("TargetId"), 64)
                asset_id = assets.get(target) if row.get("TargetType") == "Device" else None
                WorkflowExecution.objects.update_or_create(
                    integration_instance=instance,
                    external_id=_text(row["Id"], 20),
                    defaults={
                        "workflow_external_id": _text(row.get("WorkflowId"), 20),
                        "target_type": _text(row.get("TargetType"), 16),
                        "target_id": target,
                        "asset_id": asset_id,
                        "customer_id": customers.get(asset_id) if asset_id else None,
                        "trigger_type": _text(row.get("TriggerType"), 64),
                        "status": _text(row.get("Status"), 16) or "Unknown",
                        "created_at": created,
                        "completed_at": _dt(row.get("CompletedAt")),
                    },
                )
            if done:
                break
        # Failed-step outcome for recent failures (budgeted). Step output items are never stored.
        for ex in WorkflowExecution.objects.filter(
            integration_instance=instance, status="Failed", detail_fetched=False, customer__isnull=False
        ).order_by("-created_at")[:DETAIL_BUDGET]:
            try:
                body = adapter.get_workflow_execution(ex.external_id)
                steps = (body or {}).get("Data", {}).get("ExecutionSteps") or []
                failed = next((s for s in steps if isinstance(s, dict) and s.get("Status") == "Failed"), None)
                ex.failed_step = _text(failed.get("Outcome"), 300) if failed else ""
            except (VendorClientError, ValueError, AttributeError):
                pass
            ex.detail_fetched = True
            ex.save(update_fields=["failed_step", "detail_fetched"])
        WorkflowExecution.objects.filter(
            integration_instance=instance, created_at__lt=now - timedelta(days=90)
        ).delete()
        state.status, state.error_code, state.last_success_at = "ok", "", now
    except VendorAuthError:
        state.status, state.error_code = "not_permitted", "auth_failed"
    except VendorClientError as exc:
        # 403/404: the token may lack automation permission or the tenant has no automation module.
        state.status, state.error_code = "not_permitted", f"http_{exc.status}" if exc.status else "client_error"
    except ConnectorError as exc:
        state.status, state.error_code = "unavailable", exc.code
    except Exception:
        logger.exception("automation_collection_failed", extra={"instance": str(instance.id)})
        state.status, state.error_code = "failed", "internal_error"
    state.save()
    return state.status


def collect_script_values(run: Any, adapter: Any, budget: int) -> int:
    """SCR-01: per device of this run's generation, the latest successful run of each enabled collector.
    Oldest values first, at most ``budget`` device x collector pairs per sync. Returns the number of calls made."""
    from apps.integrations.http import ConnectorError, VendorClientError, VendorUnavailable
    from apps.inventory.models import AssetObservation

    collectors = list(ScriptCollector.objects.filter(integration_instance=run.integration_instance, enabled=True))
    if not collectors or budget <= 0:
        return 0
    assets = [o.asset for o in AssetObservation.objects.filter(generation=run.generation).select_related("asset")]
    last = {
        (str(v.collector_id), str(v.asset_id)): v.fetched_at
        for v in DeviceScriptValue.objects.filter(collector__in=collectors, customer=run.customer)
    }
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    pairs = sorted(
        ((c, a) for c in collectors for a in assets),
        key=lambda pair: last.get((str(pair[0].id), str(pair[1].id)), epoch),
    )[:budget]
    calls, unavailable = 0, 0
    for collector, asset in pairs:
        values: dict[str, Any] = {}
        state, execution_id, executed_at = DeviceScriptValue.State.NEVER_RUN, "", None
        try:
            latest = adapter.latest_script_run(collector.script_external_id, asset.external_id)
            calls += 1
            if latest and latest.get("Id"):
                body = adapter.get_script_run(collector.script_external_id, asset.external_id, str(latest["Id"]))
                calls += 1
                data = (body or {}).get("Data") or {}
                allowed = set(collector.allowed_variables)
                for var in data.get("VariableOutputs") or []:
                    if isinstance(var, dict) and var.get("Name") in allowed:
                        values[str(var["Name"])] = {
                            "value": _text(var.get("Value"), 500),
                            "type": _text(var.get("DataType"), 16),
                        }
                state, execution_id = DeviceScriptValue.State.COLLECTED, _text(latest["Id"], 64)
                executed_at = _dt(data.get("Endtime")) or _dt(latest.get("StartTime"))
            unavailable = 0
        except VendorUnavailable:
            state = DeviceScriptValue.State.FAILED
            unavailable += 1
        except (VendorClientError, ConnectorError, ValueError, AttributeError):
            state = DeviceScriptValue.State.FAILED
        DeviceScriptValue.objects.update_or_create(
            collector=collector,
            asset=asset,
            defaults={
                "customer": run.customer,
                "state": state,
                "execution_id": execution_id,
                "executed_at": executed_at,
                "values": values,
                "fetched_at": timezone.now(),
            },
        )
        if unavailable >= 3:
            break  # VSA X is struggling; the remaining devices are read on the next sync
    return calls
