from __future__ import annotations

import re
from typing import Any

from rest_framework import serializers

from apps.accounts import scope
from apps.accounts.models import Role, User
from apps.accounts.roles import MEMBERSHIP_ROLES
from apps.integrations.models import IntegrationInstance

from .models import Customer, CustomerMembership, CustomerSourceMapping

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


class CustomerSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=32)
    my_capabilities = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "code",
            "name",
            "status",
            "data_region",
            "restricted_data",
            "notes",
            "created_at",
            "updated_at",
            "my_capabilities",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "my_capabilities"]

    def get_my_capabilities(self, obj: Customer) -> list[str]:
        request = self.context.get("request")
        return sorted(scope.capabilities_for_customer(request.user, obj.id)) if request else []

    def validate_code(self, value: str) -> str:
        value = value.strip().upper()
        if not CODE_RE.match(value):
            raise serializers.ValidationError("Use 2-32 upper-case letters, digits, - or _.")
        qs = Customer.objects.filter(code=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A customer with this code already exists.")
        return value


class UserRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "is_active"]


class MembershipSerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    email = serializers.EmailField(write_only=True, required=False)
    role = serializers.SlugRelatedField(slug_field="key", queryset=Role.objects.filter(key__in=MEMBERSHIP_ROLES))
    granted_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = CustomerMembership
        fields = [
            "id",
            "user",
            "email",
            "role",
            "can_export",
            "is_active",
            "granted_by",
            "granted_at",
            "revoked_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "is_active", "granted_by", "granted_at", "revoked_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None:
            email = (attrs.pop("email", "") or "").strip().lower()
            if not email:
                raise serializers.ValidationError({"email": "Required."})
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user is None:
                raise serializers.ValidationError({"email": "No active user with this email."})
            attrs["user"] = user
        else:
            attrs.pop("email", None)
        return attrs


class IntegrationRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationInstance
        fields = ["id", "name", "provider", "is_fixture"]


class SourceMappingSerializer(serializers.ModelSerializer):
    integration_instance = serializers.PrimaryKeyRelatedField(queryset=IntegrationInstance.objects.all())
    integration = IntegrationRefSerializer(source="integration_instance", read_only=True)
    customer = serializers.SerializerMethodField()
    proposed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = CustomerSourceMapping
        fields = [
            "id",
            "customer",
            "integration_instance",
            "integration",
            "external_org_id",
            "external_org_name",
            "mapping_status",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "customer",
            "integration",
            "mapping_status",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
            "updated_at",
        ]

    def get_customer(self, obj: CustomerSourceMapping) -> dict[str, str]:
        return {"id": str(obj.customer_id), "code": obj.customer.code, "name": obj.customer.name}

    def validate_external_org_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Required.")
        return value


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
