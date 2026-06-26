import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("compliance", "0003_audit_event_immutable_trigger"),
        ("documents", "0004_documentslot_stream_milestone_non_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="conditionalclearance",
            name="clearance_type",
            field=models.CharField(
                choices=[
                    ("railway", "Railway Authority NOC"),
                    ("crz", "CRZ / MCZMA Coastal Clearance"),
                    ("heritage_mhcc", "MHCC Heritage Clearance"),
                    ("aviation_aai", "AAI / Aviation Clearance"),
                    ("pollution_mpcb", "MPCB Pollution Control Clearance"),
                ],
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name="conditionalclearance",
            name="clearance_doc",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clearance_evidence",
                to="documents.documentupload",
            ),
        ),
    ]
