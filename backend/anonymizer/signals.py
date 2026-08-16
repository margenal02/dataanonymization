import shutil
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import AnonymizationTask, TrainingDocument


@receiver(post_delete, sender=AnonymizationTask)
def delete_task_files(sender, instance, **kwargs):
    """Clean task storage for API, admin, and queryset deletions alike."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    for folder in ("tasks", "processing"):
        target = (media_root / folder / str(instance.id)).resolve()
        if media_root not in target.parents:
            raise ValueError("Refusing to delete files outside MEDIA_ROOT.")
        if target.exists():
            shutil.rmtree(target)


@receiver(post_delete, sender=TrainingDocument)
def delete_training_document_files(sender, instance, **kwargs):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    for folder in ("training", "processing"):
        target = (media_root / folder / str(instance.id)).resolve()
        if media_root not in target.parents:
            raise ValueError("Refusing to delete files outside MEDIA_ROOT.")
        if target.exists():
            shutil.rmtree(target)
