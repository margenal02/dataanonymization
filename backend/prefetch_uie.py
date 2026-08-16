import os
import threading
from pathlib import Path


def cache_size(path):
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def report_cache_growth(path, stop_event):
    last_size = -1
    while not stop_event.wait(2):
        current_size = cache_size(path)
        if current_size != last_size:
            print(
                f"[UIE 模型 2/3] 正在下载或转换，本地缓存 {current_size / 1024 / 1024:.1f} MB",
                flush=True,
            )
            last_size = current_size


def main():
    print("[UIE 模型 1/3] 正在加载 PaddleNLP 运行组件", flush=True)
    from paddlenlp import Taskflow
    from paddlenlp.utils.log import logger

    logger.set_level("ERROR")
    model_cache = Path(os.getenv("PPNLP_HOME", "/opt/paddlenlp"))
    stop_event = threading.Event()
    monitor = threading.Thread(target=report_cache_growth, args=(model_cache, stop_event), daemon=True)
    monitor.start()
    try:
        engine = Taskflow(
            "information_extraction",
            schema=["人名"],
            model=os.getenv("UIE_MODEL", "uie-base"),
            device_id=-1,
            batch_size=1,
            position_prob=0.45,
            max_seq_len=512,
        )
    finally:
        stop_event.set()
        monitor.join(timeout=3)
    print(f"[UIE 模型 2/3] 下载与转换完成，缓存 {cache_size(model_cache) / 1024 / 1024:.1f} MB", flush=True)
    print("[UIE 模型 3/3] 执行中文人名识别自检", flush=True)
    result = engine("联系人张三，单位中国烟草总公司。")
    if not result or not result[0].get("人名"):
        raise RuntimeError("UIE-base 模型自检没有返回结果。")
    print("[UIE 模型 3/3] 自检通过，模型已写入后端镜像", flush=True)


if __name__ == "__main__":
    main()
