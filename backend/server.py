from __future__ import annotations

import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from mlkem_service import PARAMETERS, get_mlkem, run_known_answer_test, run_timing_detection
from formal_timing import run_formal_timing


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class Handler(SimpleHTTPRequestHandler):
    server_version = "MLKEMPlatform/0.1"

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8 * 1024 * 1024:
            raise ValueError("请求数据过大")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/info":
            self._json(200, {
                "name": "ML-KEM时间特性检测与防护平台",
                "version": "0.1.0",
                "engine": "mlkem-native",
                "parameter_sets": {
                    level: {
                        "public_key_bytes": p.public_key,
                        "secret_key_bytes": p.secret_key,
                        "ciphertext_bytes": p.ciphertext,
                        "shared_secret_bytes": p.shared_secret,
                    }
                    for level, p in PARAMETERS.items()
                },
            })
            return

        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (FRONTEND / relative).resolve()
        if FRONTEND.resolve() not in target.parents and target != FRONTEND.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            body = self._body()
            level = str(body.get("level", "768"))
            engine = get_mlkem(level)
            if path == "/api/keygen":
                result = engine.keygen()
            elif path == "/api/encaps":
                result = engine.encaps(str(body.get("public_key", "")))
            elif path == "/api/decaps":
                result = engine.decaps(str(body.get("ciphertext", "")), str(body.get("secret_key", "")))
            elif path == "/api/demo":
                result = engine.demo()
            elif path == "/api/selftest":
                result = engine.selftest(int(body.get("iterations", 20)))
            elif path == "/api/vector-test":
                result = run_known_answer_test()
            elif path == "/api/timing-detect":
                result = run_timing_detection(int(body.get("cpu", 0)), int(body.get("timeout_seconds", 600)))
            elif path == "/api/formal-timing":
                result = run_formal_timing(level, int(body.get("pairs", 10000)), int(body.get("cpu", 0)))
            else:
                self._json(404, {"ok": False, "error": "接口不存在"})
                return
            self._json(200, {"ok": True, "result": result})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()


def main() -> None:
    host = os.environ.get("MLKEM_HOST", "127.0.0.1")
    port = int(os.environ.get("MLKEM_PORT", "8000"))
    for level in PARAMETERS:
        get_mlkem(level)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ML-KEM platform is running at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

