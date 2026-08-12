import uuid
from django.db import models


def input_upload_path(instance, filename):
    return f"tasks/{instance.id}/input/{filename}"


def output_upload_path(instance, filename):
    return f"tasks/{instance.id}/output/{filename}"


def restore_input_upload_path(instance, filename):
    return f"tasks/{instance.id}/restore-input/{filename}"


def restored_upload_path(instance, filename):
    return f"tasks/{instance.id}/restored/{filename}"


class AnonymizationTask(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "处理中"
        COMPLETED = "completed", "脱敏完成"
        RESTORED = "restored", "已反匿名"
        FAILED = "failed", "处理失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_name = models.CharField(max_length=120, db_index=True)
    original_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=12)
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    input_file = models.FileField(upload_to=input_upload_path)
    anonymized_file = models.FileField(upload_to=output_upload_path, blank=True)
    restore_input_file = models.FileField(upload_to=restore_input_upload_path, blank=True)
    restored_file = models.FileField(upload_to=restored_upload_path, blank=True)
    mapping_ciphertext = models.TextField(blank=True)
    entity_counts = models.JSONField(default=dict, blank=True)
    options = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "脱敏任务"
        verbose_name_plural = "脱敏任务"

    @property
    def code(self):
        return f"DA-{self.created_at:%Y%m%d}-{str(self.id)[:6].upper()}" if self.created_at else str(self.id)[:8]

    def __str__(self):
        return f"{self.code} {self.task_name}"
