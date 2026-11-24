"""One authorization (product owner, 2026-11-24).

When ``REQUIRE_SECOND_APPROVER`` is off (the default), a change made by someone who is allowed to approve it takes
effect when it is saved: the proposal is recorded and approved in one step, by the same person, and both steps stay in
the audit log. With ``REQUIRE_SECOND_APPROVER=true`` the proposal waits for a different administrator as before.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.utils import timezone


def one_step() -> bool:
    return not getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True)


def approve_on_save(obj: Any, user: Any, audit: Callable[[str, Any], None], prefix: str) -> bool:
    """Approve a just-proposed row (``state``/``reviewed_by``/``reviewed_at``) when one step is allowed."""
    if not one_step() or getattr(obj, "state", None) != "proposed":
        return False
    obj.state, obj.reviewed_by, obj.reviewed_at = "approved", user, timezone.now()
    obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
    audit(f"{prefix}.approved", obj)
    return True
