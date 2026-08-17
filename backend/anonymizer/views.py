import hashlib
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import connection
from django.http import FileResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .crypto import decrypt_mapping, encrypt_mapping
from .entity_schema import UIE_TRAINING_PROMPT_BY_CATEGORY
from .file_processors import (
    ProcessingError,
    SUPPORTED_EXTENSIONS,
    extract_pdf_pages,
    process_file,
    validate_upload_content,
)
from .models import AnonymizationTask, ModelArtifact, RecognitionLabel, TrainingDocument, TrainingExample
from .model_packages import (
    ModelPackageError,
    activate_artifact,
    artifact_to_dict,
    build_export_file,
    import_model_package,
)
from .recognizer import (
    CATEGORY_LABELS,
    DEFAULT_CATEGORIES,
    MappingBuilder,
    build_restorer,
    contains_equivalent,
    registered_match_spans,
    suggest_organization_alias_groups,
)
from .serializers import TaskSerializer
from .training_data import (
    active_custom_entities,
    create_or_reactivate_label,
    deactivate_label,
    label_to_dict,
    record_rejected_entities,
    record_document_annotations,
    save_task_custom_entities,
    update_label,
)
from .throttles import LocalUploadThrottle
from .uie_runtime import UIEProcessingError, predict_entities, runtime_status, set_runtime_mode


logger = logging.getLogger(__name__)


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
    total_chars = 0
    extension = Path(source).suffix.lower()

    def collect(text):
        nonlocal total_chars
        value = str(text or "").strip()
        if not value:
            return text
        total_chars += len(value)
        if total_chars > settings.UIE_MAX_TOTAL_CHARS:
            raise ProcessingError(
                f"文件可识别文字超过 UIE 上限 {settings.UIE_MAX_TOTAL_CHARS} 字符，请拆分文件后处理。"
            )
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
    for original, token in mapping.get("original_to_token", {}).items():
        category = token_categories.get(token, "custom")
        key = (original, category)
        occurrences = []
        for index, chunk in enumerate(text_chunks):
            for match in registered_match_spans(chunk, {original: token}):
                position = match["start"]
                end = match["end"]
                prefix = re.sub(r"\s+", " ", chunk[max(0, position - 70):position]).strip()
                suffix = re.sub(r"\s+", " ", chunk[end:end + 70]).strip()
                occurrences.append({
                    "prefix": prefix,
                    "match": match["text"],
                    "suffix": suffix,
                    "location": f"第 {index + 1} 页" if file_type == "pdf" else f"文本片段 {index + 1}",
                })
                if len(occurrences) >= 3:
                    break
            if len(occurrences) >= 3:
                break
        filename_matches = registered_match_spans(filename_stem, {original: token})
        if not occurrences and filename_matches:
            filename_match = filename_matches[0]
            position = filename_match["start"]
            occurrences.append({
                "prefix": filename_stem[:position],
                "match": filename_match["text"],
                "suffix": filename_stem[filename_match["end"]:],
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


def _build_review_preview(mapping, text_chunks, file_type, filename_stem):
    """Build an encrypted full-text preview with non-overlapping entity spans."""
    original_to_token = mapping.get("original_to_token") or {
        original: token for token, original in mapping.get("token_to_original", {}).items()
        if token.startswith("【")
    }
    token_categories = mapping.get("token_categories", {})
    sections = []
    source_sections = [
        {
            "location": f"第 {index + 1} 页" if file_type == "pdf" else f"文本片段 {index + 1}",
            "text": chunk,
        }
        for index, chunk in enumerate(text_chunks)
    ]
    if filename_stem:
        source_sections.insert(0, {"location": "文件名", "text": filename_stem})
    for section_index, section in enumerate(source_sections):
        text = section["text"]
        spans = []
        for match in registered_match_spans(text, original_to_token):
            spans.append({
                "start": match["start"],
                "end": match["end"],
                "text": match["text"],
                "entity_text": match["entity_text"],
                "token": match["token"],
                "category": token_categories.get(match["token"], "custom"),
            })
        sections.append({
            "index": section_index,
            "location": section["location"],
            "text": text,
            "spans": sorted(spans, key=lambda item: item["start"]),
        })
    return sections


def _process_task(
    task,
    categories,
    uie_mode,
    combined_custom,
    excluded_entities=None,
    await_review=False,
    accepted_alias_groups=None,
    previous_mapping=None,
):
    processing_started = time.monotonic()
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
        if str(item.get("text", "")).strip()
        and contains_equivalent(searchable_text, str(item.get("text", "")).strip())
    ]
    custom_keys = {
        (str(item.get("text", "")).strip(), item.get("category", "custom"))
        for item in matching_custom
    }
    builder = MappingBuilder(
        str(task.id),
        categories,
        matching_custom,
        excluded_entities=excluded_entities,
        previous_mapping=previous_mapping,
        token_namespace=settings.ANONYMIZATION_NAMESPACE,
    )
    for text_chunk in recognition_chunks:
        builder.discover(text_chunk)

    if settings.UIE_ENABLED and set(categories) & {"person", "organization", "address", "location", "product"}:
        report_progress({"percent": 60, "stage": "uie", "detail": "正在使用 UIE-base 复核敏感信息"})
        model_entities, rejected_count = _select_model_entities(
            builder, predict_entities(list(dict.fromkeys(recognition_chunks)), categories, uie_mode)
        )
        for entity in model_entities:
            if builder.register_detected(entity.get("text"), entity.get("category")):
                model_entity_count += 1
                model_metadata[(entity.get("text"), entity.get("category"))] = {
                    "probability": round(float(entity.get("probability", 0.0)), 4),
                }
        options["uie_rejected_count"] = rejected_count
    options["uie_detected_count"] = model_entity_count

    alias_suggestions = suggest_organization_alias_groups(builder, searchable_text)
    applied_alias_groups = []
    for group in accepted_alias_groups or []:
        if not isinstance(group, dict):
            continue
        canonical = str(group.get("canonical", "")).strip()
        members = [str(item).strip() for item in group.get("members", []) if str(item).strip()]
        if canonical and canonical in members:
            token = builder.merge_aliases(canonical, members, group.get("category", "organization"))
            if token:
                applied_alias_groups.append({
                    "id": str(group.get("id", "")),
                    "category": group.get("category", "organization"),
                    "canonical": canonical,
                    "members": list(dict.fromkeys(members)),
                    "reason": str(group.get("reason", "人工确认同一实体")),
                    "confidence": float(group.get("confidence", 1.0) or 1.0),
                    "accepted": True,
                    "token": token,
                })

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
                builder.anonymize_registered,
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
    mapping["machine_scope"] = "local-encrypted-mapping"
    mapping["review_exclusions"] = list(excluded_entities or [])
    mapping["review_contexts"] = _build_review_contexts(
        mapping,
        text_chunks,
        task.file_type,
        filename_stem,
        model_metadata,
        custom_keys,
    )
    mapping["review_preview"] = _build_review_preview(mapping, text_chunks, task.file_type, filename_stem)
    mapping["alias_suggestions"] = applied_alias_groups or alias_suggestions
    if not await_review:
        save_task_custom_entities([
            {
                "text": original,
                "category": mapping.get("token_categories", {}).get(token, "custom"),
            }
            for original, token in mapping.get("original_to_token", {}).items()
        ])
    review_metrics = dict(options.get("review_metrics") or {})
    if await_review:
        review_metrics.update({
            "candidate_count": len(mapping.get("original_to_token", {})),
            "candidate_occurrence_count": sum(
                len(section.get("spans", [])) for section in mapping["review_preview"]
            ),
            "model_detected_count": model_entity_count,
            "model_rejected_count": int(options.get("uie_rejected_count", 0)),
            "alias_suggestion_count": len(alias_suggestions),
            "recognized_at": timezone.now().isoformat(),
        })
        options["recognition_duration_ms"] = round((time.monotonic() - processing_started) * 1000)
    else:
        review_metrics.update({
            "confirmed_entity_count": len(mapping.get("original_to_token", {})),
            "confirmed_occurrence_count": sum(
                len(section.get("spans", [])) for section in mapping["review_preview"]
            ),
        })
        options["last_processing_duration_ms"] = round((time.monotonic() - processing_started) * 1000)
    options["review_metrics"] = review_metrics
    task.mapping_ciphertext = encrypt_mapping(mapping)
    task.entity_counts = builder.counts()
    task.task_name = _task_name(anonymized_stem)
    task.options = options
    task.options["anonymization_namespace"] = settings.ANONYMIZATION_NAMESPACE
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
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return Response(
            {"status": "unavailable", "service": "数据安全平台", "database": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({
        "status": "ok",
        "service": "数据安全平台",
        "database": "ok",
        "time": timezone.now(),
    })


@api_view(["GET", "POST"])
def model_runtime(request):
    if request.method == "GET":
        result = runtime_status()
        result["active_artifact_id"] = str(ModelArtifact.objects.filter(is_active=True).values_list("id", flat=True).first() or "")
        return Response(result)
    mode = request.data.get("mode", "on_demand")
    try:
        set_runtime_mode(mode)
    except UIEProcessingError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    result = runtime_status()
    result["selected_mode"] = mode
    return Response(result)


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([LocalUploadThrottle])
def model_artifact_collection(request):
    if request.method == "GET":
        artifacts = [artifact_to_dict(item) for item in ModelArtifact.objects.all()]
        active = next((item for item in artifacts if item["is_active"]), None)
        return Response({
            "base_model": {
                "name": settings.UIE_MODEL,
                "version": "内置",
                "is_active": active is None,
            },
            "artifacts": artifacts,
            "active_artifact_id": active["id"] if active else "",
            "max_package_size_mb": settings.MODEL_PACKAGE_MAX_SIZE_MB,
            "package_format": "data-security-uie-model/v1",
        })
    try:
        artifact = import_model_package(
            request.FILES.get("file"),
            request.data.get("name", ""),
            request.data.get("version", ""),
        )
    except ModelPackageError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(artifact_to_dict(artifact), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
def model_artifact_detail(request, artifact_id):
    artifact = get_object_or_404(ModelArtifact, id=artifact_id)
    if artifact.is_active:
        return Response({"detail": "正在使用的模型不能删除，请先切换到内置模型。"}, status=status.HTTP_409_CONFLICT)
    if request.headers.get("X-Model-Delete-Confirm") != str(artifact.id):
        return Response({"detail": "删除模型包需要确认。"}, status=status.HTTP_400_BAD_REQUEST)
    artifact.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def model_artifact_activate(request, artifact_id):
    artifact = get_object_or_404(ModelArtifact, id=artifact_id)
    try:
        set_runtime_mode("on_demand")
    except UIEProcessingError:
        # The pointer remains useful after a manager/container restart.
        pass
    try:
        activate_artifact(artifact)
    except ModelPackageError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    result = artifact_to_dict(artifact)
    result["detail"] = "模型已激活，将在下一次识别时加载。"
    return Response(result)


@api_view(["POST"])
def model_base_activate(request):
    try:
        set_runtime_mode("on_demand")
    except UIEProcessingError:
        pass
    activate_artifact(None)
    return Response({
        "name": settings.UIE_MODEL,
        "is_active": True,
        "detail": "已切换到内置模型，将在下一次识别时加载。",
    })


@api_view(["GET"])
def model_artifact_export(request, artifact_id):
    artifact = get_object_or_404(ModelArtifact, id=artifact_id)
    try:
        export_file = build_export_file(artifact)
    except ModelPackageError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    safe_name = _safe_name(f"{artifact.name}-{artifact.version}.zip")
    response = FileResponse(export_file, as_attachment=True, filename=safe_name, content_type="application/zip")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


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


def _training_document_summary(document):
    annotation_count = 0
    if document.annotations_ciphertext:
        try:
            annotation_count = len(decrypt_mapping(document.annotations_ciphertext).get("entities", []))
        except ValueError:
            annotation_count = 0
    return {
        "id": str(document.id),
        "original_name": document.original_name,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "status": document.status,
        "status_label": document.get_status_display(),
        "annotation_count": annotation_count,
        "error_message": document.error_message,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def _training_document_payload(document):
    payload = _training_document_summary(document)
    if document.preview_ciphertext:
        preview_mapping = decrypt_mapping(document.preview_ciphertext)
        payload.update({
            "preview": preview_mapping.get("review_preview", []),
            "entities": _review_entities(preview_mapping),
            "alias_groups": preview_mapping.get("alias_suggestions", []),
        })
    else:
        payload.update({"preview": [], "entities": [], "alias_groups": []})
    if document.annotations_ciphertext:
        payload["annotations"] = decrypt_mapping(document.annotations_ciphertext)
    return payload


def _prepare_training_document(document):
    chunks, _ = _collect_text_chunks(document.source_file.path, document.id)
    filename_stem = Path(document.original_name).stem
    recognition_chunks = list(chunks)
    if filename_stem:
        recognition_chunks.append(filename_stem)
    searchable_text = "\n".join(recognition_chunks)
    learned = active_custom_entities()
    builder = MappingBuilder(str(document.id), DEFAULT_CATEGORIES, learned)
    for chunk in recognition_chunks:
        builder.discover(chunk)
    model_metadata = {}
    if settings.UIE_ENABLED:
        model_entities, _ = _select_model_entities(
            builder,
            predict_entities(list(dict.fromkeys(recognition_chunks)), DEFAULT_CATEGORIES, "on_demand"),
        )
        for entity in model_entities:
            if builder.register_detected(entity.get("text"), entity.get("category")):
                model_metadata[(entity.get("text"), entity.get("category"))] = {
                    "probability": round(float(entity.get("probability", 0.0)), 4),
                }
    alias_suggestions = suggest_organization_alias_groups(builder, searchable_text)
    mapping = builder.export()
    custom_keys = {(item["text"], item["category"]) for item in learned}
    mapping["review_contexts"] = _build_review_contexts(
        mapping, chunks, document.file_type, filename_stem, model_metadata, custom_keys,
    )
    mapping["review_preview"] = _build_review_preview(mapping, chunks, document.file_type, filename_stem)
    mapping["alias_suggestions"] = alias_suggestions
    document.preview_ciphertext = encrypt_mapping(mapping)
    document.status = TrainingDocument.Status.READY
    document.error_message = ""
    document.save(update_fields=["preview_ciphertext", "status", "error_message", "updated_at"])


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([LocalUploadThrottle])
def training_document_collection(request):
    if request.method == "GET":
        return Response({
            "documents": [_training_document_summary(item) for item in TrainingDocument.objects.all()[:100]],
            "labeled_count": TrainingDocument.objects.filter(status=TrainingDocument.Status.LABELED).count(),
        })
    upload = request.FILES.get("file")
    error = _validate_upload(upload)
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    original_name = _safe_name(upload.name)
    document = TrainingDocument.objects.create(
        original_name=original_name,
        file_type=Path(original_name).suffix.lower().lstrip("."),
        file_size=upload.size,
        sha256=_sha256(upload),
        source_file=upload,
    )
    try:
        _prepare_training_document(document)
    except Exception as exc:
        logger.exception("Training document pre-label failed", extra={"document_id": str(document.id)})
        document.status = TrainingDocument.Status.FAILED
        document.error_message = str(exc) if isinstance(exc, (ProcessingError, UIEProcessingError, ValueError)) else "文档预标失败，请查看后端日志。"
        document.save(update_fields=["status", "error_message", "updated_at"])
        return Response(_training_document_summary(document), status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(_training_document_payload(document), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST", "DELETE"])
def training_document_detail(request, document_id):
    document = get_object_or_404(TrainingDocument, id=document_id)
    if request.method == "DELETE":
        if request.headers.get("X-Training-Delete-Confirm") != str(document.id):
            return Response({"detail": "缺少有效的删除确认信息。"}, status=status.HTTP_400_BAD_REQUEST)
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "GET":
        try:
            return Response(_training_document_payload(document))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    if not document.preview_ciphertext:
        return Response({"detail": "该文档尚未完成机器预标。"}, status=status.HTTP_409_CONFLICT)
    mapping = decrypt_mapping(document.preview_ciphertext)
    known = {(item["text"], item["category"]) for item in _review_entities(mapping)}
    known_texts = {item[0] for item in known}
    selected = []
    for item in request.data.get("selected_entities", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        category = str(item.get("category", "custom"))
        if text in known_texts and category in {*DEFAULT_CATEGORIES, "custom"}:
            selected.append({"text": text, "category": category})
    additions = _custom_entities(request.data.get("additions", ""))
    final_entities = list({
        (item["category"], item["text"]): item for item in [*selected, *additions]
    }.values())
    if not final_entities:
        return Response({"detail": "请至少保留或补充一个有效标注。"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        for item in final_entities:
            create_or_reactivate_label(item["text"], item["category"], source="annotation")
        record_document_annotations(final_entities, document.id, mapping.get("review_preview", []))
        rejected = [
            {"text": text, "category": category}
            for text, category in known
            if (text, category) not in {(item["text"], item["category"]) for item in selected}
        ]
        if rejected:
            record_rejected_entities(rejected, document.id)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    document.annotations_ciphertext = encrypt_mapping({
        "entities": final_entities,
        "alias_groups": request.data.get("alias_groups", []),
        "saved_at": timezone.now().isoformat(),
    })
    document.status = TrainingDocument.Status.LABELED
    document.save(update_fields=["annotations_ciphertext", "status", "updated_at"])
    return Response(_training_document_payload(document))


def _training_dataset_lines():
    documents = TrainingDocument.objects.filter(
        status=TrainingDocument.Status.LABELED,
    ).iterator(chunk_size=20)
    for document in documents:
        if not document.preview_ciphertext or not document.annotations_ciphertext:
            continue
        preview = decrypt_mapping(document.preview_ciphertext).get("review_preview", [])
        entities = decrypt_mapping(document.annotations_ciphertext).get("entities", [])
        for section in preview:
            content = str(section.get("text", ""))
            if not content:
                continue
            by_category = defaultdict(list)
            for entity in entities:
                text = str(entity.get("text", "")).strip()
                category = str(entity.get("category", "custom"))
                if category not in UIE_TRAINING_PROMPT_BY_CATEGORY:
                    continue
                start_at = 0
                while text:
                    start = content.find(text, start_at)
                    if start < 0:
                        break
                    by_category[category].append({
                        "text": text, "start": start, "end": start + len(text),
                    })
                    start_at = start + len(text)
            # Include reviewed negative samples as empty result lists. These are
            # required to teach UIE when a prompt has no answer in a section.
            for category, prompt in UIE_TRAINING_PROMPT_BY_CATEGORY.items():
                yield json.dumps({
                    "content": content,
                    "prompt": prompt,
                    "result_list": by_category.get(category, []),
                }, ensure_ascii=False, separators=(",", ":")) + "\n"


@api_view(["GET"])
def training_dataset_export(request):
    response = StreamingHttpResponse(
        _training_dataset_lines(),
        content_type="application/jsonl; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="uie-training-dataset.jsonl"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([LocalUploadThrottle])
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
        logger.exception("Anonymization task failed", extra={"task_id": str(task.id)})
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
    original_to_token = mapping.get("original_to_token") or {
        text: token for token, text in mapping.get("token_to_original", {}).items()
        if token.startswith("【")
    }
    aliases = mapping.get("alias_to_canonical", {})
    suggestion_members = {
        member
        for group in mapping.get("alias_suggestions", [])
        if isinstance(group, dict) and not group.get("accepted")
        for member in group.get("members", [])[1:]
    }
    occurrence_index = defaultdict(list)
    occurrence_counts = Counter()
    for section in mapping.get("review_preview", []):
        section_text = str(section.get("text", ""))
        for span in section.get("spans", []):
            text = str(span.get("entity_text") or span.get("text", ""))
            token = str(span.get("token", ""))
            key = (token, text)
            occurrence_counts[key] += 1
            if len(occurrence_index[key]) >= 3:
                continue
            start = int(span.get("start", 0))
            end = int(span.get("end", start))
            occurrence_index[key].append({
                "prefix": re.sub(r"\s+", " ", section_text[max(0, start - 70):start]).strip(),
                "match": str(span.get("text", text)),
                "suffix": re.sub(r"\s+", " ", section_text[end:end + 70]).strip(),
                "location": section.get("location", "原文"),
            })

    entities = []
    for text, token in original_to_token.items():
        if not token.startswith("【"):
            continue
        category = categories.get(token, "custom")
        context = context_map.get(token, {})
        occurrences = occurrence_index[(token, text)]
        entities.append({
            "key": f"{token}::{text}",
            "token": token,
            "text": text,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, CATEGORY_LABELS["custom"]),
            "source": "alias" if text in suggestion_members else context.get("source", "rule"),
            "probability": context.get("probability"),
            "occurrences": occurrences or context.get("occurrences", []),
            "occurrence_count": occurrence_counts[(token, text)] or len(context.get("occurrences", [])),
            "canonical": aliases.get(text, text),
            "is_alias": text in aliases,
        })
    return sorted(entities, key=lambda item: (item["category_label"], item["token"], item["text"]))


def _review_payload(task, mapping, request, excluded_count=None):
    return {
        "task": TaskSerializer(task, context={"request": request}).data,
        "entities": _review_entities(mapping),
        "preview": mapping.get("review_preview", []),
        "alias_groups": mapping.get("alias_suggestions", []),
        "excluded_count": (
            len(mapping.get("review_exclusions", []))
            if excluded_count is None else excluded_count
        ),
    }


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
        return Response(_review_payload(task, mapping, request))

    additions = _custom_entities(request.data.get("additions", ""))
    manual_addition_count = len({(item.get("category"), item.get("text")) for item in additions})
    remove_tokens = request.data.get("remove_tokens", [])
    if not isinstance(remove_tokens, list):
        return Response({"detail": "误识别标记必须是列表。"}, status=status.HTTP_400_BAD_REQUEST)
    token_to_original = mapping.get("token_to_original", {})
    original_to_token = mapping.get("original_to_token") or {
        text: token for token, text in token_to_original.items() if token.startswith("【")
    }
    token_categories = mapping.get("token_categories", {})
    entity_rows = [
        (text, token, token_categories.get(token, "custom"))
        for text, token in original_to_token.items() if token.startswith("【")
    ]
    entity_tokens = [row[1] for row in entity_rows]
    selected_payload = request.data.get("selected_entities")
    selected_by_key = {}
    if selected_payload is not None:
        if not isinstance(selected_payload, list):
            return Response({"detail": "已选识别项必须是列表。"}, status=status.HTTP_400_BAD_REQUEST)
        for item in selected_payload:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token", ""))
            category = str(item.get("category", token_categories.get(token, "custom")))
            if token in entity_tokens and category in {*DEFAULT_CATEGORIES, "custom"}:
                text = str(item.get("text", "")).strip()
                if text:
                    selected_by_key[(token, text)] = category
                else:
                    for row_text, row_token, _ in entity_rows:
                        if row_token == token:
                            selected_by_key[(token, row_text)] = category
    else:
        removed_set = set(remove_tokens)
        selected_by_key = {
            (token, text): category
            for text, token, category in entity_rows
            if token not in removed_set
        }

    removals = []
    category_corrections = []
    rejected_candidate_count = 0
    for text, token, old_category in entity_rows:
        selected_category = selected_by_key.get((token, text))
        if selected_category is None or selected_category != old_category:
            removals.append({"text": text, "category": old_category})
        if selected_category is None:
            rejected_candidate_count += 1
        if selected_category is not None and selected_category != old_category:
            category_corrections.append({
                "text": text,
                "category": selected_category,
            })
    additions = list({
        (item["category"], item["text"]): item
        for item in [*additions, *category_corrections]
    }.values())

    requested_alias_groups = request.data.get("alias_groups", [])
    accepted_alias_groups = []
    known_groups = {
        str(group.get("id")): group
        for group in mapping.get("alias_suggestions", []) if isinstance(group, dict)
    }
    if isinstance(requested_alias_groups, list):
        selected_texts = {text for (_, text) in selected_by_key}
        for requested in requested_alias_groups:
            if not isinstance(requested, dict) or not requested.get("accepted"):
                continue
            known = known_groups.get(str(requested.get("id")))
            if not known:
                continue
            members = [str(item) for item in known.get("members", [])]
            canonical = str(requested.get("canonical") or known.get("canonical", ""))
            if canonical in members and all(member in selected_texts for member in members):
                accepted = dict(known, canonical=canonical, accepted=True)
                accepted_alias_groups.append(accepted)
                additions.extend({"text": member, "category": known.get("category", "organization")} for member in members)
    additions = list({
        (item["category"], item["text"]): item for item in additions
    }.values())

    try:
        confirmed_entities = [
            {"text": text, "category": category}
            for (token, text), category in selected_by_key.items()
            if category in {*DEFAULT_CATEGORIES, "custom"}
        ]
        save_task_custom_entities(list({
            (item["category"], item["text"]): item
            for item in [*additions, *confirmed_entities]
        }.values()))
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
        task_options = dict(task.options or {})
        review_metrics = dict(task_options.get("review_metrics") or {})
        review_metrics.update({
            "candidate_count": len(entity_rows),
            "selected_count": len(selected_by_key),
            "rejected_count": rejected_candidate_count,
            "category_corrected_count": len(category_corrections),
            "manual_added_count": manual_addition_count,
            "alias_accepted_count": len(accepted_alias_groups),
            "reviewed_at": timezone.now().isoformat(),
        })
        task_options["review_metrics"] = review_metrics
        task.options = task_options
        _process_task(
            task,
            categories,
            uie_mode,
            combined_custom,
            excluded_entities,
            await_review=False,
            accepted_alias_groups=accepted_alias_groups,
            previous_mapping=mapping,
        )
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
        logger.exception("Review reprocessing failed", extra={"task_id": str(task.id)})
        return Response({"detail": "校正后重新处理失败，请查看后端日志。"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return Response(_review_payload(
        task,
        decrypt_mapping(task.mapping_ciphertext),
        request,
        excluded_count=len(excluded_entities),
    ))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([LocalUploadThrottle])
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
        restorer = build_restorer(mapping)
        restored_upload_name = restorer(upload_name)
        output_name = _output_name(restored_upload_name, "正式版")
        output_path = Path(settings.MEDIA_ROOT) / "processing" / str(task.id) / output_name
        process_file(task.restore_input_file.path, output_path, restorer)
        if task.restored_file:
            task.restored_file.delete(save=False)
        with output_path.open("rb") as handle:
            task.restored_file.save(output_name, File(handle), save=False)
        task.status = AnonymizationTask.Status.RESTORED
        task.error_message = ""
        task.save()
        output_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.exception("Restore task failed", extra={"task_id": str(task.id)})
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
    task_rows = list(tasks.values("status", "file_type", "entity_counts", "options", "created_at"))
    status_counts = Counter(row["status"] for row in task_rows)
    file_type_counts = Counter((row["file_type"] or "unknown").upper() for row in task_rows)
    entity_counts = Counter()
    review_totals = Counter()
    duration_values = []
    confirmed_occurrences = 0
    daily_counts = Counter()
    for row in task_rows:
        daily_counts[timezone.localtime(row["created_at"]).date().isoformat()] += 1
        for label, count in (row["entity_counts"] or {}).items():
            entity_counts[label] += int(count or 0)
        options = row["options"] or {}
        metrics = options.get("review_metrics") or {}
        if "confirmed_occurrence_count" in metrics:
            confirmed_occurrences += int(metrics.get("confirmed_occurrence_count", 0) or 0)
        elif row["status"] in {AnonymizationTask.Status.COMPLETED, AnonymizationTask.Status.RESTORED}:
            confirmed_occurrences += sum(int(value or 0) for value in (row["entity_counts"] or {}).values())
        if metrics.get("reviewed_at"):
            review_totals["reviewed_tasks"] += 1
        for key in (
            "candidate_count", "candidate_occurrence_count", "selected_count", "rejected_count",
            "category_corrected_count", "manual_added_count", "alias_accepted_count",
        ):
            review_totals[key] += int(metrics.get(key, 0) or 0)
        duration = options.get("recognition_duration_ms")
        if isinstance(duration, (int, float)) and duration >= 0:
            duration_values.append(float(duration))

    total_tasks = len(task_rows)
    completed_tasks = status_counts[AnonymizationTask.Status.COMPLETED] + status_counts[AnonymizationTask.Status.RESTORED]
    candidate_total = review_totals["candidate_count"]
    selected_total = review_totals["selected_count"]
    today = timezone.localdate()
    trend = [
        {"date": (today - timedelta(days=offset)).isoformat(), "count": daily_counts[(today - timedelta(days=offset)).isoformat()]}
        for offset in range(6, -1, -1)
    ]
    training_status_counts = {
        choice: TrainingDocument.objects.filter(status=choice).count()
        for choice, _ in TrainingDocument.Status.choices
    }
    totals = {
        "tasks": total_tasks,
        "completed": completed_tasks,
        "restored": status_counts[AnonymizationTask.Status.RESTORED],
        "failed": status_counts[AnonymizationTask.Status.FAILED],
        "pending_review": status_counts[AnonymizationTask.Status.REVIEW],
        "entities": sum(entity_counts.values()),
        "entity_occurrences": confirmed_occurrences,
        "training_examples": TrainingExample.objects.count(),
        "active_labels": RecognitionLabel.objects.filter(is_active=True).count(),
        "training_documents": TrainingDocument.objects.count(),
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        "completion_rate": round(completed_tasks * 100 / total_tasks, 1) if total_tasks else 0.0,
        "status_distribution": [
            {"key": key, "label": label, "count": status_counts[key]}
            for key, label in AnonymizationTask.Status.choices
        ],
        "entity_distribution": [
            {"label": label, "count": count}
            for label, count in entity_counts.most_common()
        ],
        "file_type_distribution": [
            {"label": label, "count": count}
            for label, count in file_type_counts.most_common()
        ],
        "review_quality": {
            **review_totals,
            "candidate_acceptance_rate": round(selected_total * 100 / candidate_total, 1) if candidate_total else 0.0,
        },
        "performance": {
            "measured_tasks": len(duration_values),
            "average_recognition_seconds": round(sum(duration_values) / len(duration_values) / 1000, 1) if duration_values else 0.0,
            "maximum_recognition_seconds": round(max(duration_values) / 1000, 1) if duration_values else 0.0,
        },
        "training_status": training_status_counts,
        "seven_day_trend": trend,
    }
    return Response(totals)
