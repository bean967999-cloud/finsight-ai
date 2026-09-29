"""Deterministic citation anchoring and financial-number consistency checks."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from finsight.domain.evidence import Citation, CitationStatus, RerankedEvidence

_CITATION_MARKER = re.compile(r"\[C[1-9][0-9]*\]", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<value>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>个百分点|万亿元|亿元|万元|万股|亿股|％|%|元|亿|万|股|年|月|日|倍|次)?"
)

_UNIT_RULES: dict[str, tuple[str, Decimal]] = {
    "元": ("currency_cny", Decimal(1)),
    "万元": ("currency_cny", Decimal(10_000)),
    "亿元": ("currency_cny", Decimal(100_000_000)),
    "万亿元": ("currency_cny", Decimal(1_000_000_000_000)),
    "股": ("shares", Decimal(1)),
    "万股": ("shares", Decimal(10_000)),
    "亿股": ("shares", Decimal(100_000_000)),
    "万": ("scaled_count", Decimal(10_000)),
    "亿": ("scaled_count", Decimal(100_000_000)),
    "%": ("percent", Decimal(1)),
    "％": ("percent", Decimal(1)),
    "个百分点": ("percentage_point", Decimal(1)),
    "年": ("year", Decimal(1)),
    "月": ("month", Decimal(1)),
    "日": ("day", Decimal(1)),
    "倍": ("multiple", Decimal(1)),
    "次": ("count", Decimal(1)),
    "": ("scalar", Decimal(1)),
}


@dataclass(frozen=True, slots=True)
class NumericFact:
    raw: str
    value: Decimal
    dimension: str

    @property
    def canonical(self) -> str:
        return f"{self.dimension}:{self.value.normalize()}"


@dataclass(frozen=True, slots=True)
class CitationVerification:
    citation: Citation
    claim_facts: tuple[NumericFact, ...]
    quote_facts: tuple[NumericFact, ...]
    unsupported_facts: tuple[NumericFact, ...]


class CitationVerifier:
    """Verifies exact quote anchoring and number/unit consistency.

    This intentionally does not decide whether a qualitative paraphrase is semantically
    equivalent to the source. It establishes a deterministic minimum safety boundary.
    """

    def verify(
        self,
        *,
        citation_id: str,
        evidence: RerankedEvidence,
        claim_text: str,
        quoted_text: str,
    ) -> CitationVerification:
        claim_text = claim_text.strip()
        quoted_text = quoted_text.strip()
        if not claim_text:
            raise ValueError("claim_text must not be empty")
        if not quoted_text:
            raise ValueError("quoted_text must not be empty")

        # Check this before constructing Citation so callers receive a rejected audit result
        # rather than losing the reason inside a validation exception.
        if quoted_text not in evidence.candidate.content:
            citation = Citation(
                citation_id=citation_id,
                evidence=evidence,
                quoted_text=evidence.candidate.content,
                status=CitationStatus.REJECTED,
                verification_reason="requested quote is not an exact substring of the source chunk",
            )
            return CitationVerification(citation, (), (), ())

        claim_facts = self.extract_numeric_facts(claim_text)
        quote_facts = self.extract_numeric_facts(quoted_text)
        supported = {fact.canonical for fact in quote_facts}
        unsupported = tuple(fact for fact in claim_facts if fact.canonical not in supported)
        if unsupported:
            missing = ", ".join(fact.raw for fact in unsupported)
            status = CitationStatus.REJECTED
            reason = f"claim numbers or units are not supported by the quote: {missing}"
        elif claim_facts:
            status = CitationStatus.VERIFIED
            reason = "quote is source-anchored and every claim number matches in value and unit"
        else:
            status = CitationStatus.VERIFIED
            reason = "quote is source-anchored; no numeric claim required numeric comparison"

        citation = Citation(
            citation_id=citation_id,
            evidence=evidence,
            quoted_text=quoted_text,
            status=status,
            verification_reason=reason,
        )
        return CitationVerification(citation, claim_facts, quote_facts, unsupported)

    @staticmethod
    def extract_numeric_facts(text: str) -> tuple[NumericFact, ...]:
        text = _CITATION_MARKER.sub("", text)
        facts: list[NumericFact] = []
        for match in _NUMBER.finditer(text):
            raw_value = match.group("value")
            unit = match.group("unit") or ""
            dimension, multiplier = _UNIT_RULES[unit]
            try:
                value = Decimal(raw_value.replace(",", "")) * multiplier
            except InvalidOperation as exc:  # Defensive: regex should already prevent this.
                raise ValueError(f"invalid numeric value: {raw_value}") from exc
            facts.append(NumericFact(match.group(0).strip(), value, dimension))
        return tuple(facts)
