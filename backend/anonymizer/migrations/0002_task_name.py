from pathlib import Path

from django.db import migrations, models


def populate_task_names(apps, schema_editor):
    task_model = apps.get_model("anonymizer", "AnonymizationTask")
    for task in task_model.objects.all().iterator():
        task.task_name = Path(task.original_name).stem[:120] or "数据脱敏任务"
        task.save(update_fields=["task_name"])


class Migration(migrations.Migration):
    dependencies = [("anonymizer", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="anonymizationtask",
            name="task_name",
            field=models.CharField(db_index=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.RunPython(populate_task_names, migrations.RunPython.noop),
    ]
