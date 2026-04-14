# Migration: Self-Learning Intelligence Layer models.
# These tables are NEW and must actually be created.

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sources', '0008_early_warning_state_only'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdaptiveThreshold',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('param_name', models.CharField(help_text="Unique key, e.g. 'anomaly.volume_spike_threshold'.", max_length=120, unique=True)),
                ('param_type', models.CharField(choices=[('anomaly_threshold', 'Anomaly Threshold'), ('predictive_weight', 'Predictive Weight'), ('source_trust_weight', 'Source Trust Weight'), ('escalation_sensitivity', 'Escalation Sensitivity')], max_length=32)),
                ('current_value', models.DecimalField(decimal_places=4, max_digits=8)),
                ('previous_value', models.DecimalField(blank=True, decimal_places=4, max_digits=8, null=True)),
                ('default_value', models.DecimalField(decimal_places=4, max_digits=8)),
                ('min_value', models.DecimalField(decimal_places=4, default=Decimal('0.0'), max_digits=8)),
                ('max_value', models.DecimalField(decimal_places=4, default=Decimal('10.0'), max_digits=8)),
                ('adjustment_reason', models.TextField(blank=True, default='')),
                ('evidence', models.JSONField(blank=True, default=dict)),
                ('version', models.PositiveIntegerField(default=1)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['param_name'],
                'indexes': [models.Index(fields=['param_type'], name='sources_ada_param_t_83bbf1_idx'), models.Index(fields=['param_name'], name='sources_ada_param_n_449467_idx')],
            },
        ),
        migrations.CreateModel(
            name='OutcomeRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('target_type', models.CharField(choices=[('alert', 'Alert'), ('event', 'Event'), ('prediction', 'Prediction'), ('case', 'Case'), ('anomaly', 'Anomaly')], max_length=16)),
                ('target_id', models.PositiveIntegerField()),
                ('expected_outcome', models.TextField(blank=True, default='')),
                ('actual_outcome', models.TextField(blank=True, default='')),
                ('accuracy_status', models.CharField(choices=[('pending', 'Pending'), ('accurate', 'Accurate'), ('partially_accurate', 'Partially Accurate'), ('inaccurate', 'Inaccurate'), ('indeterminate', 'Indeterminate')], default='pending', max_length=24)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolution_notes', models.TextField(blank=True, default='')),
                ('prediction_snapshot', models.JSONField(blank=True, default=dict, help_text='Original prediction scores at prediction time.')),
                ('outcome_snapshot', models.JSONField(blank=True, default=dict, help_text='Metric values at resolution time.')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['target_type', 'target_id'], name='sources_out_target__1adede_idx'), models.Index(fields=['accuracy_status'], name='sources_out_accurac_f583a6_idx'), models.Index(fields=['resolved_at'], name='sources_out_resolve_c37349_idx')],
                'constraints': [models.UniqueConstraint(fields=('target_type', 'target_id'), name='unique_outcome_per_target')],
            },
        ),
        migrations.CreateModel(
            name='AnalystFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('target_type', models.CharField(choices=[('alert', 'Alert'), ('event', 'Event'), ('prediction', 'Prediction'), ('case', 'Case'), ('anomaly', 'Anomaly')], max_length=16)),
                ('target_id', models.PositiveIntegerField()),
                ('feedback_type', models.CharField(choices=[('confirmed', 'Confirmed'), ('false_positive', 'False Positive'), ('misleading', 'Misleading'), ('useful', 'Useful'), ('escalated_correctly', 'Escalated Correctly'), ('dismissed_correctly', 'Dismissed Correctly')], max_length=24)),
                ('comment', models.TextField(blank=True, default='')),
                ('confidence', models.DecimalField(decimal_places=2, default=Decimal('1.00'), help_text='Analyst confidence in the feedback (0-1).', max_digits=4)),
                ('context_snapshot', models.JSONField(blank=True, default=dict, help_text='Snapshot of scores/metrics at feedback time for audit.')),
                ('analyst', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='analyst_feedbacks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['target_type', 'target_id'], name='sources_ana_target__99aeaa_idx'), models.Index(fields=['feedback_type'], name='sources_ana_feedbac_22a5f0_idx'), models.Index(fields=['created_at'], name='sources_ana_created_8bdb49_idx')],
            },
        ),
        migrations.CreateModel(
            name='LearningRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('record_type', models.CharField(help_text='E.g. prediction_evaluation, anomaly_evaluation, feedback_record.', max_length=32)),
                ('features', models.JSONField(blank=True, default=dict, help_text='Event features: type, source_count, importance, etc.')),
                ('prediction_scores', models.JSONField(blank=True, default=dict, help_text='Prediction scores at evaluation time.')),
                ('anomaly_metrics', models.JSONField(blank=True, default=dict, help_text='Anomaly detection metrics at evaluation time.')),
                ('feedback_summary', models.JSONField(blank=True, default=dict, help_text='Analyst feedback aggregation.')),
                ('outcome', models.JSONField(blank=True, default=dict, help_text='Final outcome data from OutcomeRecord.')),
                ('accuracy_label', models.CharField(blank=True, default='', help_text='Ground truth label: accurate, inaccurate, etc.', max_length=24)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='learning_records', to='sources.event')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['record_type'], name='sources_lea_record__389f6d_idx'), models.Index(fields=['accuracy_label'], name='sources_lea_accurac_7d3a0b_idx'), models.Index(fields=['created_at'], name='sources_lea_created_eb4f45_idx')],
            },
        ),
        migrations.CreateModel(
            name='SourceReputationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('previous_trust', models.DecimalField(decimal_places=2, max_digits=4)),
                ('new_trust', models.DecimalField(decimal_places=2, max_digits=4)),
                ('change_delta', models.DecimalField(decimal_places=3, max_digits=5)),
                ('reason', models.CharField(choices=[('false_positive', 'False Positive Contribution'), ('useful_signal', 'Useful Signal Contribution'), ('consistency', 'Consistency Check'), ('historical_precision', 'Historical Precision'), ('manual_override', 'Manual Override'), ('periodic_recalc', 'Periodic Recalculation')], max_length=32)),
                ('evidence', models.JSONField(blank=True, default=dict, help_text='Data supporting the trust change.')),
                ('is_rollback', models.BooleanField(default=False)),
                ('rolled_back_at', models.DateTimeField(blank=True, null=True)),
                ('rolled_back_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reputation_logs', to='sources.source')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['source', '-created_at'], name='sources_sou_source__cd80fe_idx'), models.Index(fields=['reason'], name='sources_sou_reason_512345_idx')],
            },
        ),
    ]
