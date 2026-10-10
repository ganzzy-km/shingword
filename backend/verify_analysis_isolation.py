"""Audit existing analysis modules without importing the Flask app or opening DBs.

This is a verification loader, not a new production engine or API contract.
"""
import importlib.util
import json
import socket
import sqlite3
import sys
from pathlib import Path


def forbidden(*_args, **_kwargs):
    raise AssertionError("analysis attempted database or network access")


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
directory = Path(__file__).parent / "app" / "analysis"
spec = importlib.util.spec_from_file_location("existing_analysis", directory / "__init__.py", submodule_search_locations=[str(directory)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from existing_analysis.engine import split_sentences
from existing_analysis.integration import analyze_sentence

text = "한글 🐧 漢字.\r\n\r\n가와 가, é를 확인한다."
sentences = split_sentences(text)
assert all(text[s["start"]:s["end"]] == s["text"] for s in sentences)
assert [s["start"] for s in sentences] == sorted(s["start"] for s in sentences)
first = analyze_sentence("학생이 책을 읽는다.")
second = analyze_sentence("학생이 책을 읽는다.")
assert first == second
assert first["morphology"]["analyzer"] == "kiwi"
assert not any(name in sys.modules for name in ("app", "flask", "sqlalchemy"))
assert split_sentences("") == []
print(json.dumps({"status": "PASS_COMPONENT_AUDIT_ONLY", "checks": 6,
                  "kiwi": True, "deterministic": True, "spanSlicesMatch": True,
                  "flaskDbNetworkUsed": False,
                  "p02Complete": False, "remaining": ["standalone production package entry", "NFC/LF input contract", "versioned result schema and approved P02 gates"]}))
