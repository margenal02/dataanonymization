from django.core.management.base import BaseCommand

from anonymizer.models import AnonymizationTask


class Command(BaseCommand):
    help = "Recover tasks left in processing state after a backend restart."

    def handle(self, *args, **options):
        recovered = 0
        for task in AnonymizationTask.objects.filter(status=AnonymizationTask.Status.PROCESSING):
            task_options = dict(task.options or {})
            previous_status = task_options.pop("processing_previous_status", "")
            if previous_status not in {
                AnonymizationTask.Status.REVIEW,
                AnonymizationTask.Status.COMPLETED,
                AnonymizationTask.Status.RESTORED,
            }:
                if task.anonymized_file:
                    previous_status = AnonymizationTask.Status.COMPLETED
                elif task.mapping_ciphertext:
                    previous_status = AnonymizationTask.Status.REVIEW
                else:
                    previous_status = AnonymizationTask.Status.CANCELLED
            task_options["processing_progress"] = {
                "percent": int((task_options.get("processing_progress") or {}).get("percent", 0)),
                "stage": "cancelled",
                "detail": "服务重启，未完成的处理已安全中断",
            }
            task.status = previous_status
            task.options = task_options
            task.cancel_requested = False
            task.error_message = "服务重启导致本次处理被中断，原始文件和上一版本结果均已保留。"
            task.save(update_fields=[
                "status", "options", "cancel_requested", "error_message", "updated_at",
            ])
            recovered += 1
        if recovered:
            self.stdout.write(self.style.WARNING(f"已恢复 {recovered} 个被重启中断的任务。"))
