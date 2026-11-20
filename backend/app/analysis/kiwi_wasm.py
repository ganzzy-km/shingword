"""Local Kiwi CoNg worker for environments that cannot load the Python extension."""
from __future__ import annotations

import atexit
import json
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue


@dataclass(frozen=True)
class Token:
    form: str
    tag: str
    start: int
    len: int


class KiwiWasm:
    def __init__(self):
        from kiwipiepy_model import get_model_path

        self._model_path = get_model_path()
        self._process = None
        self._lock = threading.Lock()
        self._start()
        atexit.register(self._stop)

    def _start(self):
        self._responses = Queue()
        self._process = subprocess.Popen(
            ["node", str(Path(__file__).with_name("kiwi_worker.mjs")), self._model_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(
            target=self._read_responses,
            args=(self._process.stdout, self._responses),
            daemon=True,
        ).start()
        try:
            self.version = self._receive()["version"]
        except Exception:
            self._stop()
            raise

    @staticmethod
    def _read_responses(stdout, responses):
        try:
            with stdout:
                for line in stdout:
                    responses.put(line)
        finally:
            responses.put(None)

    def _receive(self):
        try:
            line = self._responses.get(timeout=60)
        except Empty as exc:
            raise TimeoutError("Kiwi worker timed out") from exc
        if line is None:
            raise RuntimeError("Kiwi worker exited")
        return json.loads(line)

    def _stop(self):
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finally:
            with suppress(BrokenPipeError):
                process.stdin.close()

    def analyze(self, text, *, top_n):
        with self._lock:
            if self._process is None:
                self._start()
            try:
                self._process.stdin.write(json.dumps([text, top_n], ensure_ascii=True) + "\n")
                self._process.stdin.flush()
                response = self._receive()
            except (OSError, RuntimeError, ValueError):
                self._stop()
                raise
        if "error" in response:
            raise RuntimeError("Kiwi worker could not analyze the text")
        return [([Token(*token) for token in tokens], score) for tokens, score in response["candidates"]]
