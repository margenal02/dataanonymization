import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class UIEProcessingError(RuntimeError):
    pass


def _manager_url(path):
    parsed = urllib.parse.urlsplit(settings.UIE_MANAGER_URL)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise UIEProcessingError("UIE-micro 管理地址必须是本机 HTTP 回环地址。")
    port = parsed.port or 80
    return f"http://127.0.0.1:{port}{path}"


def _request(path, payload=None, timeout=10):
    url = _manager_url(path)
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="GET" if payload is None else "POST",
    )
    try:
        # _manager_url restricts the destination to loopback HTTP.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        raise UIEProcessingError(detail or f"UIE-micro 服务返回错误 {exc.code}。") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UIEProcessingError("UIE-micro 本地识别服务不可用，请查看后端日志。") from exc


def predict_entities(texts, categories, mode):
    if not settings.UIE_ENABLED:
        return []
    if mode not in {"on_demand", "resident"}:
        raise UIEProcessingError("无效的 UIE 运行模式。")
    supported = [item for item in categories if item in {"person", "organization", "address", "location", "product"}]
    if not supported or not texts:
        return []
    return _request("/predict", {
        "mode": mode,
        "texts": texts,
        "categories": supported,
    }, timeout=settings.UIE_REQUEST_TIMEOUT_SECONDS).get("entities", [])


def runtime_status():
    if not settings.UIE_ENABLED:
        return {"enabled": False, "available": False, "model": settings.UIE_MODEL, "resident_loaded": False}
    try:
        result = _request("/status", timeout=3)
        result["enabled"] = True
        return result
    except UIEProcessingError as exc:
        return {
            "enabled": True,
            "available": False,
            "model": settings.UIE_MODEL,
            "resident_loaded": False,
            "detail": str(exc),
        }


def set_runtime_mode(mode):
    if not settings.UIE_ENABLED:
        raise UIEProcessingError("当前部署未启用 UIE-micro。")
    if mode == "resident":
        return _request("/warmup", {}, timeout=settings.UIE_START_TIMEOUT_SECONDS)
    if mode == "on_demand":
        return _request("/unload", {}, timeout=30)
    raise UIEProcessingError("无效的 UIE 运行模式。")
