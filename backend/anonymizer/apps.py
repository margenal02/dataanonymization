from django.apps import AppConfig


class AnonymizerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "anonymizer"
    verbose_name = "数据脱敏"

    def ready(self):
        from . import signals  # noqa: F401
