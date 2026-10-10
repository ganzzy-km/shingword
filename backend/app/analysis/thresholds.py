"""글빛 언어 분석의 조정 가능한 공학적 휴리스틱.

이 값들은 논문에서 직접 제시된 평가 점수가 아니다. 글빛의 회귀 테스트 자료로
조정하는 프로젝트 초기 기준이며, 교사 평가 점수로 사용하지 않는다.
"""

SEMANTIC_WEIGHTS = {
    "roles": 0.25,
    "predicate": 0.25,
    "concepts": 0.15,
    "polarity": 0.15,
    "grammar": 0.10,
    "entities": 0.10,
}

HIGH_EQUIVALENCE_THRESHOLD = 0.85
RELATED_MEANING_THRESHOLD = 0.65
LOW_MORPHOLOGY_CONFIDENCE = 0.55
CONCEPT_CONFIDENCE_THRESHOLD = 0.72

# 표준국어대사전 호출 정책
DICTIONARY_CONNECT_TIMEOUT_SECONDS = 2
DICTIONARY_RESPONSE_TIMEOUT_SECONDS = 3
DICTIONARY_MAX_RETRIES = 1
DICTIONARY_FAILURE_THRESHOLD = 3
DICTIONARY_CIRCUIT_SECONDS = 60
DICTIONARY_CACHE_SECONDS = 60 * 60
DICTIONARY_CACHE_SIZE = 256

