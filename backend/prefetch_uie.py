import os


def main():
    from paddlenlp import Taskflow
    from paddlenlp.utils.log import logger

    logger.set_level("ERROR")
    print("预下载并初始化 UIE-micro 中文信息抽取模型……", flush=True)
    engine = Taskflow(
        "information_extraction",
        schema=["人名"],
        model=os.getenv("UIE_MODEL", "uie-micro"),
        device_id=-1,
        batch_size=1,
        position_prob=0.45,
        max_seq_len=512,
    )
    result = engine("联系人张三，单位中国烟草总公司。")
    if not result or not result[0].get("人名"):
        raise RuntimeError("UIE-micro 模型自检没有返回结果。")
    print("UIE-micro 模型已写入本地镜像缓存。", flush=True)


if __name__ == "__main__":
    main()
