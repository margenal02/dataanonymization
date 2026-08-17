import json
import os
import queue
import signal
# Only a fixed local Python module is launched without a shell.
import subprocess  # nosec B404
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .uie_worker import PROTOCOL_PREFIX


MODEL_LOCK = threading.Lock()
RESIDENT_WORKER = None
MODEL_NAME = os.getenv("UIE_MODEL", "uie-base")
START_TIMEOUT = int(os.getenv("UIE_START_TIMEOUT_SECONDS", "600"))
REQUEST_TIMEOUT = int(os.getenv("UIE_REQUEST_TIMEOUT_SECONDS", "1800"))


def _configured_model_name():
    pointer = os.getenv("UIE_MODEL_POINTER", "")
    if not pointer:
        return MODEL_NAME
    try:
        with open(pointer, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return f"{payload.get('name') or '本地模型'} {payload.get('version') or ''}".strip()
    except (OSError, ValueError, json.JSONDecodeError):
        return MODEL_NAME


class ModelWorker:
    def __init__(self):
        worker_environment = os.environ.copy()
        worker_environment["PYTHONIOENCODING"] = "utf-8"
        # Command and arguments are constants rather than request data.
        self.process = subprocess.Popen(  # nosec B603
            [sys.executable, "-m", "anonymizer.uie_worker", "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=0,
            env=worker_environment,
        )
        self.messages = queue.Queue()
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()
        ready = self._next_message(START_TIMEOUT)
        if ready.get("event") != "ready":
            self.close()
            raise RuntimeError(ready.get("detail", "UIE-base 模型未能完成初始化。"))
        self.model_name = ready.get("model", MODEL_NAME)

    def _read_stdout(self):
        try:
            for raw_line in self.process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith(PROTOCOL_PREFIX):
                    continue
                try:
                    self.messages.put(json.loads(line[len(PROTOCOL_PREFIX):]))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put({"event": "error", "detail": "UIE-base 模型进程已退出。"})

    def _next_message(self, timeout):
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("UIE-base 模型响应超时。") from exc

    def predict(self, payload):
        if self.process.poll() is not None:
            raise RuntimeError("UIE-base 模型进程未运行。")
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.process.stdin.write(message.encode("utf-8"))
        self.process.stdin.flush()
        response = self._next_message(REQUEST_TIMEOUT)
        if response.get("event") == "error":
            raise RuntimeError(response.get("detail", "UIE-base 识别失败。"))
        if response.get("event") != "result":
            raise RuntimeError("UIE-base 返回了无法识别的响应。")
        return response.get("entities", [])

    def close(self):
        if not getattr(self, "process", None) or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def _ensure_resident():
    global RESIDENT_WORKER
    if RESIDENT_WORKER is None or RESIDENT_WORKER.process.poll() is not None:
        if RESIDENT_WORKER is not None:
            RESIDENT_WORKER.close()
        RESIDENT_WORKER = ModelWorker()
    return RESIDENT_WORKER


def _unload_resident():
    global RESIDENT_WORKER
    if RESIDENT_WORKER is not None:
        RESIDENT_WORKER.close()
        RESIDENT_WORKER = None


class Handler(BaseHTTPRequestHandler):
    server_version = "DataAnonymizationUIE/1.0"

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 8 * 1024 * 1024:
            raise ValueError("UIE 请求大小无效。")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path != "/status":
            self._json(404, {"detail": "not found"})
            return
        worker = RESIDENT_WORKER
        loaded = bool(worker is not None and worker.process.poll() is None)
        self._json(200, {
            "available": True,
            "model": worker.model_name if loaded else _configured_model_name(),
            "resident_loaded": loaded,
        })

    def do_POST(self):
        try:
            if self.path == "/predict":
                payload = self._payload()
                mode = payload.get("mode", "on_demand")
                if mode not in {"on_demand", "resident"}:
                    raise ValueError("无效的 UIE 运行模式。")
                with MODEL_LOCK:
                    if mode == "resident":
                        entities = _ensure_resident().predict(payload)
                    else:
                        _unload_resident()
                        worker = ModelWorker()
                        try:
                            entities = worker.predict(payload)
                        finally:
                            worker.close()
                self._json(200, {"entities": entities, "mode": mode, "model": _configured_model_name()})
                return
            if self.path == "/warmup":
                with MODEL_LOCK:
                    worker = _ensure_resident()
                self._json(200, {"resident_loaded": True, "model": worker.model_name})
                return
            if self.path == "/unload":
                with MODEL_LOCK:
                    _unload_resident()
                self._json(200, {"resident_loaded": False, "model": _configured_model_name()})
                return
            self._json(404, {"detail": "not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"detail": str(exc)})
        except Exception as exc:
            _unload_resident()
            self._json(503, {"detail": str(exc)})

    def log_message(self, fmt, *args):
        return


def main():
    host = os.getenv("UIE_MANAGER_HOST", "127.0.0.1")
    port = int(os.getenv("UIE_MANAGER_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)

    def stop(*_):
        _unload_resident()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()
