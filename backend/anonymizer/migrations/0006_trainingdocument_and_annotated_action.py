import uuid
import anonymizer.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0005_add_review_task_status")]

    operations = [
        migrations.AlterField(
            model_name="trainingexample",
            name="action",
            field=models.CharField(
                choices=[
                    ("created", "新增"),
                    ("updated", "修改"),
                    ("deleted", "停用"),
                    ("task_custom", "任务新增"),
                    ("rejected", "人工否决"),
                    ("annotated", "文档标注"),
                ],
                max_length=24,
            ),
        ),
        migrations.CreateModel(
            name="TrainingDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_name", models.CharField(max_length=255)),
                ("file_type", models.CharField(max_length=12)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("source_file", models.FileField(upload_to=anonymizer.models.training_upload_path)),
                ("preview_ciphertext", models.TextField(blank=True)),
                ("annotations_ciphertext", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("processing", "机器预标中"), ("ready", "待人工标注"), ("labeled", "已形成训练集"), ("failed", "预标失败")], default="processing", max_length=20)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"], "verbose_name": "训练标注文档", "verbose_name_plural": "训练标注文档"},
        ),
    ]
