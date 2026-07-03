import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_initial"),
        ("applications", "0004_applicationparty_account_of_record_constraint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── DocumentSlot: drop old unique_together before removing fields ────────
        migrations.AlterUniqueTogether(
            name="documentslot",
            unique_together=set(),
        ),
        # Remove old DocumentSlot fields not in spec
        migrations.RemoveField(model_name="documentslot", name="stream"),
        migrations.RemoveField(model_name="documentslot", name="code"),
        migrations.RemoveField(model_name="documentslot", name="name"),
        migrations.RemoveField(model_name="documentslot", name="description"),
        migrations.RemoveField(model_name="documentslot", name="accepted_mime_types"),
        migrations.RemoveField(model_name="documentslot", name="max_size_mb"),
        migrations.RemoveField(model_name="documentslot", name="is_active"),
        # Add new DocumentSlot fields
        migrations.AddField(
            model_name="documentslot",
            name="document_type",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="documentslot",
            name="applies_when",
            field=models.CharField(blank=True, max_length=64),
        ),
        # New unique constraint on (stream_milestone, document_type)
        migrations.AddConstraint(
            model_name="documentslot",
            constraint=models.UniqueConstraint(
                fields=["stream_milestone", "document_type"], name="uniq_doc_slot"
            ),
        ),
        # ── DocumentUpload: drop old indexes before renaming/removing fields ─────
        migrations.RemoveIndex(
            model_name="documentupload",
            name="documents_u_applica_bb2078_idx",
        ),
        migrations.RemoveIndex(
            model_name="documentupload",
            name="documents_u_status_b4321c_idx",
        ),
        # Remove fields not in spec
        migrations.RemoveField(model_name="documentupload", name="status"),
        migrations.RemoveField(model_name="documentupload", name="reviewer_remarks"),
        migrations.RemoveField(model_name="documentupload", name="reviewed_at"),
        # Rename slot → document_slot
        migrations.RenameField(
            model_name="documentupload",
            old_name="slot",
            new_name="document_slot",
        ),
        # Make document_slot nullable (ad-hoc uploads have no slot)
        migrations.AlterField(
            model_name="documentupload",
            name="document_slot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="documents.documentslot",
            ),
        ),
        # Rename mime_type → content_type
        migrations.RenameField(
            model_name="documentupload",
            old_name="mime_type",
            new_name="content_type",
        ),
        # Change content_type max_length from 100 → 128
        migrations.AlterField(
            model_name="documentupload",
            name="content_type",
            field=models.CharField(max_length=128),
        ),
        # Change size_bytes from PositiveIntegerField to BigIntegerField
        migrations.AlterField(
            model_name="documentupload",
            name="size_bytes",
            field=models.BigIntegerField(),
        ),
        # Fix application related_name
        migrations.AlterField(
            model_name="documentupload",
            name="application",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="documents",
                to="applications.application",
            ),
        ),
        # Fix milestone_instance related_name
        migrations.AlterField(
            model_name="documentupload",
            name="milestone_instance",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="applications.milestoneinstance",
            ),
        ),
        # Fix uploaded_by related_name
        migrations.AlterField(
            model_name="documentupload",
            name="uploaded_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Add new fields
        migrations.AddField(
            model_name="documentupload",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="documentupload",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        # New index on (application, document_slot, version)
        migrations.AddIndex(
            model_name="documentupload",
            index=models.Index(
                fields=["application", "document_slot", "version"],
                name="documents_u_app_slot_ver_idx",
            ),
        ),
        # CheckConstraint: size_bytes > 0
        migrations.AddConstraint(
            model_name="documentupload",
            constraint=models.CheckConstraint(  # type: ignore[call-arg]
                condition=models.Q(size_bytes__gt=0), name="document_size_positive"
            ),
        ),
    ]
