# Hand-crafted migration: Early-Warning models already present in DB.
# Uses SeparateDatabaseAndState so Django learns about them without
# attempting to CREATE tables that already exist.

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


# ── The five early-warning CreateModel ops (state-only) ──────
_EW_STATE_OPS = [
    migrations.CreateModel(
        name='AnomalyDetection',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('anomaly_type', models.CharField(choices=[('volume_spike', 'Volume Spike'), ('source_diversity', 'Source Diversity Change'), ('entity_surge', 'Entity Mention Surge'), ('location_surge', 'Location Activity Surge'), ('narrative_shift', 'Narrative Shift')], max_length=24)),
            ('severity', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')], default='medium', max_length=12)),
            ('status', models.CharField(choices=[('active', 'Active'), ('acknowledged', 'Acknowledged'), ('dismissed', 'Dismissed'), ('expired', 'Expired')], default='active', max_length=16)),
            ('title', models.CharField(max_length=500)),
            ('description', models.TextField(blank=True)),
            ('metric_name', models.CharField(blank=True, max_length=120)),
            ('baseline_value', models.FloatField(default=0)),
            ('current_value', models.FloatField(default=0)),
            ('deviation_factor', models.FloatField(default=0, help_text='How many standard deviations above baseline.')),
            ('confidence', models.DecimalField(decimal_places=2, default=Decimal('0.50'), max_digits=4)),
            ('location_country', models.CharField(blank=True, max_length=4)),
            ('location_name', models.CharField(blank=True, max_length=255)),
            ('evidence', models.JSONField(blank=True, default=dict, help_text='Supporting data points, time-series, related article IDs.')),
            ('related_event_ids', models.JSONField(blank=True, default=list)),
            ('related_entity_ids', models.JSONField(blank=True, default=list)),
            ('detected_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('expires_at', models.DateTimeField(blank=True, null=True)),
            ('entity', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='anomalies', to='sources.entity')),
            ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='anomalies', to='sources.event')),
        ],
        options={
            'ordering': ['-detected_at'],
            'indexes': [models.Index(fields=['anomaly_type', 'severity'], name='sources_ano_anomaly_f9211a_idx'), models.Index(fields=['status'], name='sources_ano_status_fcf18b_idx'), models.Index(fields=['detected_at'], name='sources_ano_detecte_9ea1ae_idx'), models.Index(fields=['location_country'], name='sources_ano_locatio_60f698_idx')],
        },
    ),
    migrations.CreateModel(
        name='GeoRadarZone',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('title', models.CharField(max_length=300)),
            ('description', models.TextField(blank=True)),
            ('center_lat', models.DecimalField(decimal_places=6, max_digits=9)),
            ('center_lon', models.DecimalField(decimal_places=6, max_digits=9)),
            ('radius_km', models.FloatField(default=50, help_text='Radius in km.')),
            ('location_country', models.CharField(blank=True, max_length=4)),
            ('location_name', models.CharField(blank=True, max_length=255)),
            ('event_count', models.PositiveIntegerField(default=0)),
            ('event_concentration', models.FloatField(default=0, help_text='Events per 100km\u00b2.')),
            ('avg_severity', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('anomaly_count', models.PositiveIntegerField(default=0)),
            ('temporal_trend', models.CharField(blank=True, help_text='intensifying | stable | subsiding', max_length=16)),
            ('event_ids', models.JSONField(blank=True, default=list)),
            ('anomaly_ids', models.JSONField(blank=True, default=list)),
            ('status', models.CharField(choices=[('active', 'Active'), ('cooling', 'Cooling Down'), ('expired', 'Expired')], default='active', max_length=12)),
            ('first_detected_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('last_activity_at', models.DateTimeField(blank=True, null=True)),
        ],
        options={
            'ordering': ['-event_concentration'],
            'indexes': [models.Index(fields=['status'], name='sources_geo_status_2a9244_idx'), models.Index(fields=['event_concentration'], name='sources_geo_event_c_88f06a_idx'), models.Index(fields=['location_country'], name='sources_geo_locatio_77ba83_idx')],
        },
    ),
    migrations.CreateModel(
        name='HistoricalPattern',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('pattern_name', models.CharField(blank=True, max_length=300)),
            ('similarity_score', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('matching_dimensions', models.JSONField(blank=True, default=list, help_text='["event_type", "location", "entity_overlap", "source_pattern"]')),
            ('historical_outcome', models.TextField(blank=True, help_text='What happened after the historical event.')),
            ('predicted_trajectory', models.TextField(blank=True, help_text='Projected trajectory based on pattern.')),
            ('predicted_trajectory_ar', models.TextField(blank=True)),
            ('confidence', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='historical_patterns', to='sources.event')),
            ('matched_event', models.ForeignKey(blank=True, help_text='The historical event this pattern is compared against.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matched_as_pattern', to='sources.event')),
        ],
        options={
            'ordering': ['-similarity_score'],
            'indexes': [models.Index(fields=['similarity_score'], name='sources_his_similar_588839_idx')],
        },
    ),
    migrations.CreateModel(
        name='PredictiveScore',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('escalation_probability', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='0-1: Will the situation escalate within 48h?', max_digits=4)),
            ('continuation_probability', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='0-1: Will the event continue developing?', max_digits=4)),
            ('misleading_probability', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='0-1: Probability of misleading / disinformation signal.', max_digits=4)),
            ('monitoring_priority', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='0-1: Composite priority score.', max_digits=4)),
            ('anomaly_factor', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('correlation_factor', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('historical_factor', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('source_diversity_factor', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('velocity_factor', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('reasoning', models.TextField(blank=True)),
            ('reasoning_ar', models.TextField(blank=True)),
            ('risk_trend', models.CharField(blank=True, help_text='rising | stable | declining', max_length=16)),
            ('weak_signals', models.JSONField(blank=True, default=list, help_text='[{"signal": "...", "weight": 0.2, "source": "anomaly|correlation|pattern"}]')),
            ('model_used', models.CharField(blank=True, max_length=64)),
            ('scored_at', models.DateTimeField(blank=True, null=True)),
            ('event', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='predictive_score', to='sources.event')),
        ],
        options={
            'indexes': [models.Index(fields=['monitoring_priority'], name='sources_pre_monitor_0193d8_idx'), models.Index(fields=['escalation_probability'], name='sources_pre_escalat_aab76c_idx')],
        },
    ),
    migrations.CreateModel(
        name='SignalCorrelation',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('correlation_type', models.CharField(choices=[('cross_event', 'Cross-Event'), ('cross_entity', 'Cross-Entity'), ('cross_location', 'Cross-Location'), ('temporal', 'Temporal Proximity'), ('source_pattern', 'Source Pattern')], max_length=20)),
            ('strength', models.CharField(choices=[('weak', 'Weak'), ('moderate', 'Moderate'), ('strong', 'Strong')], default='weak', max_length=12)),
            ('title', models.CharField(max_length=500)),
            ('description', models.TextField(blank=True)),
            ('correlation_score', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4)),
            ('entity_ids', models.JSONField(blank=True, default=list)),
            ('anomaly_ids', models.JSONField(blank=True, default=list)),
            ('reasoning', models.TextField(blank=True, help_text='Explainable reasoning for this correlation.')),
            ('evidence', models.JSONField(blank=True, default=dict)),
            ('supporting_signals', models.JSONField(blank=True, default=list, help_text='[{"signal_type": "...", "detail": "...", "weight": 0.3}]')),
            ('detected_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('event_a', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='correlations_as_a', to='sources.event')),
            ('event_b', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='correlations_as_b', to='sources.event')),
        ],
        options={
            'ordering': ['-correlation_score', '-detected_at'],
            'indexes': [models.Index(fields=['correlation_type'], name='sources_sig_correla_22b8c1_idx'), models.Index(fields=['strength'], name='sources_sig_strengt_ae57b3_idx'), models.Index(fields=['detected_at'], name='sources_sig_detecte_d6982a_idx')],
        },
    ),
]


class Migration(migrations.Migration):
    """Register early-warning models that already exist in the database."""

    dependencies = [
        ('sources', '0007_intel_assessment'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=_EW_STATE_OPS,
            database_operations=[],   # tables already exist
        ),
    ]
