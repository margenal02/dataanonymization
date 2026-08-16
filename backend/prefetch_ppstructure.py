import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from anonymizer.ppstructure_worker import _build_pipeline, _recognize


def cache_size(path):
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def main():
    cache = Path(os.getenv("PADDLE_PDX_CACHE_HOME", "/opt/paddlex"))
    print("[PP-StructureV3 1/3] 加载精简流水线（版面、文字检测、文字识别）", flush=True)
    pipeline = _build_pipeline()
    print(
        f"[PP-StructureV3 2/3] 模型下载完成，本地缓存 {cache_size(cache) / 1024 / 1024:.1f} MB",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="ppstructure-check-") as directory:
        image_path = Path(directory) / "check.png"
        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).text((40, 90), "Data Anonymization OCR Check 2026", fill="black")
        image.save(image_path)
        _recognize(pipeline, image_path)
    print("[PP-StructureV3 3/3] 精简流水线自检通过，模型已写入后端镜像", flush=True)


if __name__ == "__main__":
    main()
