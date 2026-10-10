from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis.engine import argument_links, classify_role  # noqa: E402
from app.analysis.spelling import spelling_findings  # noqa: E402
from validation.cases import CLASSIFICATION_CASES, LINK_CASES, SPELLING_CASES  # noqa: E402


def classification_report():
    rows = []
    for case in CLASSIFICATION_CASES:
        actual, confidence, rule = classify_role(case["text"])
        rows.append({**case, "actual": actual, "confidence": confidence, "rule": rule, "success": actual == case["expected"]})
    correct = sum(row["success"] for row in rows)
    return {
        "total": len(rows),
        "correct": correct,
        "incorrect": len(rows) - correct,
        "accuracyPercent": round(correct * 100 / len(rows), 1),
        "misclassified": [row for row in rows if not row["success"]],
        "cases": rows,
    }


def link_report():
    rows = []
    for case in LINK_CASES:
        result = argument_links(case["sentences"])[0]
        actual = "연결" if result["score"] >= 4 else "비연결"
        rows.append({
            "id": case["id"],
            "claim": result["claim"]["text"],
            "evidence": result["evidence"]["text"],
            "expected": case["expected"],
            "score": result["score"],
            "status": result["status"],
            "details": result["details"],
            "actual": actual,
            "success": actual == case["expected"],
        })
    connected = [row["score"] for row in rows if row["expected"] == "연결"]
    unconnected = [row["score"] for row in rows if row["expected"] == "비연결"]
    return {
        "total": len(rows),
        "correct": sum(row["success"] for row in rows),
        "connectedAverage": round(sum(connected) / len(connected), 2),
        "unconnectedAverage": round(sum(unconnected) / len(unconnected), 2),
        "cases": rows,
    }


def spelling_report():
    rows = []
    for case in SPELLING_CASES:
        findings = spelling_findings(case["text"])
        actual = [finding["current"] for finding in findings]
        rows.append({**case, "actual": actual, "findings": findings, "success": actual == case["expected"]})
    normal_rows = [row for row in rows if not row["expected"]]
    return {
        "total": len(rows),
        "correct": sum(row["success"] for row in rows),
        "falsePositiveNormalSentences": sum(bool(row["actual"]) for row in normal_rows),
        "implemented": ["맞춤법", "명백한 잘못 사용된 단어", "문맥상 어휘 선택 확인"],
        "notImplementedAsSeparateDetector": ["일반 모호 표현", "일반 반복 표현"],
        "cases": rows,
    }


def build_report():
    return {
        "classification": classification_report(),
        "argumentLinks": link_report(),
        "spellingAndWordUse": spelling_report(),
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
