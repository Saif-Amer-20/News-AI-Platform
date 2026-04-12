from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0002_add_article_translation"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticleAISummary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("summary", models.TextField(blank=True)),
                ("predictions", models.TextField(blank=True)),
                ("model_used", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("article", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ai_summary", to="sources.article")),
            ],
            options={
                "indexes": [models.Index(fields=["status"], name="sources_arti_status_ai_idx")],
            },
        ),
    ]
