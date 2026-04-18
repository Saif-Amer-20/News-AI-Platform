from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sources", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ValidationTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tag_type", models.CharField(
                    choices=[
                        ("cluster_correct", "Cluster assignment correct"),
                        ("cluster_wrong", "Cluster assignment wrong"),
                        ("dup_correct", "Duplicate flag correct"),
                        ("dup_wrong", "Duplicate flag wrong — not a duplicate"),
                        ("dup_missed", "Missed duplicate — should be flagged"),
                        ("entity_missing", "Entity missed by extraction"),
                        ("entity_wrong", "Entity extracted incorrectly"),
                        ("geo_correct", "Geo location correct"),
                        ("geo_wrong", "Geo location incorrect"),
                        ("conflict_correct", "Conflict flag correct"),
                        ("conflict_wrong", "Conflict flag incorrect"),
                        ("quality_override", "Quality score override"),
                    ],
                    db_index=True,
                    max_length=32,
                )),
                ("correct_value", models.TextField(blank=True, help_text="The correct value (e.g. correct cluster key, correct entity name).")),
                ("notes", models.TextField(blank=True)),
                ("article", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="validation_tags", to="sources.article")),
                ("tagged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["tag_type"], name="validation_v_tag_typ_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ValidationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(
                    choices=[
                        ("running", "Running"),
                        ("completed", "Completed"),
                        ("failed", "Failed"),
                    ],
                    default="running",
                    max_length=16,
                )),
                ("articles_sampled", models.PositiveIntegerField(default=0)),
                ("report_json", models.JSONField(blank=True, default=dict)),
                ("elapsed_seconds", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=8)),
                ("notes", models.TextField(blank=True)),
                ("triggered_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
