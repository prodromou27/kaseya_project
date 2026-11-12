from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from . import roles
from .models import Role, User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class RoleSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["key", "name", "description", "is_global", "capabilities"]

    def get_capabilities(self, obj: Role) -> list[str]:
        return sorted(obj.capabilities)


class UserSerializer(serializers.ModelSerializer):
    """Super-admin user management. No password hash, OIDC subject or session data is ever returned."""

    global_role = serializers.SlugRelatedField(
        slug_field="key", queryset=Role.objects.filter(is_global=True), allow_null=True, required=False
    )
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False, max_length=256)
    oidc_linked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "display_name",
            "is_active",
            "auth_source",
            "global_role",
            "oidc_linked",
            "last_login",
            "date_joined",
            "password",
        ]
        read_only_fields = ["id", "auth_source", "oidc_linked", "last_login", "date_joined"]

    def get_oidc_linked(self, obj: User) -> bool:
        return bool(obj.oidc_subject)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        password = attrs.get("password")
        if password:
            validate_password(password, user=User(email=attrs.get("email", "")))
        return attrs

    def create(self, validated: dict[str, Any]) -> User:
        password = validated.pop("password", None)
        return User.objects.create_user(password=password, auth_source=User.AuthSource.LOCAL, **validated)

    def update(self, instance: User, validated: dict[str, Any]) -> User:
        password = validated.pop("password", None)
        for key, value in validated.items():
            setattr(instance, key, value)
        if password:
            if instance.auth_source != User.AuthSource.LOCAL:
                raise serializers.ValidationError({"password": "SSO users cannot have a local password."})
            instance.set_password(password)
        instance.save()
        return instance


def me_payload(user: User, membership_caps: dict[Any, frozenset[str]]) -> dict[str, Any]:
    from apps.customers.models import CustomerMembership

    memberships = (
        CustomerMembership.objects.filter(user=user, is_active=True, customer_id__in=list(membership_caps))
        .select_related("customer", "role")
        .order_by("customer__name")
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "auth_source": user.auth_source,
        "global_role": user.global_role.key if user.global_role_id else None,
        "global_capabilities": sorted(user.global_capabilities),
        "is_super_admin": user.is_super_admin,
        "memberships": [
            {
                "customer": {"id": str(m.customer_id), "code": m.customer.code, "name": m.customer.name},
                "role": m.role.key,
                "capabilities": sorted(membership_caps.get(m.customer_id, frozenset())),
            }
            for m in memberships
        ],
        "roles_reference": {k: sorted(v["capabilities"]) for k, v in roles.ROLE_DEFINITIONS.items()},  # type: ignore[arg-type]
    }
