from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("anonymizer", "0007_modelartifact"),
    ]

    operations = [
        migrations.AddField(
            model_name="anonymizationtask",
            name="cancel_requested",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="anonymizationtask",
            name="status",
            field=models.CharField(
                choices=[
                    ("processing", "处理中"),
                    ("review", "待人工确认"),
                    ("completed", "脱敏完成"),
                    ("restored", "已反匿名"),
                    ("failed", "处理失败"),
                    ("cancelled", "已中断"),
                ],
                default="processing",
                max_length=20,
            ),
        ),
    ]
