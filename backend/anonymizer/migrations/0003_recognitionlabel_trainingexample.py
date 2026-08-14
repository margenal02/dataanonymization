import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0002_task_name")]

    operations = [
        migrations.CreateModel(
            name="RecognitionLabel",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("category", models.CharField(choices=[("organization", "单位"), ("person", "人名"), ("phone", "电话"), ("id_card", "证件"), ("email", "邮箱"), ("address", "地址"), ("custom", "敏感项")], max_length=24)),
                ("text_ciphertext", models.TextField()),
                ("fingerprint", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "本地识别标签", "verbose_name_plural": "本地识别标签", "ordering": ["category", "created_at"]},
        ),
        migrations.CreateModel(
            name="TrainingExample",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("created", "新增"), ("updated", "修改"), ("deleted", "停用"), ("task_custom", "任务新增")], max_length=24)),
                ("payload_ciphertext", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("label", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="anonymizer.recognitionlabel")),
            ],
            options={"verbose_name": "模型训练样本", "verbose_name_plural": "模型训练样本", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="recognitionlabel",
            constraint=models.UniqueConstraint(fields=("category", "fingerprint"), name="unique_recognition_label"),
        ),
    ]
