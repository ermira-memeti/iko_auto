"""V8.3: narrow, audit-friendly activation of FIVE V8.2 draft RDF additions.

Development-only rules were designed after inspecting the 50 AI-assisted V8
questions and retrieval errors. They do not constitute independent intent
classification or semantic entailment. Original V6 graph and V8.2 graph stay
byte-for-byte unchanged; only this separately named eighth retrieval method
uses the route. Unrelated policy questions use original V6 evidence ranking.
"""
from __future__ import annotations
import re
from .policy_catalog import named_insurers

METHOD = "bm25_metadata_graph_intent_v8_3"

# Both a topic-specific anchor AND its correct insurer are needed. Generic
# words ("damage", "car", "approved", "repair", "accident") never activate.
# The Direct Line hire-car route must not fire for car-sharing questions.
TOPIC_PATTERNS = {
    "AXA": {
        "windscreen": (r"\bwindscreen\b|\bwindshield\b|\bcar glass\b|\bwindow glass\b",),
    },
    "Admiral": {
        "windscreen_adas": (r"\badas\b|\brecalibrat\w*\b|driver[ -]assistance|driver[ -]assist",),
    },
    "Aviva": {
        "glass_adas": (r"\bwindscreen\b|\bwindshield\b|\bglass (?:claim|repair|work|replacement)\b|\badas\b|\brecalibrat\w*\b",),
    },
    "Direct Line": {
        "windscreen": (r"\bwindscreen\b|\bwindshield\b|\bglass (?:repair|replacement|claim|work)\b",),
        "hire_car": (r"\bhire car\b|\bhired car\b|\breplacement hire vehicle\b",),
    },
}


def route_intent(question: str, insurer: str) -> dict:
    """Return conservative decision: extended or ORIGINAL V6 graph.

    Multiple named insurers, mismatched insurer names, and unknown insurers
    are never assigned a cross-policy V8.2 clause. The original graph may
    itself reject conflicting insurer names; this method cannot bypass that.
    """
    named = named_insurers(question)
    match = not named or named == [insurer]
    reason = "NO_TOPIC_MATCH"
    topic = None
    if not match:
        reason = "CONFLICTING_OR_MULTIPLE_INSURERS"
    elif insurer not in TOPIC_PATTERNS:
        reason = "NO_ENHANCED_CONCEPT_FOR_INSURER"
    else:
        for key, patterns in TOPIC_PATTERNS[insurer].items():
            if all(re.search(pat, question, flags=re.IGNORECASE) for pat in patterns):
                topic=key
                reason="EXPLICIT_CONCEPT_AND_POLICY_MATCH"
                break
    return {"insurer":insurer, "mentioned_insurers":named, "topic":topic,
            "route":"enhanced_v8_2" if topic else "original_v6",
            "reason":reason, "gate_version":"v8.3-explicit-insurer-topic-v1"}
