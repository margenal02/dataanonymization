import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0006_trainingdocument_and_annotated_action")]

    operations = [
        migrations.CreateModel(
            name="ModelArtifact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("version", models.CharField(default="1.0.0", max_length=64)),
                ("base_model", models.CharField(default="uie-base", max_length=80)),
                ("storage_folder", models.CharField(max_length=255, unique=True)),
                ("package_sha256", models.CharField(max_length=64)),
                ("package_size", models.PositiveBigIntegerField(default=0)),
                ("file_manifest", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "本地 UIE 模型包",
                "verbose_name_plural": "本地 UIE 模型包",
                "ordering": ["-created_at"],
            },
        ),
    ]
