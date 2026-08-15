import hashlib
import hmac

from django.conf import settings
from django.db import transaction

from .crypto import decrypt_mapping, encrypt_mapping
from .models import RecognitionLabel, TrainingExample


VALID_CATEGORIES = {choice[0] for choice in RecognitionLabel.CATEGORY_CHOICES}


def normalize_label_text(value):
    text = " ".join(str(value or "").strip().split())
    if len(text) < 2:
        raise ValueError("识别标签至少需要 2 个字符。")
    if len(text) > 200:
        raise ValueError("识别标签不能超过 200 个字符。")
    if "【" in text or "】" in text or "ANON_" in text:
        raise ValueError("识别标签不能包含系统匿名标记。")
    return text


def validate_category(value):
    category = str(value or "custom").strip()
    if category not in VALID_CATEGORIES:
        raise ValueError("无效的识别标签类型。")
    return category


def _fingerprint(text, category):
    key = hashlib.sha256(settings.MAPPING_ENCRYPTION_KEY.encode("utf-8")).digest()
    return hmac.new(key, f"{category}\0{text}".encode("utf-8"), hashlib.sha256).hexdigest()


def _encrypt_label(text):
    return encrypt_mapping({"text": text})


def decrypt_label(label):
    return str(decrypt_mapping(label.text_ciphertext).get("text", ""))


def label_to_dict(label):
    return {
        "id": str(label.id),
        "text": decrypt_label(label),
        "category": label.category,
        "category_label": label.get_category_display(),
        "created_at": label.created_at,
        "updated_at": label.updated_at,
    }


def _record_example(label, action, before=None, after=None, source="web"):
    TrainingExample.objects.create(
        label=label,
        action=action,
        payload_ciphertext=encrypt_mapping({
            "before": before,
            "after": after,
            "source": source,
        }),
    )


@transaction.atomic
def create_or_reactivate_label(text, category, source="web"):
    text = normalize_label_text(text)
    category = validate_category(category)
    fingerprint = _fingerprint(text, category)
    label, created = RecognitionLabel.objects.get_or_create(
        category=category,
        fingerprint=fingerprint,
        defaults={"text_ciphertext": _encrypt_label(text), "is_active": True},
    )
    changed = created or not label.is_active
    if not created and not label.is_active:
        label.text_ciphertext = _encrypt_label(text)
        label.is_active = True
        label.save(update_fields=["text_ciphertext", "is_active", "updated_at"])
    if changed:
        _record_example(label, "task_custom" if source == "task_custom" else "created", after={
            "text": text,
            "category": category,
        }, source=source)
    return label, changed


@transaction.atomic
def update_label(label, text, category):
    before_text = decrypt_label(label)
    before_category = label.category
    text = normalize_label_text(text)
    category = validate_category(category)
    fingerprint = _fingerprint(text, category)
    duplicate = RecognitionLabel.objects.filter(category=category, fingerprint=fingerprint).exclude(id=label.id).first()
    if duplicate:
        if not duplicate.is_active:
            duplicate.is_active = True
            duplicate.save(update_fields=["is_active", "updated_at"])
        label.is_active = False
        label.save(update_fields=["is_active", "updated_at"])
        target = duplicate
    else:
        label.category = category
        label.fingerprint = fingerprint
        label.text_ciphertext = _encrypt_label(text)
        label.is_active = True
        label.save(update_fields=["category", "fingerprint", "text_ciphertext", "is_active", "updated_at"])
        target = label
    _record_example(target, "updated", before={"text": before_text, "category": before_category}, after={
        "text": text,
        "category": category,
    })
    return target


@transaction.atomic
def deactivate_label(label):
    if not label.is_active:
        return
    text = decrypt_label(label)
    label.is_active = False
    label.save(update_fields=["is_active", "updated_at"])
    _record_example(label, "deleted", before={"text": text, "category": label.category})


def active_custom_entities():
    entities = []
    for label in RecognitionLabel.objects.filter(is_active=True):
        try:
            text = decrypt_label(label)
        except ValueError:
            continue
        if text:
            entities.append({"text": text, "category": label.category})
    return entities


def save_task_custom_entities(entities):
    for item in entities:
        create_or_reactivate_label(item.get("text"), item.get("category", "custom"), source="task_custom")


def record_rejected_entities(entities, task_id):
    for item in entities:
        text = normalize_label_text(item.get("text"))
        category = validate_category(item.get("category", "custom"))
        TrainingExample.objects.create(
            action="rejected",
            payload_ciphertext=encrypt_mapping({
                "before": {"text": text, "category": category},
                "after": None,
                "source": "task_review",
                "task_id": str(task_id),
            }),
        )
