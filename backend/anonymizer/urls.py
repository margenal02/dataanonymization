from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("stats/", views.stats, name="stats"),
    path("model/runtime/", views.model_runtime, name="model-runtime"),
    path("model/artifacts/", views.model_artifact_collection, name="model-artifact-collection"),
    path("model/artifacts/base/activate/", views.model_base_activate, name="model-base-activate"),
    path("model/artifacts/<uuid:artifact_id>/", views.model_artifact_detail, name="model-artifact-detail"),
    path("model/artifacts/<uuid:artifact_id>/activate/", views.model_artifact_activate, name="model-artifact-activate"),
    path("model/artifacts/<uuid:artifact_id>/export/", views.model_artifact_export, name="model-artifact-export"),
    path("labels/", views.label_collection, name="label-collection"),
    path("labels/<uuid:label_id>/", views.label_detail, name="label-detail"),
    path("training/documents/", views.training_document_collection, name="training-document-collection"),
    path("training/documents/<uuid:document_id>/", views.training_document_detail, name="training-document-detail"),
    path("training/export/", views.training_dataset_export, name="training-dataset-export"),
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<uuid:task_id>/", views.task_detail, name="task-detail"),
    path("tasks/<uuid:task_id>/cancel/", views.cancel_task, name="cancel-task"),
    path("tasks/<uuid:task_id>/review/", views.task_review, name="task-review"),
    path("tasks/<uuid:task_id>/restore/", views.restore_task, name="restore-task"),
    path("tasks/<uuid:task_id>/download/<str:kind>/", views.download_task, name="download-task"),
]
