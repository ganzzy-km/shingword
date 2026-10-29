"""Coordinator child lifecycle: fake subprocesses only, no model inference."""
import json

import pytest

from test_ocr_api import setup
from v2_fixture import v2app
from app.extensions import db
from app.models import OcrRun
from app.services import ocr_jobs as jobs


class MonitorFailure(RuntimeError):
    pass


def worker_fixture(setup, monkeypatch, mode):
    app, client, headers, owner, did, jid, document, _ = setup
    observed = {"closed": 0, "terminated": 0, "waited": [], "killed": 0}
    clock = {"now": 0}

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            observed["terminated"] += 1
            if mode == "cleanup_failures":
                raise OSError("SYNTHETIC_TERMINATE_ERROR")
            self.returncode = 1

        def wait(self, timeout=None):
            observed["waited"].append(timeout)
            if mode == "cleanup_failures" and observed["killed"] == 0:
                raise jobs.subprocess.TimeoutExpired("synthetic-worker", timeout)
            self.returncode = self.returncode or 0
            return self.returncode

        def kill(self):
            observed["killed"] += 1
            self.returncode = 1

    child = Child()

    def launch(argv, **kwargs):
        response = argv[argv.index("--response") + 1]
        with open(response, "w", encoding="utf-8") as out:
            json.dump({"status": "REVIEW_READY", "pageFiles": [], "modelTimings": []}, out)
        return child

    def close():
        observed["closed"] += 1
        if mode == "cleanup_failures":
            raise OSError("SYNTHETIC_CLOSE_ERROR")
    close.memory = lambda: 9 * 1024 ** 3 if mode == "memory" else 0
    close.cpu_seconds = lambda: 0

    def attach(*_):
        if mode == "job_attach_failure":
            raise MonitorFailure("SYNTHETIC_ATTACH_FAILURE")
        return close

    def sleep(_):
        if mode in {"monitor_failure", "cleanup_failures"}:
            raise MonitorFailure("SYNTHETIC_MONITOR_FAILURE")
        if mode == "cancel":
            db.session.get(OcrRun, jid).status = "CANCELLED"
            db.session.commit()
        elif mode == "timeout":
            clock["now"] = 2000
        elif mode == "bad_progress":
            _, record = jobs.row(jid)
            jobs.local_file(record.value["prefix"] + "-progress.json").write_text("{", encoding="utf-8")
        elif mode != "memory":
            child.returncode = 0

    monkeypatch.setattr(jobs.subprocess, "Popen", launch)
    monkeypatch.setattr(jobs, "process_job", attach)
    monkeypatch.setattr(jobs.time, "sleep", sleep)
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["now"])
    return app, jid, child, observed


@pytest.mark.parametrize("mode", ["monitor_failure", "cleanup_failures", "job_attach_failure", "bad_progress"])
def test_monitor_or_attach_failure_always_reaps_and_preserves_original_error(setup, monkeypatch, mode):
    app, jid, child, observed = worker_fixture(setup, monkeypatch, mode)
    expected = json.JSONDecodeError if mode == "bad_progress" else MonitorFailure
    with pytest.raises(expected) as error:
        jobs.execute(app, jid)
    if mode != "bad_progress":
        assert str(error.value) == ("SYNTHETIC_ATTACH_FAILURE" if mode == "job_attach_failure" else "SYNTHETIC_MONITOR_FAILURE")
    assert observed["terminated"] == 1
    assert observed["waited"] and all(isinstance(t, (int, float)) and 0 < t <= 10 for t in observed["waited"])
    assert child.poll() is not None
    assert observed["closed"] == (0 if mode == "job_attach_failure" else 1)
    if mode == "cleanup_failures":
        assert observed["killed"] == 1


@pytest.mark.parametrize("mode,status,failure", [
    ("normal", "REVIEW_READY", None),
    ("cancel", "CANCELLED", None),
    ("timeout", "FAILED", "TIME_BUDGET"),
    ("memory", "FAILED", "MEMORY_BUDGET"),
])
def test_normal_cancel_and_existing_budgets_keep_status_and_release_once(setup, monkeypatch, mode, status, failure):
    app, jid, child, observed = worker_fixture(setup, monkeypatch, mode)
    jobs.execute(app, jid)
    assert child.poll() is not None and observed["closed"] == 1
    assert observed["waited"] and all(isinstance(t, (int, float)) and 0 < t <= 10 for t in observed["waited"])
    with app.app_context():
        run, record = jobs.row(jid)
        assert run.status == status
        assert record.value.get("failureCode") == failure
