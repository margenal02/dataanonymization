from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("stats/", views.stats, name="stats"),
    path("tasks/", views.task_collection, name="task-collection"),
    path("tasks/<uuid:task_id>/", views.task_detail, name="task-detail"),
    path("tasks/<uuid:task_id>/restore/", views.restore_task, name="restore-task"),
    path("tasks/<uuid:task_id>/download/<str:kind>/", views.download_task, name="download-task"),
]

