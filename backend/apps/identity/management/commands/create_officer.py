"""
Interactive command to create an officer account.
No credentials are committed to source code; everything is prompted at runtime.

Usage:
    python manage.py create_officer
"""

import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.identity.models import OfficerProfile

User = get_user_model()

ROLE_MAP = {
    "1": OfficerProfile.ROLE_ESTATE_OFFICER,
    "2": OfficerProfile.ROLE_JUNIOR_PLANNER,
    "3": OfficerProfile.ROLE_DEPUTY_PLANNER,
    "4": OfficerProfile.ROLE_CHAIRMAN,
}


class Command(BaseCommand):
    help = "Create an officer account interactively (no credentials in source code)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Create Officer Account"))

        email = input("Email: ").strip()
        username = input("Username: ").strip()
        first_name = input("First name: ").strip()
        last_name = input("Last name: ").strip()

        if not email or not username:
            raise CommandError("Email and username are required.")

        if User.objects.filter(username=username).exists():
            raise CommandError(f"Username '{username}' is already taken.")

        if User.objects.filter(email=email).exists():
            raise CommandError(f"Email '{email}' is already registered.")

        password = getpass.getpass("Password: ")
        password2 = getpass.getpass("Confirm password: ")
        if password != password2:
            raise CommandError("Passwords do not match.")

        self.stdout.write("\nSelect role:")
        for k, v in ROLE_MAP.items():
            self.stdout.write(f"  {k}: {v}")
        role_choice = input("Role [1-4]: ").strip()
        if role_choice not in ROLE_MAP:
            raise CommandError("Invalid role selection.")
        role = ROLE_MAP[role_choice]

        zone = input("Zone (optional, press Enter to skip): ").strip()

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            user_type=User.USER_TYPE_OFFICER,
        )
        OfficerProfile.objects.create(user=user, role=role, zone=zone)

        self.stdout.write(
            self.style.SUCCESS(f"Officer '{username}' ({role}) created successfully.")
        )
