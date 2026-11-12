from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from . import scope
from .roles import Cap


class HasGlobalCapability(BasePermission):
    """Requires a global capability, e.g. ``system.manage``. Configure via ``view.global_capability``."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Any, view: Any) -> bool:
        capability = getattr(view, "global_capability", Cap.SYSTEM_MANAGE)
        return scope.has_global_capability(request.user, capability)


class IsSystemAdmin(HasGlobalCapability):
    pass
