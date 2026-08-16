import argparse
import json
import os
import sys
from pathlib import Path


PROTOCOL_PREFIX = "__PPSTRUCTURE__"
_UNUSED_CHART_MODEL = "PP-Chart2Table"


def _emit(payload):
    print(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _layout_pipeline_class():
    from paddlex.inference.pipelines.layout_parsing.pipeline_v2 import (
        _LayoutParsingPipelineV2,
    )

    return _LayoutParsingPipelineV2


def _build_pipeline():
    # Keep the import inside the worker so the Django process never retains the
    # PaddleOCR model after a scanned PDF has finished processing.
    from paddleocr import PPStructureV3

    # PaddleX 3.3.13 initializes PP-Chart2Table unconditionally even when
    # use_chart_recognition=False. Intercept only that unused model while the
    # pinned PP-StructureV3 pipeline is created, then immediately restore the
    # vendor method. This keeps the lite worker to layout + mobile OCR models.
    layout_pipeline_class = _layout_pipeline_class()
    original_create_model = layout_pipeline_class.create_model

    def create_lite_model(instance, config, *args, **kwargs):
        if isinstance(config, dict) and config.get("model_name") == _UNUSED_CHART_MODEL:
            return None
        return original_create_model(instance, config, *args, **kwargs)

    layout_pipeline_class.create_model = create_lite_model
    try:
        return PPStructureV3(
            device=os.getenv("PPSTRUCTURE_DEVICE", "cpu"),
            layout_detection_model_name=os.getenv(
                "PPSTRUCTURE_LAYOUT_MODEL", "PP-DocLayout-S"
            ),
            text_detection_model_name=os.getenv(
                "PPSTRUCTURE_TEXT_DETECTION_MODEL", "PP-OCRv5_mobile_det"
            ),
            text_recognition_model_name=os.getenv(
                "PPSTRUCTURE_TEXT_RECOGNITION_MODEL", "PP-OCRv5_mobile_rec"
            ),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_seal_recognition=False,
            use_table_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
            enable_mkldnn=False,
            cpu_threads=max(1, min(16, int(os.getenv("PPSTRUCTURE_CPU_THREADS", "8")))),
        )
    finally:
        layout_pipeline_class.create_model = original_create_model


def _result_payload(result):
    payload = getattr(result, "json", {})
    if callable(payload):
        payload = payload()
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("res")
    return nested if isinstance(nested, dict) else payload


def _extract_text(result):
    payload = _result_payload(result)
    ordered_parts = []
    for block in payload.get("parsing_res_list", []) or []:
        if not isinstance(block, dict):
            continue
        content = str(block.get("block_content", "")).strip()
        if content:
            ordered_parts.append(content)

    ordered_text = "\n".join(ordered_parts)
    overall = payload.get("overall_ocr_res") or {}
    for recognized in overall.get("rec_texts", []) or []:
        content = str(recognized).strip()
        # Text in tables or an unclassified area may be absent from the layout
        # blocks. Append only missing lines to avoid duplicating normal text.
        if content and content not in ordered_text:
            ordered_parts.append(content)
    return "\n".join(ordered_parts).strip()


def _recognize(pipeline, image_path):
    output = pipeline.predict(
        input=str(image_path),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_table_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_region_detection=False,
    )
    result = next(iter(output), None)
    return _extract_text(result) if result is not None else ""


def serve(image_paths):
    try:
        pipeline = _build_pipeline()
    except Exception as exc:
        _emit({"event": "error", "detail": f"PP-StructureV3 精简模型加载失败：{exc}"})
        return 1

    _emit({"event": "ready", "mode": "lite"})
    for index, image_path in enumerate(image_paths):
        try:
            path = Path(image_path)
            if not path.is_file():
                raise FileNotFoundError("页面图像不存在")
            text = _recognize(pipeline, path)
            _emit({"event": "result", "index": index, "text": text})
        except Exception as exc:
            _emit({"event": "error", "index": index, "detail": f"第 {index + 1} 个页面识别失败：{exc}"})
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+")
    args = parser.parse_args()
    raise SystemExit(serve(args.images))


if __name__ == "__main__":
    main()
