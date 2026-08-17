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


def training_upload_path(instance, filename):
    return f"training/{instance.id}/input/{filename}"


class ModelArtifact(models.Model):
    """A validated, portable UIE checkpoint stored in local model storage."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=64, default="1.0.0")
    base_model = models.CharField(max_length=80, default="uie-base")
    storage_folder = models.CharField(max_length=255, unique=True)
    package_sha256 = models.CharField(max_length=64)
    package_size = models.PositiveBigIntegerField(default=0)
    file_manifest = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "本地 UIE 模型包"
        verbose_name_plural = "本地 UIE 模型包"

    def __str__(self):
        return f"{self.name} {self.version}"


class AnonymizationTask(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "处理中"
        REVIEW = "review", "待人工确认"
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


class RecognitionLabel(models.Model):
    CATEGORY_CHOICES = [
        ("organization", "单位"),
        ("person", "人名"),
        ("product", "品牌/产品"),
        ("location", "产区/地点"),
        ("phone", "电话"),
        ("id_card", "证件"),
        ("email", "邮箱"),
        ("address", "地址"),
        ("custom", "敏感项"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    text_ciphertext = models.TextField()
    fingerprint = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["category", "fingerprint"], name="unique_recognition_label"),
        ]
        verbose_name = "本地识别标签"
        verbose_name_plural = "本地识别标签"


class TrainingExample(models.Model):
    ACTION_CHOICES = [
        ("created", "新增"),
        ("updated", "修改"),
        ("deleted", "停用"),
        ("task_custom", "任务新增"),
        ("rejected", "人工否决"),
        ("annotated", "文档标注"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.ForeignKey(RecognitionLabel, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    payload_ciphertext = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "模型训练样本"
        verbose_name_plural = "模型训练样本"


class TrainingDocument(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "机器预标中"
        READY = "ready", "待人工标注"
        LABELED = "labeled", "已形成训练集"
        FAILED = "failed", "预标失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=12)
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    source_file = models.FileField(upload_to=training_upload_path)
    preview_ciphertext = models.TextField(blank=True)
    annotations_ciphertext = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "训练标注文档"
        verbose_name_plural = "训练标注文档"
