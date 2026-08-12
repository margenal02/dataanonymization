import anonymizer.models
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="AnonymizationTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_name", models.CharField(max_length=255)),
                ("file_type", models.CharField(max_length=12)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("processing", "处理中"), ("completed", "脱敏完成"), ("restored", "已反匿名"), ("failed", "处理失败")], default="processing", max_length=20)),
                ("input_file", models.FileField(upload_to=anonymizer.models.input_upload_path)),
                ("anonymized_file", models.FileField(blank=True, upload_to=anonymizer.models.output_upload_path)),
                ("restore_input_file", models.FileField(blank=True, upload_to=anonymizer.models.restore_input_upload_path)),
                ("restored_file", models.FileField(blank=True, upload_to=anonymizer.models.restored_upload_path)),
                ("mapping_ciphertext", models.TextField(blank=True)),
                ("entity_counts", models.JSONField(blank=True, default=dict)),
                ("options", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "脱敏任务", "verbose_name_plural": "脱敏任务", "ordering": ["-created_at"]},
        )
    ]

