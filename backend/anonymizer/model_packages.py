import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ModelArtifact


PACKAGE_FORMAT = "data-security-uie-model"
PACKAGE_FORMAT_VERSION = 1
MAX_FILES = 5000
MAX_COMPRESSION_RATIO = 250
WEIGHT_SUFFIXES = {".pdparams", ".pdiparams"}
CONFIG_NAMES = {"model_config.json", "config.json", "taskflow_config.json"}
TOKENIZER_NAMES = {"vocab.txt", "tokenizer.json", "sentencepiece.bpe.model", "spiece.model"}
BLOCKED_SUFFIXES = {".py", ".pyc", ".pyd", ".so", ".dll", ".exe", ".bat", ".cmd", ".ps1", ".sh"}
ALLOWED_BASE_MODELS = {"uie-base"}


class ModelPackageError(ValueError):
    pass


def model_storage_root():
    root = (Path(settings.MEDIA_ROOT) / "model-artifacts").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_artifact_path(artifact):
    root = model_storage_root()
    target = (root / artifact.storage_folder).resolve()
    if root not in target.parents:
        raise ModelPackageError("模型存储路径无效。")
    return target


def active_pointer_path():
    return model_storage_root() / "active.json"


def _clean_label(value, fallback, max_length):
    value = re.sub(r"[\x00-\x1f<>:\\/*?\"|]", "_", str(value or "")).strip(" ._")
    return (value or fallback)[:max_length]


def _safe_members(archive):
    members = [item for item in archive.infolist() if not item.is_dir()]
    if not members:
        raise ModelPackageError("模型压缩包为空。")
    if len(members) > MAX_FILES:
        raise ModelPackageError(f"模型压缩包文件数超过 {MAX_FILES} 个。")
    max_uncompressed = settings.MODEL_PACKAGE_MAX_SIZE_MB * 1024 * 1024
    total_uncompressed = 0
    result = []
    seen_paths = set()
    for item in members:
        normalized = item.filename.replace("\\", "/")
        if "\x00" in normalized or any(":" in part for part in normalized.split("/")):
            raise ModelPackageError("模型压缩包包含非法文件名。")
        if item.flag_bits & 0x1:
            raise ModelPackageError("模型压缩包不能包含加密文件。")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ModelPackageError("模型压缩包包含不安全路径。")
        path_key = path.as_posix().casefold()
        if path_key in seen_paths:
            raise ModelPackageError("模型压缩包包含重复路径。")
        seen_paths.add(path_key)
        # Unix symlink bits in the external attributes are not accepted.
        if ((item.external_attr >> 16) & 0o170000) == 0o120000:
            raise ModelPackageError("模型压缩包不能包含符号链接。")
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            raise ModelPackageError(f"模型包不能包含可执行文件：{path.name}")
        total_uncompressed += item.file_size
        if total_uncompressed > max_uncompressed:
            raise ModelPackageError(f"模型解压后不能超过 {settings.MODEL_PACKAGE_MAX_SIZE_MB} MB。")
        if item.file_size > 10 * 1024 * 1024 and item.compress_size > 0:
            if item.file_size / item.compress_size > MAX_COMPRESSION_RATIO:
                raise ModelPackageError("模型压缩包的压缩比异常，已拒绝解压。")
        result.append((item, path))
    return result


def _strip_common_root(paths):
    first_parts = {path.parts[0] for path in paths if path.parts}
    if len(first_parts) == 1 and all(len(path.parts) > 1 for path in paths):
        return [PurePosixPath(*path.parts[1:]) for path in paths]
    return paths


def _validate_checkpoint(folder):
    files = [path for path in folder.iterdir() if path.is_file()]
    relative = [path.relative_to(folder).as_posix() for path in files]
    names = {path.name.lower() for path in files}
    has_weights = any(path.suffix.lower() in WEIGHT_SUFFIXES for path in files)
    if not has_weights:
        raise ModelPackageError("未找到 UIE 权重文件（.pdparams 或 .pdiparams）。")
    if not (names & CONFIG_NAMES):
        raise ModelPackageError("未找到 UIE 模型配置文件（model_config.json 或 config.json）。")
    if not (names & TOKENIZER_NAMES):
        raise ModelPackageError("未找到分词器词表（vocab.txt、tokenizer.json 或 SentencePiece 模型）。")
    return relative


def _validate_artifact_integrity(artifact):
    folder = model_artifact_path(artifact)
    _validate_checkpoint(folder)
    expected = (artifact.file_manifest or {}).get("files", {})
    if not expected:
        raise ModelPackageError("模型缺少完整性清单，请重新导入。")
    for relative, metadata in expected.items():
        path = (folder / relative).resolve()
        if folder not in path.parents or not path.is_file():
            raise ModelPackageError(f"模型文件缺失：{relative}")
        if _hash_file(path) != metadata.get("sha256"):
            raise ModelPackageError(f"模型文件完整性校验失败：{relative}")
    return folder


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_for(folder, name, version, base_model):
    files = {}
    total = 0
    for path in sorted(item for item in folder.rglob("*") if item.is_file() and item.name != "manifest.json"):
        relative = path.relative_to(folder).as_posix()
        size = path.stat().st_size
        total += size
        files[relative] = {"sha256": _hash_file(path), "size": size}
    return {
        "format": PACKAGE_FORMAT,
        "format_version": PACKAGE_FORMAT_VERSION,
        "name": name,
        "version": version,
        "base_model": base_model,
        "created_at": timezone.now().isoformat(),
        "files": files,
        "privacy": "仅包含模型权重和运行配置，不包含原始文档、匿名映射、标签库或密钥。",
        "total_size": total,
    }


def import_model_package(upload, requested_name="", requested_version=""):
    if not upload or not str(upload.name).lower().endswith(".zip"):
        raise ModelPackageError("请选择 ZIP 格式的 UIE 模型包。")
    max_bytes = settings.MODEL_PACKAGE_MAX_SIZE_MB * 1024 * 1024
    if upload.size > max_bytes:
        raise ModelPackageError(f"模型包不能超过 {settings.MODEL_PACKAGE_MAX_SIZE_MB} MB。")

    package_digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(suffix=".zip") as source:
        for chunk in upload.chunks():
            package_digest.update(chunk)
            source.write(chunk)
        source.flush()
        source.seek(0)
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile as exc:
            raise ModelPackageError("模型包不是有效的 ZIP 文件。") from exc
        with archive, tempfile.TemporaryDirectory() as temp_folder:
            members = _safe_members(archive)
            source_paths = [path for _, path in members]
            target_paths = _strip_common_root(source_paths)
            extract_root = Path(temp_folder) / "checkpoint"
            extract_root.mkdir()
            for (item, _), relative in zip(members, target_paths):
                target = (extract_root / Path(*relative.parts)).resolve()
                if extract_root.resolve() not in target.parents:
                    raise ModelPackageError("模型压缩包包含越界路径。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source_handle, target.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)

            _validate_checkpoint(extract_root)
            imported_manifest = {}
            manifest_path = extract_root / "manifest.json"
            if manifest_path.exists():
                try:
                    imported_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ModelPackageError("manifest.json 不是有效的 UTF-8 JSON。") from exc
                if not isinstance(imported_manifest, dict):
                    raise ModelPackageError("manifest.json 顶层必须是 JSON 对象。")
                if imported_manifest.get("format") not in {None, PACKAGE_FORMAT}:
                    raise ModelPackageError("模型包格式标识不受支持。")
                if imported_manifest.get("format_version") not in {None, PACKAGE_FORMAT_VERSION}:
                    raise ModelPackageError("模型包格式版本不受支持。")

            name = _clean_label(requested_name or imported_manifest.get("name") or Path(upload.name).stem, "本地 UIE 模型", 120)
            version = _clean_label(requested_version or imported_manifest.get("version"), "1.0.0", 64)
            base_model = _clean_label(imported_manifest.get("base_model"), "uie-base", 80)
            if base_model not in ALLOWED_BASE_MODELS:
                raise ModelPackageError("当前部署只接受基于 uie-base 微调的模型包。")
            artifact_id = __import__("uuid").uuid4()
            folder_name = str(artifact_id)
            destination = model_storage_root() / folder_name
            manifest = _manifest_for(extract_root, name, version, base_model)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                shutil.move(str(extract_root), str(destination))
                artifact = ModelArtifact.objects.create(
                    id=artifact_id,
                    name=name,
                    version=version,
                    base_model=base_model,
                    storage_folder=folder_name,
                    package_sha256=package_digest.hexdigest(),
                    package_size=manifest["total_size"],
                    file_manifest=manifest,
                )
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
    return artifact


def activate_artifact(artifact=None):
    pointer = active_pointer_path()
    old_pointer = pointer.read_bytes() if pointer.exists() else None
    try:
        with transaction.atomic():
            ModelArtifact.objects.filter(is_active=True).update(is_active=False)
            if artifact is None:
                pointer.unlink(missing_ok=True)
                return
            target = _validate_artifact_integrity(artifact)
            payload = {
                "artifact_id": str(artifact.id),
                "name": artifact.name,
                "version": artifact.version,
                "base_model": artifact.base_model,
                "task_path": str(target),
            }
            temp_pointer = pointer.with_suffix(".tmp")
            temp_pointer.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_pointer, pointer)
            artifact.is_active = True
            artifact.save(update_fields=["is_active", "updated_at"])
    except Exception:
        if old_pointer is None:
            pointer.unlink(missing_ok=True)
        else:
            pointer.write_bytes(old_pointer)
        raise


def artifact_to_dict(artifact):
    return {
        "id": str(artifact.id),
        "name": artifact.name,
        "version": artifact.version,
        "base_model": artifact.base_model,
        "package_sha256": artifact.package_sha256,
        "package_size": artifact.package_size,
        "file_count": len((artifact.file_manifest or {}).get("files", {})),
        "is_active": artifact.is_active,
        "created_at": artifact.created_at,
        "updated_at": artifact.updated_at,
    }


def build_export_file(artifact):
    folder = _validate_artifact_integrity(artifact)
    output = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, suffix=".zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(folder / "manifest.json", "manifest.json")
        for relative in sorted((artifact.file_manifest or {}).get("files", {})):
            archive.write(folder / relative, relative)
    output.seek(0)
    return output
