import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0004_applicationparty_account_of_record_constraint"),
        ("documents", "0003_rebuild_document_models"),
    ]

    operations = [
        # stream_milestone was nullable in the original scaffold; make it required
        # so the DB enforces that every DocumentSlot references a valid
        # (stream, milestone) combination via the StreamMilestone through-table.
        # Safe to apply on an empty table (no data migrations needed).
        migrations.AlterField(
            model_name="documentslot",
            name="stream_milestone",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_slots",
                to="applications.streammilestone",
            ),
        ),
    ]
