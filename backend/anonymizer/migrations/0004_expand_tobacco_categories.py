from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0003_recognitionlabel_trainingexample")]

    operations = [
        migrations.AlterField(
            model_name="recognitionlabel",
            name="category",
            field=models.CharField(
                choices=[
                    ("organization", "单位"),
                    ("person", "人名"),
                    ("product", "品牌/产品"),
                    ("location", "产区/地点"),
                    ("phone", "电话"),
                    ("id_card", "证件"),
                    ("email", "邮箱"),
                    ("address", "地址"),
                    ("custom", "敏感项"),
                ],
                max_length=24,
            ),
        ),
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
                ],
                max_length=24,
            ),
        ),
    ]
