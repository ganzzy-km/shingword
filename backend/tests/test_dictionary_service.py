from __future__ import annotations

from app.services.dictionary_service import DictionaryClient


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.parameters = []

    def get_json(self, endpoint, parameters):
        self.calls += 1
        self.parameters.append((endpoint, parameters))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


def search_payload(item):
    return {"channel": {"item": item}}


def test_dictionary_normalizes_single_and_array_shapes_and_caches():
    single = {
        "target_code": 404765, "word": "나무", "sup_no": 1, "pos": "명사",
        "sense": {"definition": "목질 식물.", "link": "https://stdict.korean.go.kr/search/searchView.do?word_no=404765"},
    }
    transport = FakeTransport([search_payload(single)])
    client = DictionaryClient(lambda: "a" * 32, transport=transport)
    first = client.lookup("나무")
    second = client.lookup("나무")
    assert first["status"] == "available"
    assert first["entries"][0]["target_code"] == "404765"
    assert second["cached"] is True and transport.calls == 1
    assert transport.parameters[0][1]["key"] == "a" * 32

    array_transport = FakeTransport([search_payload([single, {**single, "target_code": 2, "sense": [{"definition": "둘째 뜻"}]}])])
    assert len(DictionaryClient(lambda: "b" * 32, transport=array_transport).lookup("나무")["entries"]) == 2


def test_dictionary_error_codes_retry_and_circuit_breaker():
    invalid = DictionaryClient(lambda: "a" * 32, transport=FakeTransport([{"error": {"error_code": "020"}}]))
    assert invalid.lookup("나무")["status"] == "invalid_key"
    disabled = DictionaryClient(lambda: "a" * 32, transport=FakeTransport([{"error": {"error_code": 21}}]))
    assert disabled.lookup("나무")["status"] == "temporarily_disabled"

    transport = FakeTransport([TimeoutError("slow")])
    client = DictionaryClient(lambda: "a" * 32, transport=transport)
    assert client.lookup("하나")["status"] == "timeout"
    assert client.lookup("둘")["status"] == "timeout"
    assert client.lookup("셋")["status"] == "timeout"
    calls_after_failures = transport.calls
    assert client.lookup("넷")["status"] == "temporarily_disabled"
    assert transport.calls == calls_after_failures


def test_dictionary_malformed_response_never_exposes_key():
    key = "deadbeef" * 4
    client = DictionaryClient(lambda: key, transport=FakeTransport([{"unexpected": []}]))
    result = client.lookup("표현")
    assert result["status"] == "service_unavailable"
    assert key not in str(result)


def test_dictionary_detail_normalizes_view_response():
    payload = {"channel": {"item": {
        "target_code": "404765",
        "word_info": {"word": "나무"},
        "pos_info": {"pos": "명사", "comm_pattern_info": {
            "pattern_info": {"pattern": "명사"},
            "grammar_info": {"grammar": "일반"},
            "sense_info": [{"definition": "목질 식물."}, {"definition": "재료."}],
        }},
    }}}
    transport = FakeTransport([payload])
    result = DictionaryClient(lambda: "c" * 32, transport=transport).detail("404765", "나무")
    assert result["status"] == "available"
    assert [item["definition"] for item in result["entries"]] == ["목질 식물.", "재료."]
    assert transport.parameters[0][0] == "view.do"
    assert transport.parameters[0][1]["method"] == "word_info"
