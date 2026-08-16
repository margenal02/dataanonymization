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
from .file_processors import (
    ProcessingError,
    SUPPORTED_EXTENSIONS,
    extract_pdf_pages,
    process_file,
    validate_upload_content,
)
from .models import AnonymizationTask, RecognitionLabel, TrainingExample
from .recognizer import CATEGORY_LABELS, DEFAULT_CATEGORIES, MappingBuilder, restore_text
from .serializers import TaskSerializer
from .training_data import (
    active_custom_entities,
    create_or_reactivate_label,
    deactivate_label,
    label_to_dict,
    record_rejected_entities,
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


def _as_bool(value, default=False):
    if value is None or value == "":
        return bool(default)
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _custom_entities(value):
    parsed = _parse_json(value, None)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    entities = []
    category_map = {
        "单位": "organization", "人名": "person", "产品": "product", "品牌": "product",
        "产区": "location", "地点": "location", "电话": "phone", "证件": "id_card",
        "邮箱": "email", "地址": "address", "敏感项": "custom",
    }
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


def _collect_text_chunks(source, task_id, progress_callback=None):
    chunks = []
    seen = set()
    total_chars = 0
    extension = Path(source).suffix.lower()

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

    if extension == ".pdf":
        pdf_pages = extract_pdf_pages(source, progress_callback)
        for page_text in pdf_pages:
            collect(page_text)
        return chunks, pdf_pages

    discovery_path = Path(settings.MEDIA_ROOT) / "processing" / str(task_id) / f"uie-discovery{extension}"

    try:
        process_file(source, discovery_path, collect)
    finally:
        discovery_path.unlink(missing_ok=True)
    return chunks, None


def _select_model_entities(builder, entities):
    """Apply per-category thresholds and resolve UIE type conflicts by surface value."""
    priority = {"organization": 5, "product": 4, "location": 3, "address": 2, "person": 1}
    selected = {}
    rejected_count = 0
    for entity in entities:
        category = entity.get("category")
        probability = float(entity.get("probability", 0.0) or 0.0)
        if probability < settings.UIE_CATEGORY_THRESHOLDS.get(category, 1.0):
            rejected_count += 1
            continue
        value = builder.validate_detected(entity.get("text"), category)
        if not value:
            rejected_count += 1
            continue
        candidate = dict(entity, text=value, probability=probability)
        # Once every candidate has passed its own threshold, prefer the more
        # specific tobacco-domain type for the same surface value.  The value is
        # still masked either way; this keeps the review label deterministic.
        score = (priority.get(category, 0), probability)
        current = selected.get(value)
        if current is None or score > current[0]:
            if current is not None:
                rejected_count += 1
            selected[value] = (score, candidate)
        else:
            rejected_count += 1
    ordered = sorted(
        (item[1] for item in selected.values()),
        key=lambda item: (item.get("text_index", 0), item.get("start", -1), -len(item.get("text", ""))),
    )
    return ordered, rejected_count


def _build_review_contexts(mapping, text_chunks, file_type, filename_stem, model_metadata, custom_keys):
    contexts = {}
    token_categories = mapping.get("token_categories", {})
    for token, original in mapping.get("token_to_original", {}).items():
        if not token.startswith("【"):
            continue
        category = token_categories.get(token, "custom")
        key = (original, category)
        occurrences = []
        for index, chunk in enumerate(text_chunks):
            start_at = 0
            while len(occurrences) < 3:
                position = chunk.find(original, start_at)
                if position < 0:
                    break
                prefix = re.sub(r"\s+", " ", chunk[max(0, position - 70):position]).strip()
                suffix = re.sub(r"\s+", " ", chunk[position + len(original):position + len(original) + 70]).strip()
                occurrences.append({
                    "prefix": prefix,
                    "match": original,
                    "suffix": suffix,
                    "location": f"第 {index + 1} 页" if file_type == "pdf" else f"文本片段 {index + 1}",
                })
                start_at = position + max(1, len(original))
            if len(occurrences) >= 3:
                break
        if not occurrences and original in filename_stem:
            position = filename_stem.find(original)
            occurrences.append({
                "prefix": filename_stem[:position],
                "match": original,
                "suffix": filename_stem[position + len(original):],
                "location": "文件名",
            })
        model_info = model_metadata.get(key, {})
        source = "model" if model_info else "label" if key in custom_keys else "rule"
        contexts[token] = {
            "source": source,
            "probability": model_info.get("probability"),
            "occurrences": occurrences,
        }
    return contexts


def _process_task(task, categories, uie_mode, combined_custom, excluded_entities=None, await_review=False):
    options = dict(task.options or {})
    task.status = AnonymizationTask.Status.PROCESSING

    def report_progress(event):
        progress = {
            "percent": max(0, min(100, int(event.get("percent", 0)))),
            "stage": str(event.get("stage", "processing")),
            "detail": str(event.get("detail", "正在处理文件")),
        }
        for key in ("current_page", "pdf_page_count", "ocr_page_count"):
            if key in event:
                progress[key] = int(event[key])
                options[key] = int(event[key])
        options["processing_progress"] = progress
        task.options = options
        task.save(update_fields=["status", "options", "updated_at"])

    report_progress({"percent": 2, "stage": "prepare", "detail": "文件已保存，正在检查内容结构"})
    model_entity_count = 0
    model_metadata = {}
    text_chunks, pdf_pages = _collect_text_chunks(
        task.input_file.path,
        task.id,
        progress_callback=report_progress,
    )
    filename_stem = Path(task.original_name).stem
    recognition_chunks = list(text_chunks)
    if filename_stem and filename_stem not in recognition_chunks:
        recognition_chunks.append(filename_stem)
    searchable_text = "\n".join(recognition_chunks)
    matching_custom = [
        item for item in combined_custom
        if str(item.get("text", "")).strip() and str(item.get("text", "")).strip() in searchable_text
    ]
    custom_keys = {
        (str(item.get("text", "")).strip(), item.get("category", "custom"))
        for item in matching_custom
    }
    builder = MappingBuilder(
        str(task.id), categories, matching_custom, excluded_entities=excluded_entities,
    )
    for text_chunk in recognition_chunks:
        builder.discover(text_chunk)

    if settings.UIE_ENABLED and set(categories) & {"person", "organization", "address", "location", "product"}:
        report_progress({"percent": 60, "stage": "uie", "detail": "正在使用 UIE-micro 复核敏感信息"})
        model_entities, rejected_count = _select_model_entities(
            builder, predict_entities(recognition_chunks, categories, uie_mode)
        )
        for entity in model_entities:
            if builder.register_detected(entity.get("text"), entity.get("category")):
                model_entity_count += 1
                model_metadata[(entity.get("text"), entity.get("category"))] = {
                    "probability": round(float(entity.get("probability", 0.0)), 4),
                }
        options["uie_rejected_count"] = rejected_count
    options["uie_detected_count"] = model_entity_count

    anonymized_stem = builder.anonymize_filename_stem(Path(task.original_name).stem)
    if await_review:
        report_progress({"percent": 75, "stage": "review", "detail": "识别完成，正在整理人工确认候选"})
        if task.anonymized_file:
            task.anonymized_file.delete(save=False)
    else:
        output_name = _output_name(task.original_name, "已脱敏", anonymized_stem)
        output_path = Path(settings.MEDIA_ROOT) / "processing" / str(task.id) / output_name
        report_progress({"percent": 70, "stage": "write", "detail": "人工选择已确认，正在生成脱敏文件"})
        try:
            process_file(
                task.input_file.path,
                output_path,
                builder.anonymize,
                pdf_pages=pdf_pages,
                progress_callback=report_progress,
            )
            if task.anonymized_file:
                task.anonymized_file.delete(save=False)
            with output_path.open("rb") as handle:
                task.anonymized_file.save(output_name, File(handle), save=False)
        finally:
            output_path.unlink(missing_ok=True)

    mapping = builder.export()
    mapping["review_exclusions"] = list(excluded_entities or [])
    mapping["review_contexts"] = _build_review_contexts(
        mapping,
        text_chunks,
        task.file_type,
        filename_stem,
        model_metadata,
        custom_keys,
    )
    task.mapping_ciphertext = encrypt_mapping(mapping)
    task.entity_counts = builder.counts()
    task.task_name = _task_name(anonymized_stem)
    task.options = options
    task.options["review_required"] = bool(options.get("review_required", await_review))
    task.options["review_confirmed"] = not await_review
    task.options["processing_progress"] = {
        "percent": 100,
        "stage": "review" if await_review else "completed",
        "detail": "候选识别完成，请人工确认" if await_review else "脱敏文件生成完成",
    }
    task.error_message = ""
    task.status = AnonymizationTask.Status.REVIEW if await_review else AnonymizationTask.Status.COMPLETED
    task.save()
    return task


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
    review_required = _as_bool(
        request.data.get("review_required"),
        getattr(settings, "REQUIRE_HUMAN_REVIEW", True),
    )
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
            "review_required": review_required,
            "review_confirmed": False,
        },
    )

    try:
        _process_task(task, categories, uie_mode, combined_custom, await_review=review_required)
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


def _review_entities(mapping):
    categories = mapping.get("token_categories", {})
    context_map = mapping.get("review_contexts", {})
    entities = []
    for token, text in mapping.get("token_to_original", {}).items():
        if not token.startswith("【"):
            continue
        category = categories.get(token, "custom")
        entities.append({
            "token": token,
            "text": text,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, CATEGORY_LABELS["custom"]),
            "source": context_map.get(token, {}).get("source", "rule"),
            "probability": context_map.get(token, {}).get("probability"),
            "occurrences": context_map.get(token, {}).get("occurrences", []),
        })
    return sorted(entities, key=lambda item: (item["category_label"], item["token"]))


@api_view(["GET", "POST"])
def task_review(request, task_id):
    task = get_object_or_404(AnonymizationTask, id=task_id)
    if not task.mapping_ciphertext or not task.input_file:
        return Response({"detail": "该任务没有可校正的识别映射或原始文件。"}, status=status.HTTP_409_CONFLICT)
    try:
        mapping = decrypt_mapping(task.mapping_ciphertext)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    if request.method == "GET":
        return Response({
            "task": TaskSerializer(task, context={"request": request}).data,
            "entities": _review_entities(mapping),
            "excluded_count": len(mapping.get("review_exclusions", [])),
        })

    additions = _custom_entities(request.data.get("additions", ""))
    remove_tokens = request.data.get("remove_tokens", [])
    if not isinstance(remove_tokens, list):
        return Response({"detail": "误识别标记必须是列表。"}, status=status.HTTP_400_BAD_REQUEST)
    token_to_original = mapping.get("token_to_original", {})
    token_categories = mapping.get("token_categories", {})
    entity_tokens = [token for token in token_to_original if token.startswith("【")]
    selected_payload = request.data.get("selected_entities")
    selected_by_token = {}
    if selected_payload is not None:
        if not isinstance(selected_payload, list):
            return Response({"detail": "已选识别项必须是列表。"}, status=status.HTTP_400_BAD_REQUEST)
        for item in selected_payload:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token", ""))
            category = str(item.get("category", token_categories.get(token, "custom")))
            if token in entity_tokens and category in {*DEFAULT_CATEGORIES, "custom"}:
                selected_by_token[token] = category
    else:
        removed_set = set(remove_tokens)
        selected_by_token = {
            token: token_categories.get(token, "custom")
            for token in entity_tokens
            if token not in removed_set
        }

    removals = []
    category_corrections = []
    for token in entity_tokens:
        old_category = token_categories.get(token, "custom")
        selected_category = selected_by_token.get(token)
        if selected_category is None or selected_category != old_category:
            removals.append({"text": token_to_original[token], "category": old_category})
        if selected_category is not None and selected_category != old_category:
            category_corrections.append({
                "text": token_to_original[token],
                "category": selected_category,
            })
    additions = list({
        (item["category"], item["text"]): item
        for item in [*additions, *category_corrections]
    }.values())

    try:
        save_task_custom_entities(additions)
        previous_exclusions = [
            item for item in mapping.get("review_exclusions", []) if isinstance(item, dict)
        ]
        additions_keys = {(item.get("text", "").strip(), item.get("category", "custom")) for item in additions}
        exclusions_by_key = {
            (item.get("text", "").strip(), item.get("category", "custom")): item
            for item in [*previous_exclusions, *removals]
            if item.get("text", "").strip()
        }
        for key in additions_keys:
            exclusions_by_key.pop(key, None)
        excluded_entities = list(exclusions_by_key.values())
        learned = active_custom_entities()
        combined_custom = list({(item["category"], item["text"]): item for item in learned}.values())
        categories = [
            item for item in (task.options or {}).get("categories", DEFAULT_CATEGORIES)
            if item in DEFAULT_CATEGORIES
        ]
        uie_mode = (task.options or {}).get("uie_mode", "on_demand")
        _process_task(task, categories, uie_mode, combined_custom, excluded_entities, await_review=False)
        if removals:
            record_rejected_entities(removals, task.id)
        for field_name in ("restore_input_file", "restored_file"):
            field = getattr(task, field_name)
            if field:
                field.delete(save=False)
        task.save(update_fields=["restore_input_file", "restored_file", "updated_at"])
    except (ProcessingError, UIEProcessingError, ValueError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except Exception:
        return Response({"detail": "校正后重新处理失败，请查看后端日志。"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return Response({
        "task": TaskSerializer(task, context={"request": request}).data,
        "entities": _review_entities(decrypt_mapping(task.mapping_ciphertext)),
        "excluded_count": len(excluded_entities),
    })


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
        if task.status == AnonymizationTask.Status.REVIEW:
            return Response({"detail": "请先完成人工确认，再下载脱敏文件。"}, status=status.HTTP_409_CONFLICT)
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
    totals = {
        "tasks": tasks.count(),
        "completed": tasks.filter(status__in=["completed", "restored"]).count(),
        "restored": tasks.filter(status="restored").count(),
        "entities": 0,
        "training_examples": TrainingExample.objects.count(),
        "active_labels": RecognitionLabel.objects.filter(is_active=True).count(),
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
    }
    for counts in tasks.values_list("entity_counts", flat=True):
        totals["entities"] += sum(counts.values()) if isinstance(counts, dict) else 0
    return Response(totals)
