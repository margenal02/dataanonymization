def ensure_aistudio_download_compatibility():
    """Keep PaddleNLP beta4 importable with the newer PaddleX SDK stack.

    PaddleNLP 3.0.0b4 imports ``aistudio_sdk.hub.download`` eagerly, while
    PaddleX 3.3.13 requires aistudio-sdk >= 0.3.5 where that legacy download
    API no longer exists. UIE-base uses its own public BOS resource URLs, so a
    guarded placeholder is sufficient and fails explicitly if another caller
    ever tries the removed AIStudio code path.
    """
    from aistudio_sdk import hub

    if hasattr(hub, "download"):
        return False

    def unavailable_aistudio_download(*args, **kwargs):
        raise RuntimeError(
            "当前 aistudio-sdk 已移除旧版 download API；本地 UIE-base 不使用该下载通道。"
        )

    hub.download = unavailable_aistudio_download
    return True
