"""One-time local bootstrap super administrator (SECURITY.md §2).

* Refuses if any active super administrator already exists (one-time).
* Refuses if LOCAL_LOGIN_ENABLED is false.
* Password from BOOTSTRAP_ADMIN_PASSWORD / BOOTSTRAP_ADMIN_PASSWORD_FILE or an interactive prompt — never
  a command-line argument (shell history / process list exposure).
"""

from __future__ import annotations

import getpass
from typing import Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.accounts.roles import SUPER_ADMIN
from apps.audit.services import record_event
from config.env import env_str


class Command(BaseCommand):
    help = "Create the one-time local bootstrap super administrator."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--display-name", default="Bootstrap administrator")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.LOCAL_LOGIN_ENABLED:
            raise CommandError("LOCAL_LOGIN_ENABLED is false; bootstrap accounts cannot be used.")
        if User.objects.filter(global_role__key=SUPER_ADMIN, is_active=True).exists():
            raise CommandError("A super administrator already exists. Bootstrap is one-time only.")
        email = options["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("A user with that email already exists.")

        password = env_str("BOOTSTRAP_ADMIN_PASSWORD", "")
        if not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Confirm: "):
                raise CommandError("Passwords do not match.")
        try:
            validate_password(password, user=User(email=email))
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                display_name=options["display_name"],
                auth_source=User.AuthSource.LOCAL,
                global_role=Role.objects.get(key=SUPER_ADMIN),
            )
            record_event(
                action="auth.bootstrap_admin_created",
                outcome="success",
                actor_label="system:bootstrap_admin",
                target_type="user",
                target_id=str(user.id),
                metadata={"email": email},
            )
        self.stdout.write(self.style.SUCCESS(f"Bootstrap super administrator {email} created."))
        self.stdout.write("Disable LOCAL_LOGIN_ENABLED once Entra ID SSO has been verified (P5-01).")
