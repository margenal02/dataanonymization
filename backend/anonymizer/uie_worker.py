import argparse
import json
import os
import sys


PROTOCOL_PREFIX = "__UIE__"
SCHEMA_BY_CATEGORY = {
    "person": ["人名"],
    "organization": ["单位名称", "部门名称"],
    "address": ["详细地址"],
    "location": ["烟叶产区"],
    "product": ["烟草品牌或产品名称"],
}
SCHEMA_CATEGORY = {
    "人名": "person",
    "单位名称": "organization",
    "部门名称": "organization",
    "详细地址": "address",
    "烟叶产区": "location",
    "烟草品牌或产品名称": "product",
}


def _emit(payload):
    print(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _schema(categories):
    result = []
    for category in categories:
        result.extend(SCHEMA_BY_CATEGORY.get(category, []))
    return list(dict.fromkeys(result))


def _load_engine():
    from paddlenlp import Taskflow
    from paddlenlp.utils.log import logger

    logger.set_level("ERROR")
    return Taskflow(
        "information_extraction",
        schema=["人名"],
        model=os.getenv("UIE_MODEL", "uie-base"),
        device_id=-1,
        batch_size=max(1, int(os.getenv("UIE_BATCH_SIZE", "1"))),
        position_prob=float(os.getenv("UIE_POSITION_PROB", "0.45")),
        max_seq_len=max(128, int(os.getenv("UIE_MAX_SEQ_LEN", "512"))),
    )


def _predict(engine, payload):
    texts = payload.get("texts") or []
    categories = payload.get("categories") or []
    schema = _schema(categories)
    if not texts or not schema:
        return []
    entities = []
    # Query one flat schema at a time. This preserves per-category confidence
    # handling and avoids cross-label competition in tobacco-domain documents.
    for requested_schema in schema:
        engine.set_schema([requested_schema])
        raw_results = engine(texts)
        for text_index, item in enumerate(raw_results):
            if not isinstance(item, dict):
                continue
            category = SCHEMA_CATEGORY.get(requested_schema)
            for match in item.get(requested_schema, []) or []:
                value = str(match.get("text", "")).strip()
                if not value:
                    continue
                entities.append({
                    "text_index": text_index,
                    "text": value,
                    "category": category,
                    "start": int(match.get("start", -1)),
                    "end": int(match.get("end", -1)),
                    "probability": float(match.get("probability", 0.0)),
                })
    return entities


def serve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        engine = _load_engine()
    except Exception as exc:
        _emit({"event": "error", "detail": f"UIE-base 模型加载失败：{exc}"})
        return 1
    _emit({"event": "ready", "model": os.getenv("UIE_MODEL", "uie-base")})
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            _emit({"event": "result", "entities": _predict(engine, payload)})
        except Exception as exc:
            _emit({"event": "error", "detail": f"UIE-base 识别失败：{exc}"})
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if not args.serve:
        parser.error("uie_worker must be started with --serve")
    raise SystemExit(serve())


if __name__ == "__main__":
    main()
