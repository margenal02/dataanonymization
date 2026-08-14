from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("stats/", views.stats, name="stats"),
    path("model/runtime/", views.model_runtime, name="model-runtime"),
    path("labels/", views.label_collection, name="label-collection"),
    path("labels/<uuid:label_id>/", views.label_detail, name="label-detail"),
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<uuid:task_id>/", views.task_detail, name="task-detail"),
    path("tasks/<uuid:task_id>/restore/", views.restore_task, name="restore-task"),
    path("tasks/<uuid:task_id>/download/<str:kind>/", views.download_task, name="download-task"),
]
