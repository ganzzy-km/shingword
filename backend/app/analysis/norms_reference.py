"""Provenance for reviewed detectors and the full default reference catalogue.

No PDF, database or network access occurs during analysis. Locations address
the supplied compilation's actual PDF pages, not original HWP page numbers.
"""
from .norms_catalogue import catalogue_manifest, detector_provisions
from .reviewed_norms import REVIEWED_PAIRS, rule_id as reviewed_rule_id

PRIMARY_REFERENCE = {
    "id": "geulbit-korean-norms-reference-v1",
    "title": "글빛 한국어 규범 참고 자료집",
    "version": "v1",
    "compiledAt": "2026-10-09",
    "publicationType": "USER_SUPPLIED_COMPILATION",
    "fileName": "geulbit_korean_norms_reference_v1.pdf",
    "sha256": "c56cfbc534c6459f3d67af72cdb96fb150bd5bf002c753fd1ce25aea95b045c5",
    "pdfPageCount": 314,
    "currentNormsChecked": False,
    "redistributionStatus": "USER_AUTHORIZED_2026_10_11",
    "authorizationScope": "Full supplied PDF, public reference registration; not independent licence verification",
    "originalSources": [
        {"id": "A", "title": "한글 맞춤법", "publisher": "문화체육관광부",
         "edition": "고시 제2017-12호", "issuedAt": "2017-03-28", "pdfPages": [10, 49]},
        {"id": "B", "title": "한글 맞춤법·표준어 규정 해설", "publisher": "국립국어원",
         "issuedAt": "2018-12-21", "pdfPages": [50, 313]},
    ],
}

# These are located passages, not approval of a pattern's context handling.
RULE_LOCATIONS = {
    "gb-local-001": {"article": "한글 맞춤법 제42항", "pdfPages": [26, 151],
                     "reviewScope": "의존 명사 수의 띄어쓰기; 문맥·인용·고유 어휘 예외 유지"},
    "gb-local-002": {"article": "한글 맞춤법 제27항 붙임 2", "pdfPages": [22, 126, 127],
                     "reviewScope": "며칠의 규정 및 해설; 직접 인용·고유 어휘 예외 유지"},
    "gb-local-005": {"article": "한글 맞춤법 제57항", "pdfPages": [33, 191, 192],
                     "reviewScope": "자격·수단·시간 기준의 의미 구별; 무조건 교체 불가"},
    "gb-local-006": {"article": "한글 맞춤법 제42항", "pdfPages": [151], "reviewScope": "용언 뒤 의존 명사 뿐; 체언 뒤 조사뿐 제외"},
    "gb-local-007": {"article": "한글 맞춤법 제42항", "pdfPages": [151], "reviewScope": "아는 대로; 법대로 등 조사 용법 제외"},
    "gb-local-008": {"article": "한글 맞춤법 제42항", "pdfPages": [152], "reviewScope": "애쓴 만큼; 체언 뒤 조사만큼 제외"},
}


def rule_reference(rule_id):
    location = RULE_LOCATIONS.get(rule_id)
    if location is None:
        for index, (article, page, _bad, _good) in enumerate(REVIEWED_PAIRS):
            if rule_id == reviewed_rule_id(index):
                location = {'article': f'한글 맞춤법 제{article}항', 'pdfPages': [page],
                            'reviewScope': '원본 표·허용 조건을 시각 검토한 제한적 표기 후보; 인용·고유 어휘 보호'}
                break
    if location is None:
        return None
    return {"reference": PRIMARY_REFERENCE, "location": location,
            "normsCatalogue": catalogue_manifest(), "provisionIds": detector_provisions(rule_id),
            "status": "PASSAGE_LOCATED_NOT_RULE_APPROVAL"}
