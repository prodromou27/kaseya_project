from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from . import roles


class Role(models.Model):
    """Seeded role catalogue. Capabilities come from ``apps.accounts.roles`` (code), not this table."""

    key = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_global = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.key

    @property
    def capabilities(self) -> frozenset[str]:
        return roles.capabilities_for_role(self.key)


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def normalize_email(self, email: str | None) -> str:  # type: ignore[override]
        return (email or "").strip().lower()

    def create_user(self, email: str, password: str | None = None, **extra: object) -> User:
        if not email:
            raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(email__iexact=(username or "").strip())


class User(AbstractBaseUser):
    class AuthSource(models.TextChoices):
        LOCAL = "local", "Local (bootstrap/dev only)"
        OIDC = "oidc", "OIDC (Microsoft Entra ID)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    auth_source = models.CharField(max_length=10, choices=AuthSource.choices, default=AuthSource.LOCAL)
    oidc_issuer = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    oidc_subject = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    global_role = models.ForeignKey(
        Role,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="global_users",
        limit_choices_to={"is_global": True},
    )
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
            models.UniqueConstraint(
                fields=["oidc_issuer", "oidc_subject"],
                name="accounts_user_oidc_identity_unique",
                condition=models.Q(oidc_subject__isnull=False),
            ),
            models.CheckConstraint(
                condition=models.Q(auth_source="local") | models.Q(oidc_subject__isnull=False),
                name="accounts_user_oidc_requires_subject",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    def save(self, *args: object, **kwargs: object) -> None:
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def is_super_admin(self) -> bool:
        return bool(self.is_active and self.global_role_id and self.global_role.key == roles.SUPER_ADMIN)

    @property
    def global_capabilities(self) -> frozenset[str]:
        if not self.is_active or not self.global_role_id:
            return frozenset()
        return roles.capabilities_for_role(self.global_role.key)
