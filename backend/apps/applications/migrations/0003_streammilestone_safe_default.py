"""
Migration: flip StreamMilestone.deemed_clearance_eligible default from True → False.

Rationale: the previous default=True meant any row created without an explicit
value (seed script, data migration, admin edit under deadline) would silently
inherit the dangerous state (eligible for auto-clearance). Default=False makes
the safe state the fallback; operators must opt in explicitly for each milestone
that should support deemed clearance.

Existing rows are unaffected — they already have a stored boolean value and
Django BooleanField defaults are Python-only (no DB DEFAULT clause is added).
Only new rows created after this migration will receive False instead of True.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="streammilestone",
            name="deemed_clearance_eligible",
            field=models.BooleanField(default=False),
        ),
    ]
