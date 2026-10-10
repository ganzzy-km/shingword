from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .thresholds import CONCEPT_CONFIDENCE_THRESHOLD


@lru_cache(maxsize=1)
def load_concept_dictionary() -> dict:
    path = Path(__file__).with_name("concept_dictionary.json")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_predicate(predicate: str) -> tuple[str, str | None]:
    value = (predicate or "").strip()
    for group, expressions in load_concept_dictionary().get("predicateGroups", {}).items():
        if value in expressions:
            return group, value
    return value, None


def predicate_group_for_text(text: str, predicate: str) -> str | None:
    group, matched = normalize_predicate(predicate)
    if matched:
        return group
    compact = "".join((text or "").split())
    for candidate_group, expressions in load_concept_dictionary().get("predicateGroups", {}).items():
        for expression in expressions:
            stem = expression[:-1] if expression.endswith("다") else expression
            if "".join(stem.split()) in compact:
                return candidate_group
    return None


def extract_concepts(text: str) -> list[dict]:
    data = load_concept_dictionary()
    if text in data.get("excludedSentences", []):
        return []
    results = []
    for group, expressions in data.get("conceptGroups", {}).items():
        for expression in expressions:
            if expression in text:
                confidence = 1.0 if text in data.get("allowedSentences", []) else 0.86
                results.append({
                    "group": group,
                    "expression": expression,
                    "confidence": confidence,
                    "verified": confidence >= data.get("confidenceThreshold", CONCEPT_CONFIDENCE_THRESHOLD),
                })
    for expression in data.get("uncertainExpressions", []):
        if expression in text:
            results.append({"group": None, "expression": expression, "confidence": 0.45, "verified": False})
    return results
