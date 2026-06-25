"""
Idempotently seeds Stream/Milestone/StreamMilestone reference data,
placeholder ConfigParameter rows, and the Holiday calendar.

Safe to re-run: uses update_or_create / get_or_create throughout.

IMPORTANT: ConfigParameter values are PLACEHOLDERS inherited from the prototype
(Code.gs FEE_RULES / index.html demo benchmarks). They are NOT confirmed UPDR-2026
figures — see Part 18 of the build plan before treating any fee output as final.

Officer accounts are NOT seeded here (that was the prototype's hardcoded-credentials
defect). Create officer accounts interactively via:
    python manage.py create_officer
"""

import calendar
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Idempotently seeds reference data (streams, milestones, config, holidays)."

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_streams_and_milestones()
        self._seed_placeholder_config()
        self._seed_holidays(2026)
        self.stdout.write(self.style.SUCCESS("Reference data seeded successfully."))

    def _seed_streams_and_milestones(self):
        from apps.applications.models import Milestone, Stream, StreamMilestone
        from apps.identity.models import OfficerProfile

        STREAMS = [
            ("new_building", "New Building (Full Lifecycle)"),
            ("addition", "Addition / Alteration"),
            ("layout", "Layout / Sub-division / Amalgamation"),
            ("reerection", "Re-erection"),
            ("temporary", "Temporary Permission"),
            ("special", "Special Buildings (High-Rise / Hazardous)"),
            ("regularise", "Regularisation of Unauthorised Construction"),
        ]
        for code, name in STREAMS:
            Stream.objects.update_or_create(code=code, defaults={"name": name})
        self.stdout.write(f"  Seeded {len(STREAMS)} streams.")

        # SLA working days are reasonable defaults; replace with confirmed UPDR-2026
        # values via a new ConfigParameter row when official figures are available.
        MILESTONES = [
            ("DEMO", "Demolition & Site Clearance", 15),
            ("S1", "Ingestion & Verification", 21),
            ("S2", "Design Sanction & Foundation Clearance", 30),
            ("S3", "Sub-Structure Validation", 21),
            ("S4", "Superstructure — 80% BUA", 21),
            ("S5", "Superstructure — Remaining 20% BUA", 21),
            ("S6", "Service Infrastructure Integration", 21),
            # "OC" replaces the build-plan doc's "S7" — the hardcoded
            # OC_NEVER_DEEMED_CODES guard in run_sla_sweep.py checks this code.
            ("OC", "Occupancy Certificate / Statutory Finalisation", 30),
        ]
        for code, name, sla_days in MILESTONES:
            Milestone.objects.update_or_create(
                code=code,
                defaults={"name": name, "default_sla_working_days": sla_days},
            )
        self.stdout.write(f"  Seeded {len(MILESTONES)} milestones.")

        OFFICER_ROLES = {
            "DEMO": OfficerProfile.ROLE_ESTATE_OFFICER,
            "S1": OfficerProfile.ROLE_JUNIOR_PLANNER,
            "S2": OfficerProfile.ROLE_DEPUTY_PLANNER,
            "S3": OfficerProfile.ROLE_JUNIOR_PLANNER,
            "S4": OfficerProfile.ROLE_JUNIOR_PLANNER,
            "S5": OfficerProfile.ROLE_DEPUTY_PLANNER,
            "S6": OfficerProfile.ROLE_DEPUTY_PLANNER,
            "OC": OfficerProfile.ROLE_CHAIRMAN,
        }

        # PRD Appendix §17.2 stream-to-milestone-sequence table.
        # OC (Occupancy Certificate) is the final stage in every stream.
        # deemed_clearance_eligible=False on every OC row enforces AC-18 guard #1.
        SEQUENCES = {
            "new_building": ["S1", "S2", "S3", "S4", "S5", "S6", "OC"],
            "addition": ["S1", "S2", "S3", "S6", "OC"],
            "layout": ["S1", "S2", "S3", "S6", "OC"],
            "reerection": ["DEMO", "S1", "S2", "S3", "S4", "S5", "S6", "OC"],
            "temporary": ["S1", "S2", "S6", "OC"],
            "special": ["S1", "S2", "S3", "S4", "S5", "S6", "OC"],
            "regularise": ["S1", "S2", "S3", "S4", "S6", "OC"],
        }
        sm_count = 0
        for stream_code, milestone_codes in SEQUENCES.items():
            stream = Stream.objects.get(code=stream_code)
            for sequence, m_code in enumerate(milestone_codes, start=1):
                milestone = Milestone.objects.get(code=m_code)
                StreamMilestone.objects.update_or_create(
                    stream=stream,
                    milestone=milestone,
                    defaults={
                        "sequence": sequence,
                        # AC-18 guard #1: OC is NEVER auto-cleared by the SLA sweep.
                        # The run_sla_sweep command has a matching hardcoded guard as
                        # a second independent layer (AC-18 belt-and-suspenders).
                        "deemed_clearance_eligible": (m_code != "OC"),
                        "required_officer_role": OFFICER_ROLES.get(m_code, ""),
                    },
                )
                sm_count += 1
        self.stdout.write(f"  Seeded {sm_count} stream-milestone rows.")

    def _seed_placeholder_config(self):
        from django.contrib.auth import get_user_model

        from apps.fees.models import ConfigParameter

        user_model = get_user_model()
        superuser = user_model.objects.filter(is_superuser=True).first()
        if superuser is None:
            self.stdout.write(
                self.style.WARNING(
                    "  No superuser found — skipping ConfigParameter seed. "
                    "Create a superuser first, then re-run this command."
                )
            )
            return

        # PLACEHOLDER VALUES — prototype constants, NOT confirmed UPDR-2026 figures.
        PLACEHOLDER_VALUES = {
            "scrutiny_fee_per_sqm": "50.00",
            "security_deposit_per_sqm": "10.00",
            "debris_deposit_per_sqm": "20.00",
            "premium_coefficient.additional_fsi": "1.10",
            "premium_coefficient.open_space_shortfall": "0.25",
            "premium_coefficient.parking_waiver": "0.40",
            "benchmark.additional_fsi": "1.50",
            "benchmark.open_space_shortfall": "30.0",
        }
        today = datetime.date.today()
        seeded = 0
        for key, value in PLACEHOLDER_VALUES.items():
            _, created = ConfigParameter.objects.get_or_create(
                key=key,
                effective_from=today,
                defaults={
                    "value": value,
                    "notes": "PLACEHOLDER — prototype value, NOT confirmed UPDR-2026 figure.",
                    "created_by": superuser,
                },
            )
            if created:
                seeded += 1
        self.stdout.write(f"  Seeded {seeded} new ConfigParameter rows.")
        self.stdout.write(
            self.style.WARNING(
                "  WARNING: ConfigParameter values are PLACEHOLDERS from the prototype. "
                "NOT confirmed UPDR-2026 figures. See Part 18 of the build plan."
            )
        )

    def _seed_holidays(self, year: int):
        from apps.compliance.models import Holiday

        # National / gazetted holidays
        NATIONAL_HOLIDAYS = [
            (datetime.date(year, 1, 26), "Republic Day"),
            (datetime.date(year, 8, 15), "Independence Day"),
            (datetime.date(year, 10, 2), "Gandhi Jayanti"),
        ]
        nat_count = 0
        for date, description in NATIONAL_HOLIDAYS:
            _, created = Holiday.objects.get_or_create(
                date=date,
                defaults={"description": description, "is_national": True},
            )
            if created:
                nat_count += 1
        self.stdout.write(f"  Seeded {nat_count} national holiday rows for {year}.")

        # 2nd and 4th Saturdays (Bank Holiday rule).
        # compute_due_at skips any date present in the Holiday table, so these
        # rows are the sole implementation of the 2nd/4th Saturday rule.
        sat_count = 0
        for month in range(1, 13):
            saturdays = [
                datetime.date(year, month, day)
                for day in range(1, calendar.monthrange(year, month)[1] + 1)
                if datetime.date(year, month, day).weekday() == 5
            ]
            for idx, sat in enumerate(saturdays, start=1):
                if idx in (2, 4):
                    label = "2nd" if idx == 2 else "4th"
                    _, created = Holiday.objects.get_or_create(
                        date=sat,
                        defaults={
                            "description": f"{label} Saturday (Bank Holiday)",
                            "is_national": False,
                        },
                    )
                    if created:
                        sat_count += 1
        self.stdout.write(f"  Seeded {sat_count} 2nd/4th Saturday rows for {year}.")
