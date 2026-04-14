from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0005_articleaisummary_predictions_ar_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventIntelAssessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                # Diffusion
                ("coverage_count", models.PositiveIntegerField(default=0, help_text="Total articles covering this event.")),
                ("distinct_source_count", models.PositiveIntegerField(default=0, help_text="Number of distinct sources.")),
                ("first_seen", models.DateTimeField(blank=True, null=True)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("source_list", models.JSONField(blank=True, default=list, help_text='[{"source_id":1,"name":"...","trust":0.7,"country":"US","articles":3,"first":"ISO","last":"ISO"}]')),
                ("article_links", models.JSONField(blank=True, default=list, help_text='[{"id":1,"title":"...","url":"...","source":"...","published_at":"ISO"}]')),
                ("publication_timeline", models.JSONField(blank=True, default=list, help_text='[{"ts":"ISO","source":"...","article_id":1,"title":"..."}]')),
                # Cross-source comparison
                ("claims", models.JSONField(blank=True, default=list, help_text='[{"claim":"...","sources":["src1"],"status":"agreed|contradicted|unique"}]')),
                ("agreements", models.JSONField(blank=True, default=list)),
                ("contradictions", models.JSONField(blank=True, default=list)),
                ("missing_details", models.JSONField(blank=True, default=list)),
                ("late_emerging_claims", models.JSONField(blank=True, default=list)),
                # AI assessment
                ("summary", models.TextField(blank=True, help_text="What happened.")),
                ("source_agreement_summary", models.TextField(blank=True)),
                ("contradiction_summary", models.TextField(blank=True)),
                ("dominant_narrative", models.TextField(blank=True)),
                ("uncertain_elements", models.TextField(blank=True)),
                ("analyst_reasoning", models.TextField(blank=True)),
                # Arabic
                ("summary_ar", models.TextField(blank=True)),
                ("source_agreement_summary_ar", models.TextField(blank=True)),
                ("contradiction_summary_ar", models.TextField(blank=True)),
                ("dominant_narrative_ar", models.TextField(blank=True)),
                ("uncertain_elements_ar", models.TextField(blank=True)),
                ("analyst_reasoning_ar", models.TextField(blank=True)),
                # Credibility
                ("credibility_score", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="0-1 composite credibility.", max_digits=4)),
                ("confidence_score", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="0-1 how confident we are in the credibility score.", max_digits=4)),
                ("verification_status", models.CharField(choices=[("verified", "Verified"), ("likely_true", "Likely True"), ("mixed", "Mixed / Conflicting"), ("unverified", "Unverified"), ("likely_misleading", "Likely Misleading")], default="unverified", max_length=20)),
                ("credibility_factors", models.JSONField(blank=True, default=dict, help_text="Breakdown of scoring factors.")),
                # Predictions
                ("escalation_probability", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=4)),
                ("continuation_probability", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=4)),
                ("hidden_link_probability", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=4)),
                ("monitoring_recommendation", models.TextField(blank=True)),
                ("forecast_signals", models.JSONField(blank=True, default=dict, help_text="Detailed forecast signals from LLM.")),
                # Meta
                ("model_used", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                # FK
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="intel_assessment", to="sources.event")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status"], name="sources_eve_status_intel_idx"),
                    models.Index(fields=["verification_status"], name="sources_eve_verif_idx"),
                    models.Index(fields=["credibility_score"], name="sources_eve_cred_idx"),
                ],
            },
        ),
    ]
