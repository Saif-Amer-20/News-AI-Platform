# Generated manually — adds language fields to Article and Entity

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sources", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="language",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="ISO 639-1 language code detected on ingest (e.g. 'ar', 'en').",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="entity",
            name="language",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Language of the entity name.",
                max_length=8,
            ),
        ),
    ]
