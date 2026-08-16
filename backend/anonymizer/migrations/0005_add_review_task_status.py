from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0004_expand_tobacco_categories")]

    operations = [
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
                ],
                default="processing",
                max_length=20,
            ),
        ),
    ]
