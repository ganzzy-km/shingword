from __future__ import annotations

import hashlib
import http.client
import json
import socket
import threading
import time
from collections import OrderedDict
from urllib.parse import urlencode

from ..analysis.thresholds import (
    DICTIONARY_CACHE_SECONDS,
    DICTIONARY_CACHE_SIZE,
    DICTIONARY_CIRCUIT_SECONDS,
    DICTIONARY_CONNECT_TIMEOUT_SECONDS,
    DICTIONARY_FAILURE_THRESHOLD,
    DICTIONARY_MAX_RETRIES,
    DICTIONARY_RESPONSE_TIMEOUT_SECONDS,
)
from .secrets_service import SafeStorageUnavailable, SecretStoreError


SOURCE_NAME = "국립국어원 표준국어대사전"
SOURCE_URL = "https://stdict.korean.go.kr"
VALID_STATUSES = {
    "available", "not_configured", "invalid_key", "timeout",
    "service_unavailable", "temporarily_disabled",
}


class DictionaryTransport:
    host = "stdict.korean.go.kr"

    def get_json(self, endpoint: str, parameters: dict) -> dict:
        connection = http.client.HTTPSConnection(self.host, timeout=DICTIONARY_CONNECT_TIMEOUT_SECONDS)
        try:
            path = f"/api/{endpoint}?{urlencode(parameters)}"
            connection.request("GET", path, headers={"Accept": "application/json", "User-Agent": "Geulbit/1"})
            if connection.sock:
                connection.sock.settimeout(DICTIONARY_RESPONSE_TIMEOUT_SECONDS)
            response = connection.getresponse()
            body = response.read(2 * 1024 * 1024)
            if response.status >= 500:
                raise OSError("upstream server error")
            if response.status != 200:
                raise ValueError("unexpected upstream response")
            value = json.loads(body.decode("utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError("unexpected response shape")
            return value
        finally:
            connection.close()


class DictionaryClient:
    def __init__(self, key_provider, transport=None, clock=None):
        self.key_provider = key_provider
        self.transport = transport or DictionaryTransport()
        self.clock = clock or time.monotonic
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.RLock()
        self._failures = 0
        self._open_until = 0.0

    def lookup(self, query: str, api_key: str | None = None, force: bool = False) -> dict:
        query = (query or "").strip()[:100]
        if not query:
            return self._result("service_unavailable", query, notice="검색어가 비어 있습니다.")
        key, key_error = self._resolve_key(api_key)
        if key_error:
            return self._result("not_configured", query, notice=key_error)
        if not key:
            return self._result("not_configured", query, notice="표준국어대사전 API 키가 설정되지 않았습니다.")

        cache_key = self._cache_key("search", query, key)
        if not force:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return {**cached, "cached": True}
            if self._circuit_open():
                return self._result("temporarily_disabled", query, notice="연속된 호출 실패로 사전 연결을 60초 동안 쉬고 있습니다.")

        payload, failure = self._request("search.do", {
            "key": key,
            "q": query,
            "req_type": "json",
            "advanced": "y",
            "target": "1",
            "method": "exact",
            "type1": "word",
            "num": "10",
        })
        if failure:
            return self._failure_result(query, failure)
        status = self._api_error_status(payload)
        if status:
            return self._result(status, query, notice=self._safe_api_notice(status))
        try:
            entries = self._normalize_search(payload)
        except (KeyError, TypeError, ValueError):
            self._register_failure()
            return self._result("service_unavailable", query, notice="사전 응답 형식이 예상과 달라 보조 검증을 생략했습니다.")
        self._register_success()
        result = self._result("available", query, entries=entries, verified_words=1 if entries else 0)
        self._put_cache(cache_key, result)
        return result

    def detail(self, target_code: str, query: str, api_key: str | None = None, force: bool = False) -> dict:
        target_code, query = str(target_code or "")[:40], (query or "").strip()[:100]
        key, key_error = self._resolve_key(api_key)
        if key_error or not key:
            return self._result("not_configured", query, notice=key_error or "표준국어대사전 API 키가 설정되지 않았습니다.")
        cache_key = self._cache_key("view", f"{target_code}:{query}", key)
        if not force:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return {**cached, "cached": True}
            if self._circuit_open():
                return self._result("temporarily_disabled", query, notice="연속된 호출 실패로 사전 연결을 60초 동안 쉬고 있습니다.")
        payload, failure = self._request("view.do", {
            "key": key, "method": "word_info", "target_code": target_code,
            "q": query, "req_type": "json",
        })
        if failure:
            return self._failure_result(query, failure)
        status = self._api_error_status(payload)
        if status:
            return self._result(status, query, notice=self._safe_api_notice(status))
        try:
            entries = self._normalize_detail(payload)
        except (KeyError, TypeError, ValueError):
            self._register_failure()
            return self._result("service_unavailable", query, notice="사전 상세 응답 형식이 예상과 달라 보조 검증을 생략했습니다.")
        self._register_success()
        result = self._result("available", query, entries=entries, verified_words=1 if entries else 0)
        self._put_cache(cache_key, result)
        return result

    def validate_key(self, api_key: str) -> dict:
        return self.lookup("나무", api_key=api_key, force=True)

    def _request(self, endpoint: str, parameters: dict) -> tuple[dict | None, str | None]:
        for attempt in range(DICTIONARY_MAX_RETRIES + 1):
            try:
                return self.transport.get_json(endpoint, parameters), None
            except (TimeoutError, socket.timeout):
                failure = "timeout"
            except (OSError, http.client.HTTPException, ValueError, json.JSONDecodeError):
                failure = "service_unavailable"
            if attempt < DICTIONARY_MAX_RETRIES:
                continue
        self._register_failure()
        return None, failure

    def _failure_result(self, query: str, status: str) -> dict:
        notice = "사전 응답 시간이 초과되어 보조 검증을 생략했습니다." if status == "timeout" else "사전 서비스에 연결할 수 없어 보조 검증을 생략했습니다."
        return self._result(status, query, notice=notice)

    def _resolve_key(self, explicit):
        if explicit is not None:
            return explicit.strip(), None
        try:
            value = self.key_provider()
            return (value or "").strip(), None
        except (SafeStorageUnavailable, SecretStoreError):
            return None, "안전한 로컬 비밀 저장소를 사용할 수 없어 사전 보조 기능이 제한되었습니다."

    @staticmethod
    def _api_error_status(payload: dict) -> str | None:
        error = payload.get("error")
        if not error:
            return None
        code = str(error.get("error_code", "")).zfill(3)
        if code == "020":
            return "invalid_key"
        if code == "021":
            return "temporarily_disabled"
        return "service_unavailable"

    @staticmethod
    def _safe_api_notice(status: str) -> str:
        return {
            "invalid_key": "등록되지 않았거나 유효하지 않은 API 키입니다.",
            "temporarily_disabled": "표준국어대사전에서 API 키 사용을 일시 중지했습니다.",
        }.get(status, "사전 서비스 오류로 보조 검증을 생략했습니다.")

    @classmethod
    def _normalize_search(cls, payload: dict) -> list[dict]:
        if "channel" not in payload or not isinstance(payload.get("channel"), dict):
            raise ValueError("missing channel")
        channel = payload["channel"]
        items = cls._as_list(channel.get("item"))
        entries = []
        for item in items:
            senses = cls._as_list(item.get("sense")) or [{}]
            for sense in senses:
                link = sense.get("link")
                if isinstance(link, dict):
                    link = next((str(value) for value in link.values() if isinstance(value, str)), None)
                entries.append({
                    "target_code": str(item.get("target_code", "")),
                    "word": str(item.get("word", "")),
                    "sup_no": str(item.get("sup_no", "")),
                    "pos": str(item.get("pos", sense.get("pos", ""))),
                    "definition": str(sense.get("definition", "")),
                    "syntacticArgument": str(sense.get("syntacticArgument", item.get("syntacticArgument", ""))),
                    "syntacticAnnotation": str(sense.get("syntacticAnnotation", item.get("syntacticAnnotation", ""))),
                    "link": cls._safe_link(link),
                    "source": SOURCE_NAME,
                })
        return entries

    @classmethod
    def _normalize_detail(cls, payload: dict) -> list[dict]:
        if "channel" not in payload or not isinstance(payload.get("channel"), dict):
            raise ValueError("missing channel")
        channel = payload["channel"]
        items = cls._as_list(channel.get("item"))
        entries = []
        for item in items:
            word_info = item.get("word_info") or {}
            pos_infos = cls._as_list(item.get("pos_info")) or [{}]
            for pos_info in pos_infos:
                patterns = cls._as_list(pos_info.get("comm_pattern_info")) or [{}]
                for pattern in patterns:
                    senses = cls._as_list(pattern.get("sense_info")) or [{}]
                    for sense in senses:
                        entries.append({
                            "target_code": str(item.get("target_code", "")),
                            "word": str(word_info.get("word", "")),
                            "sup_no": "",
                            "pos": str(pos_info.get("pos", "")),
                            "definition": str(sense.get("definition", "")),
                            "syntacticArgument": str((pattern.get("pattern_info") or {}).get("pattern", "")),
                            "syntacticAnnotation": str((pattern.get("grammar_info") or {}).get("grammar", "")),
                            "link": None,
                            "source": SOURCE_NAME,
                        })
        return entries

    @staticmethod
    def _as_list(value):
        if value is None:
            return []
        return value if isinstance(value, list) else [value] if isinstance(value, dict) else []

    @staticmethod
    def _safe_link(value):
        return value if isinstance(value, str) and value.startswith("https://stdict.korean.go.kr/") else None

    def _result(self, status, query, entries=None, verified_words=0, notice=None):
        return {
            "status": status if status in VALID_STATUSES else "service_unavailable",
            "query": query,
            "verifiedWords": verified_words,
            "entries": entries or [],
            "source": {"name": SOURCE_NAME, "url": SOURCE_URL},
            "notice": notice,
            "cached": False,
        }

    @staticmethod
    def _cache_key(kind: str, query: str, key: str) -> str:
        key_generation = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return f"{kind}:{key_generation}:{query}"

    def _get_cache(self, key):
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= self.clock():
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    def _put_cache(self, key, value):
        with self._lock:
            self._cache[key] = (self.clock() + DICTIONARY_CACHE_SECONDS, value)
            self._cache.move_to_end(key)
            while len(self._cache) > DICTIONARY_CACHE_SIZE:
                self._cache.popitem(last=False)

    def _circuit_open(self):
        with self._lock:
            return self._open_until > self.clock()

    def _register_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= DICTIONARY_FAILURE_THRESHOLD:
                self._open_until = self.clock() + DICTIONARY_CIRCUIT_SECONDS

    def _register_success(self):
        with self._lock:
            self._failures = 0
            self._open_until = 0.0
