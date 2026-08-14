from rest_framework import serializers
from .models import AnonymizationTask


class TaskSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    display_name = serializers.SerializerMethodField()
    anonymized_download_url = serializers.SerializerMethodField()
    restored_download_url = serializers.SerializerMethodField()
    stored_files = serializers.SerializerMethodField()

    class Meta:
        model = AnonymizationTask
        fields = [
            "id", "code", "task_name", "original_name", "display_name", "file_type", "file_size", "status",
            "entity_counts", "error_message", "created_at", "updated_at",
            "anonymized_download_url", "restored_download_url", "stored_files",
        ]

    def _url(self, task, kind):
        field = task.anonymized_file if kind == "anonymized" else task.restored_file
        if not field:
            return None
        return f"/api/tasks/{task.id}/download/{kind}/"

    def get_anonymized_download_url(self, task):
        return self._url(task, "anonymized")

    def get_restored_download_url(self, task):
        return self._url(task, "restored")

    def get_display_name(self, task):
        field = task.restored_file if task.status == task.Status.RESTORED else task.anonymized_file
        return field.name.rsplit("/", 1)[-1] if field else task.original_name

    def get_stored_files(self, task):
        return {
            "original": bool(task.input_file),
            "anonymized": bool(task.anonymized_file),
            "restore_input": bool(task.restore_input_file),
            "restored": bool(task.restored_file),
        }
