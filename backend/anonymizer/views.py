import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .crypto import decrypt_mapping, encrypt_mapping
from .file_processors import ProcessingError, SUPPORTED_EXTENSIONS, process_file, validate_upload_content
from .models import AnonymizationTask, RecognitionLabel, TrainingExample
from .recognizer import DEFAULT_CATEGORIES, MappingBuilder, restore_text
from .serializers import TaskSerializer
from .training_data import (
    active_custom_entities,
    create_or_reactivate_label,
    deactivate_label,
    label_to_dict,
    save_task_custom_entities,
    update_label,
)
from .uie_runtime import UIEProcessingError, predict_entities, runtime_status, set_runtime_mode


def _safe_name(name):
    clean = Path(name).name
    return re.sub(r"[\\/:*?\"<>|]", "_", clean)


def _output_name(original, suffix, stem=None):
    path = Path(original)
    output_stem = path.stem if stem is None else stem
    output_stem = re.sub(
        r"(?:[\s_-]*(?:已脱敏|脱敏|匿名|AI处理稿|AI处理|正式版))+$",
        "",
        output_stem,
        flags=re.I,
    ).strip(" _-")
    return f"{output_stem or '数据文件'}_{suffix}{path.suffix.lower()}"


def _task_name(filename):
    name = Path(filename).stem.strip()
    name = re.sub(r"(?:[\s_-]*(?:已脱敏|脱敏|匿名|AI处理稿|AI处理|正式版))+$", "", name, flags=re.I).strip()
    name = re.sub(r"[<>\x00-\x1f]", "_", name)
    return (name or "数据脱敏任务")[:120]


def _parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _custom_entities(value):
    parsed = _parse_json(value, None)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    entities = []
    category_map = {"单位": "organization", "人名": "person", "电话": "phone", "证件": "id_card", "邮箱": "email", "地址": "address"}
    for line in (value or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            label, text = line.split("|", 1)
            entities.append({"text": text.strip(), "category": category_map.get(label.strip(), "custom")})
        else:
            entities.append({"text": line, "category": "custom"})
    return entities


def _validate_upload(upload):
    if not upload:
        return "请选择需要处理的文件。"
    extension = Path(upload.name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return "仅支持 .xls、.docx、.pdf、.ofd、.txt 文件。"
    if upload.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return f"文件大小不能超过 {settings.MAX_UPLOAD_SIZE_MB} MB。"
    try:
        validate_upload_content(upload)
    except ProcessingError as exc:
        return str(exc)
    return None


def _sha256(upload):
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _collect_text_chunks(source, task_id):
    chunks = []
    seen = set()
    total_chars = 0
    extension = Path(source).suffix.lower()
    discovery_path = Path(settings.MEDIA_ROOT) / "processing" / str(task_id) / f"uie-discovery{extension}"

    def collect(text):
        nonlocal total_chars
        value = str(text or "").strip()
        if not value or value in seen:
            return text
        total_chars += len(value)
        if total_chars > settings.UIE_MAX_TOTAL_CHARS:
            raise ProcessingError(
                f"文件可识别文字超过 UIE 上限 {settings.UIE_MAX_TOTAL_CHARS} 字符，请拆分文件后处理。"
            )
        seen.add(value)
        chunks.append(value)
        return text

    try:
        process_file(source, discovery_path, collect)
    finally:
        discovery_path.unlink(missing_ok=True)
    return chunks


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "烟草行业数据脱敏系统", "time": timezone.now()})


@api_view(["GET", "POST"])
def model_runtime(request):
    if request.method == "GET":
        return Response(runtime_status())
    mode = request.data.get("mode", "on_demand")
    try:
        set_runtime_mode(mode)
    except UIEProcessingError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    result = runtime_status()
    result["selected_mode"] = mode
    return Response(result)


@api_view(["GET", "POST"])
def label_collection(request):
    if request.method == "GET":
        labels = [label_to_dict(label) for label in RecognitionLabel.objects.filter(is_active=True)]
        return Response({
            "labels": labels,
            "active_count": len(labels),
            "training_example_count": TrainingExample.objects.count(),
        })
    try:
        label, changed = create_or_reactivate_label(request.data.get("text"), request.data.get("category", "custom"))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(label_to_dict(label), status=status.HTTP_201_CREATED if changed else status.HTTP_200_OK)


@api_view(["PATCH", "DELETE"])
def label_detail(request, label_id):
    label = get_object_or_404(RecognitionLabel, id=label_id, is_active=True)
    if request.method == "DELETE":
        deactivate_label(label)
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        label = update_label(
            label,
            request.data.get("text", label_to_dict(label)["text"]),
            request.data.get("category", label.category),
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(label_to_dict(label))


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
def task_collection(request):
    if request.method == "GET":
        tasks = AnonymizationTask.objects.all()[:100]
        return Response(TaskSerializer(tasks, many=True, context={"request": request}).data)

    upload = request.FILES.get("file")
    error = _validate_upload(upload)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

    categories = _parse_json(request.data.get("categories"), DEFAULT_CATEGORIES)
    categories = [item for item in categories if item in DEFAULT_CATEGORIES]
    uie_mode = request.data.get("uie_mode", "on_demand")
    if uie_mode not in {"on_demand", "resident"}:
        return Response({"detail": "无效的 UIE 运行模式。"}, status=status.HTTP_400_BAD_REQUEST)
    custom = _custom_entities(request.data.get("custom_entities", ""))
    try:
        save_task_custom_entities(custom)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    learned = active_custom_entities()
    combined_custom = list({(item["category"], item["text"]): item for item in [*learned, *custom]}.values())
    original_name = _safe_name(upload.name)
    task = AnonymizationTask.objects.create(
        task_name=_task_name(original_name),
        original_name=original_name,
        file_type=Path(original_name).suffix.lower().lstrip("."),
        file_size=upload.size,
        sha256=_sha256(upload),
        input_file=upload,
        options={
            "categories": categories,
            "custom_entity_count": len(custom),
            "learned_label_count": len(learned),
            "uie_mode": uie_mode,
            "uie_model": settings.UIE_MODEL if settings.UIE_ENABLED else "disabled",
        },
    )

    try:
        builder = MappingBuilder(str(task.id), categories, combined_custom)
        model_entity_count = 0
        if settings.UIE_ENABLED and set(categories) & {"person", "organization", "address"}:
            text_chunks = _collect_text_chunks(task.input_file.path, task.id)
            filename_stem = Path(original_name).stem
            if filename_stem and filename_stem not in text_chunks:
                text_chunks.append(filename_stem)
            model_entities = predict_entities(text_chunks, categories, uie_mode)
            for entity in sorted(model_entities, key=lambda item: (-len(item.get("text", "")), item.get("text_index", 0))):
                if builder.register_detected(entity.get("text"), entity.get("category")):
                    model_entity_count += 1
            task.options["uie_detected_count"] = model_entity_count
        anonymized_stem = builder.anonymize_filename_stem(Path(original_name).stem)
        output_name = _output_name(original_name, "已脱敏", anonymized_stem)
        output_path = Path(settings.MEDIA_ROOT) / "processing" / str(task.id) / output_name
        process_file(task.input_file.path, output_path, builder.anonymize)
        with output_path.open("rb") as handle:
            task.anonymized_file.save(output_name, File(handle), save=False)
        task.mapping_ciphertext = encrypt_mapping(builder.export())
        task.entity_counts = builder.counts()
        task.task_name = _task_name(anonymized_stem)
        task.status = AnonymizationTask.Status.COMPLETED
        task.save()
        output_path.unlink(missing_ok=True)
    except Exception as exc:
        task.status = AnonymizationTask.Status.FAILED
        task.error_message = str(exc) if isinstance(exc, (ProcessingError, UIEProcessingError, ValueError)) else "文件处理失败，请检查文件是否损坏。"
        task.save(update_fields=["status", "error_message", "updated_at"])
        return Response(TaskSerializer(task, context={"request": request}).data, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return Response(TaskSerializer(task, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
def task_detail(request, task_id):
    task = get_object_or_404(AnonymizationTask, id=task_id)
    if request.method == "DELETE":
        if request.headers.get("X-Task-Delete-Confirm") != str(task.id):
            return Response({"detail": "缺少有效的删除确认信息。"}, status=status.HTTP_400_BAD_REQUEST)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(TaskSerializer(task, context={"request": request}).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def restore_task(request, task_id):
    task = get_object_or_404(AnonymizationTask, id=task_id)
    upload = request.FILES.get("file")
    error = _validate_upload(upload)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    if not task.mapping_ciphertext:
        return Response({"detail": "该任务没有可用的匿名映射。"}, status=status.HTTP_409_CONFLICT)

    upload_name = _safe_name(upload.name)
    if task.restore_input_file:
        task.restore_input_file.delete(save=False)
    task.restore_input_file.save(upload_name, upload, save=True)
    try:
        mapping = decrypt_mapping(task.mapping_ciphertext)
        restored_upload_name = restore_text(upload_name, mapping)
        output_name = _output_name(restored_upload_name, "正式版")
        output_path = Path(settings.MEDIA_ROOT) / "processing" / str(task.id) / output_name
        process_file(task.restore_input_file.path, output_path, lambda text: restore_text(text, mapping))
        if task.restored_file:
            task.restored_file.delete(save=False)
        with output_path.open("rb") as handle:
            task.restored_file.save(output_name, File(handle), save=False)
        task.status = AnonymizationTask.Status.RESTORED
        task.error_message = ""
        task.save()
        output_path.unlink(missing_ok=True)
    except Exception as exc:
        task.error_message = str(exc) if isinstance(exc, (ProcessingError, ValueError)) else "反匿名处理失败，请检查文件格式。"
        task.save(update_fields=["error_message", "updated_at"])
        return Response({"detail": task.error_message}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return Response(TaskSerializer(task, context={"request": request}).data)


@api_view(["GET"])
def download_task(request, task_id, kind):
    task = get_object_or_404(AnonymizationTask, id=task_id)
    if kind == "anonymized":
        field = task.anonymized_file
        filename = Path(field.name).name if field else ""
    elif kind == "restored":
        field = task.restored_file
        filename = Path(field.name).name if field else ""
    else:
        return Response({"detail": "无效的下载类型。"}, status=status.HTTP_404_NOT_FOUND)
    if not field:
        return Response({"detail": "文件不存在。"}, status=status.HTTP_404_NOT_FOUND)
    return FileResponse(field.open("rb"), as_attachment=True, filename=filename)


@api_view(["GET"])
def stats(request):
    tasks = AnonymizationTask.objects.all()
    totals = {"tasks": tasks.count(), "completed": tasks.filter(status__in=["completed", "restored"]).count(), "restored": tasks.filter(status="restored").count(), "entities": 0, "training_examples": TrainingExample.objects.count(), "active_labels": RecognitionLabel.objects.filter(is_active=True).count()}
    for counts in tasks.values_list("entity_counts", flat=True):
        totals["entities"] += sum(counts.values()) if isinstance(counts, dict) else 0
    return Response(totals)
