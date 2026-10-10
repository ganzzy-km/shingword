from __future__ import annotations

import re

from .concepts import extract_concepts, predicate_group_for_text
from .morphology import analyze_morphology
from .quotation import extract_quotations


ROLE_PATTERNS = {
    "subject": re.compile(r"([가-힣A-Za-z0-9·]+?)(?:은|는|이|가)(?=\s|,|$)"),
    "target": re.compile(r"([가-힣A-Za-z0-9·]+?)(?:을|를)(?=\s|,|$)"),
    "recipient": re.compile(r"([가-힣A-Za-z0-9·]+?)(?:에게|한테|께)(?=\s|,|$)"),
}


def extract_semantic_roles(text: str, morphology: dict | None = None) -> dict:
    morphology = morphology or analyze_morphology(text)
    quotations = extract_quotations(text)
    roles = {
        name: _unique(match.group(1) for match in pattern.finditer(text))
        for name, pattern in ROLE_PATTERNS.items()
    }
    quote_data = []
    for item in quotations:
        before = text[max(0, item.start - 40) : item.start]
        after = text[item.end : min(len(text), item.end + 30)]
        speaker_match = re.search(r"([가-힣A-Za-z0-9·]+?)(?:은|는|이|가)\s*$", before)
        action_match = re.search(r"(?:라고|하고|라며|하며)\s*([가-힣]+)", after)
        quote_data.append({
            **item.to_dict(),
            "speaker": speaker_match.group(1) if speaker_match else None,
            "action": _verb_lemma(action_match.group(1)) if action_match else None,
        })

    proper_nouns = _unique(
        [token["surface"] for token in morphology.get("morphemes", []) if str(token.get("pos", "")).startswith("NNP")]
        + re.findall(r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*|《[^》]+》|〈[^〉]+〉", text)
    )
    numbers = _unique(re.findall(r"\d+(?:[.,]\d+)?(?:년|월|일|명|개|쪽|%)?", text))
    relation = "cause_effect" if re.search(r"때문|므로|따라서|결과", text) else "comparison" if re.search(r"보다|만큼|더\s", text) else "statement"

    return {
        "subject": roles["subject"],
        "target": roles["target"],
        "recipient": roles["recipient"],
        "concepts": extract_concepts(text),
        "predicate": morphology.get("mainVerb", ""),
        "predicateGroup": predicate_group_for_text(text, morphology.get("mainVerb", "")),
        "polarity": morphology.get("polarity", "positive"),
        "tense": morphology.get("tense", ""),
        "aspect": morphology.get("aspect", ""),
        "modality": morphology.get("modality", ""),
        "causative": bool(morphology.get("causative")),
        "passive": bool(morphology.get("passive")),
        "quotation": quote_data or None,
        "properNouns": proper_nouns,
        "numbers": numbers,
        "relation": relation,
    }


def _verb_lemma(value: str) -> str:
    for suffix in ("했다", "하였다", "말했다", "물었다", "대답했다"):
        if value.endswith(suffix):
            return value[:-1] + "다"
    return value if value.endswith("다") else f"{value}다"


def _unique(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
