from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from gentrace.collector import ComfyApi
from gentrace.config import confined_path, discover_config


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/jobs/job-1"):
            payload = {"id": "job-1", "status": "completed", "workflow": {"prompt": {}}}
        elif self.path.startswith("/api/jobs"):
            payload = {"jobs": [{"id": "job-1", "status": "completed"}], "pagination": {}}
        elif self.path == "/queue":
            payload = {"queue_running": [[1, "job-1", {"x": {}}, {}, []]], "queue_pending": []}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format, *_args):
        pass


class ApiConfigTests(unittest.TestCase):
    def test_generated_path_is_confined_to_export_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "exports"
            root.mkdir()
            self.assertEqual(
                confined_path(root, root / "jobs.csv"),
                (root / "jobs.csv").resolve(),
            )
            with self.assertRaises(ValueError):
                confined_path(root, root.parent / "outside.csv")

    def test_http_api_client(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = ComfyApi(f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(api.jobs()[0]["id"], "job-1")
            self.assertEqual(api.job("job-1")["status"], "completed")
            self.assertIn("job-1", api.queue_prompts())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_stability_matrix_settings_are_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "Data"
            data.mkdir()
            settings = {
                "ActiveInstalledPackage": "id-1",
                "InstalledPackages": [{
                    "Id": "id-1", "PackageName": "ComfyUI", "LibraryPath": "Packages\\ComfyUI",
                    "LaunchArgs": [
                        {"Name": "--listen", "OptionValue": ""},
                        {"Name": "--port", "OptionValue": ""},
                    ],
                }],
                "PreferredGpu": {"Index": 0},
            }
            (data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            config = discover_config(root, root / "GenTrace")
            self.assertEqual(config.api_base, "http://127.0.0.1:8188")
            self.assertEqual(config.comfy_root, data / "Packages" / "ComfyUI")


if __name__ == "__main__":
    unittest.main()
