from django.contrib import admin
from .models import AnonymizationTask, RecognitionLabel, TrainingExample


@admin.register(AnonymizationTask)
class AnonymizationTaskAdmin(admin.ModelAdmin):
    list_display = ("code", "task_name", "original_name", "file_type", "status", "created_at")
    list_filter = ("status", "file_type", "created_at")
    search_fields = ("task_name", "original_name", "sha256")
    readonly_fields = ("id", "sha256", "created_at", "updated_at", "mapping_ciphertext")


@admin.register(RecognitionLabel)
class RecognitionLabelAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "is_active", "created_at", "updated_at")
    list_filter = ("category", "is_active", "created_at")
    readonly_fields = ("id", "fingerprint", "text_ciphertext", "created_at", "updated_at")


@admin.register(TrainingExample)
class TrainingExampleAdmin(admin.ModelAdmin):
    list_display = ("id", "label", "action", "created_at")
    list_filter = ("action", "created_at")
    readonly_fields = ("id", "label", "action", "payload_ciphertext", "created_at")
