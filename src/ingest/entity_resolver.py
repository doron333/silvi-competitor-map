"""
Operator name entity resolution.

Problem observed in real MSHA data:
  "New Enterprise Stone & Lime Co., Inc."
  "NEW ENTERPRISE STONE & LIME CO., INC."
  "New Enterprise Stone and Lime Co., Inc."
  ... appear as 4+ distinct strings for the same company (27 sites).

Rules implemented (from the build log):
- Normalize case, punctuation, whitespace
- Strip legal suffixes ONLY from the tail (never mid-name)
  so "New Enterprise Stone & Lime" does not become "new stone lime"
- Refuse to merge clearly different entities (e.g. Silvi Concrete vs Silvi Materials)
- Use rapidfuzz for residual near-duplicates after normalization
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

from rapidfuzz import fuzz, process

# Legal / corporate suffixes that should only be stripped when they appear at the end
LEGAL_SUFFIXES = [
    r"\bincorporated\b",
    r"\binc\b\.?",
    r"\bllc\b\.?",
    r"\bllp\b\.?",
    r"\blp\b\.?",
    r"\bco\b\.?",
    r"\bcompany\b",
    r"\bcorp\b\.?",
    r"\bcorporation\b",
    r"\bltd\b\.?",
    r"\blimited\b",
    r"\bplc\b\.?",
    r"\bdba\b",
    r"\bd/b/a\b",
]

SUFFIX_PATTERN = re.compile(
    r"(?:,?\s+(?:" + "|".join(LEGAL_SUFFIXES) + r"))+\s*$",
    re.IGNORECASE,
)

# Tokens that should never be collapsed across entities
HARD_STOP_TOKENS = {
    "concrete", "materials", "ready", "mix", "asphalt", "paving",
    "construction", "contracting", "trucking", "hauling",
}


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).upper()
    # Unify punctuation
    s = s.replace("&", " AND ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Strip legal suffixes from the *end only*
    s = SUFFIX_PATTERN.sub("", s).strip()
    return s


def is_hard_conflict(a: str, b: str) -> bool:
    """Return True if the two normalized names should never be merged."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    # If one contains a hard-stop token the other lacks, refuse
    for tok in HARD_STOP_TOKENS:
        in_a = tok in tokens_a
        in_b = tok in tokens_b
        if in_a != in_b:
            return True
    return False


class OperatorResolver:
    """
    Collapse variant operator strings into canonical operator IDs.
    """

    def __init__(self, similarity_threshold: int = 92):
        self.threshold = similarity_threshold
        self._canonical: Dict[str, str] = {}          # normalized -> canonical display
        self._raw_to_canonical: Dict[str, str] = {}   # original raw -> canonical
        self._groups: Dict[str, List[str]] = defaultdict(list)

    def add(self, raw_name: str | None) -> str:
        if not raw_name or not str(raw_name).strip():
            return "UNKNOWN"
        raw = str(raw_name).strip()
        norm = normalize_name(raw)
        if not norm:
            return "UNKNOWN"

        if norm in self._canonical:
            canon = self._canonical[norm]
            self._raw_to_canonical[raw] = canon
            return canon

        # Fuzzy match against existing canonicals
        if self._canonical:
            match = process.extractOne(
                norm,
                list(self._canonical.keys()),
                scorer=fuzz.token_sort_ratio,
                score_cutoff=self.threshold,
            )
            if match:
                matched_norm, score, _ = match
                if not is_hard_conflict(norm, matched_norm):
                    canon = self._canonical[matched_norm]
                    self._canonical[norm] = canon
                    self._raw_to_canonical[raw] = canon
                    self._groups[canon].append(raw)
                    return canon

        # New canonical
        # Prefer a clean title-cased version of the normalized form
        display = " ".join(w.capitalize() for w in norm.split())
        self._canonical[norm] = display
        self._raw_to_canonical[raw] = display
        self._groups[display].append(raw)
        return display

    def resolve(self, raw_name: str | None) -> str:
        if not raw_name:
            return "UNKNOWN"
        raw = str(raw_name).strip()
        if raw in self._raw_to_canonical:
            return self._raw_to_canonical[raw]
        return self.add(raw)

    def stats(self) -> Dict[str, int]:
        return {
            "raw_variants": len(self._raw_to_canonical),
            "canonical_operators": len(self._groups),
        }

    def get_groups(self) -> Dict[str, List[str]]:
        return dict(self._groups)
