from rest_framework import serializers
from .models import AnonymizationTask


class TaskSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    display_name = serializers.SerializerMethodField()
    anonymized_download_url = serializers.SerializerMethodField()
    restored_download_url = serializers.SerializerMethodField()
    stored_files = serializers.SerializerMethodField()
    recognition_mode = serializers.SerializerMethodField()
    uie_detected_count = serializers.SerializerMethodField()
    uie_rejected_count = serializers.SerializerMethodField()
    processing_progress = serializers.SerializerMethodField()
    ocr_page_count = serializers.SerializerMethodField()

    class Meta:
        model = AnonymizationTask
        fields = [
            "id", "code", "task_name", "original_name", "display_name", "file_type", "file_size", "status",
            "entity_counts", "error_message", "created_at", "updated_at",
            "anonymized_download_url", "restored_download_url", "stored_files",
            "recognition_mode", "uie_detected_count", "uie_rejected_count",
            "processing_progress", "ocr_page_count",
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

    def get_recognition_mode(self, task):
        return (task.options or {}).get("uie_mode", "rules_only")

    def get_uie_detected_count(self, task):
        return int((task.options or {}).get("uie_detected_count", 0))

    def get_uie_rejected_count(self, task):
        return int((task.options or {}).get("uie_rejected_count", 0))

    def get_processing_progress(self, task):
        return (task.options or {}).get("processing_progress") or {}

    def get_ocr_page_count(self, task):
        return int((task.options or {}).get("ocr_page_count", 0))

    def get_stored_files(self, task):
        return {
            "original": bool(task.input_file),
            "anonymized": bool(task.anonymized_file),
            "restore_input": bool(task.restore_input_file),
            "restored": bool(task.restored_file),
        }
