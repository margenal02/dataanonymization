from django.contrib import admin
from .models import AnonymizationTask


@admin.register(AnonymizationTask)
class AnonymizationTaskAdmin(admin.ModelAdmin):
    list_display = ("code", "task_name", "original_name", "file_type", "status", "created_at")
    list_filter = ("status", "file_type", "created_at")
    search_fields = ("task_name", "original_name", "sha256")
    readonly_fields = ("id", "sha256", "created_at", "updated_at", "mapping_ciphertext")
