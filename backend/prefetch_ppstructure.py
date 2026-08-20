import os
import tempfile
import gc
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
    print("[本地 OCR 1/5] 加载极速文字流水线（移动端检测与识别）", flush=True)
    fast_pipeline = _build_pipeline("fast")
    print(
        f"[本地 OCR 2/5] 极速模型下载完成，本地缓存 {cache_size(cache) / 1024 / 1024:.1f} MB",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="ppstructure-check-") as directory:
        image_path = Path(directory) / "check.png"
        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).text((40, 90), "Data Anonymization OCR Check 2026", fill="black")
        image.save(image_path)
        _recognize(fast_pipeline, image_path, "fast")
        print("[本地 OCR 3/5] 极速文字流水线自检通过", flush=True)
        del fast_pipeline
        gc.collect()

        print("[本地 OCR 4/5] 加载可选版面增强流水线", flush=True)
        layout_pipeline = _build_pipeline("layout")
        _recognize(layout_pipeline, image_path, "layout")
        del layout_pipeline
        gc.collect()
    print(
        f"[本地 OCR 5/5] 两种模式均已就绪，本地缓存 {cache_size(cache) / 1024 / 1024:.1f} MB",
        flush=True,
    )


if __name__ == "__main__":
    main()
