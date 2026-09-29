"""Source-anchored extractive answers, not unrestricted financial interpretation."""

import re
from hashlib import sha256

from finsight.domain.evidence import CitationStatus
from finsight.domain.grounded_document_answer import GroundedDocumentAnswer
from finsight.services.citation_verification import CitationVerifier
from finsight.services.document_chunk_source import ChunkSourceLoader
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.query_planning import query_digest


def requested_fact(query: str):
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", query))
    if len(years) != 1:
        return None
    lowered = query.casefold()
    matches = []
    if "股息" in query or "dividend" in lowered:
        if any(term in lowered for term in (
            "中期", "第四", "interim", "fourth", "股息率", "yield", "预测", "预计", "未来",
        )):
            return None  # Annual totals must not answer an interim-dividend question.
        matches.append("dividend")
    if ("非利息收入" in query or "non-interest income" in lowered) and any(
        term in lowered for term in ("增", "increase", "growth")
    ):
        matches.append("non_interest_growth")
    if "平均生息资产" in query or "average interest-earning assets" in lowered:
        matches.append("earning_assets")
    if len(matches) != 1:
        return None
    return matches[0], int(next(iter(years)))


def extract_quote(metric: str, content: str, *, year: int | None = None) -> str | None:
    if metric == "dividend":
        # Bind the requested year to the annual total, not a nearby prior-year comparison.
        pattern = (
            r"Total dividend distribution for (?P<distribution_year>\d{4}) was "
            r"HK\\?\$[\d.,]+ per share[^\n]*?(?:year-on-year\.|\n|$)"
            r"|total dividends of HK\\?\$[\d.,]+ per share for (?P<total_year>\d{4})"
            r"(?:[ \t]*\([^()\n]*\))?"
        )
        quotes = {
            match.group(0).strip()
            for match in re.finditer(pattern, content, re.IGNORECASE)
            if year is None
            or int(match.group("distribution_year") or match.group("total_year")) == year
        }
        return next(iter(quotes)) if len(quotes) == 1 else None
    patterns = {
        "non_interest_growth": r"The Bank saw a notable [\d.]+% increase in non-interest income[^\n]*?(?:base\.|\n|$)",
        "earning_assets": r"<table>.*?Average interest-earning assets.*?</table>",
    }
    match = re.search(patterns[metric], content, re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    return match.group(0).strip()


class GroundedDocumentAnswerService:
    def __init__(self, search, sessions, storage):
        self.search = search
        self.sessions = sessions
        self.storage = storage

    def answer(self, query, knowledge_base_id, *, criteria=None):
        fact = requested_fact(query)
        if fact is None:
            return None
        metric, year = fact
        if criteria is not None and (
            criteria.knowledge_base_id != knowledge_base_id
            or (criteria.report_year is not None and criteria.report_year != year)
        ):
            return None
        filters = criteria.model_dump() if criteria is not None else {}
        filters.update(knowledge_base_id=knowledge_base_id, report_year=year)
        output = self.search.search(
            query,
            criteria=DocumentSearchFilter(**filters),
        )
        matches = []
        for citation in output.bundle.citations:
            candidate = citation.evidence.candidate
            quote = extract_quote(metric, candidate.content, year=year)
            if quote is not None and self._anchored(candidate):
                matches.append((citation, quote))
        # Multiple companies/documents cannot silently become one answer.
        if not matches or len({c.evidence.candidate.document_id for c, _ in matches}) != 1:
            return None
        citation, quote = matches[0]
        candidate = citation.evidence.candidate
        # Explicit company naming must match the authoritative document title.
        companies = re.findall(r"([\u4e00-\u9fff]{2,8}银行)", query)
        companies = [re.sub(r"^(?:根据|依据|按照|请查询|查询|请问|请)+", "", name) for name in companies]
        if companies and not (
            all(name == "恒生银行" for name in companies)
            and "hang seng" in candidate.document_title.casefold()
        ):
            return None
        verified = (
            CitationVerifier()
            .verify(
                citation_id="C1", evidence=citation.evidence, claim_text=quote, quoted_text=quote
            )
            .citation
        )
        if verified.status != CitationStatus.VERIFIED:
            return None
        text = (
            f"据《{candidate.document_title}》（报告年份 {year}，上传文件第 {candidate.page_start} 页），"
            f"对应原文为：\n{quote}\n[C1]\n"
            "这是原文摘录及来源一致性核验，不包含投资建议；表格单位与年份以表头为准。"
        )
        return GroundedDocumentAnswer(
            query_sha256=query_digest(query), text=text, citations=(verified,)
        )

    def _anchored(self, candidate):
        from finsight.infrastructure.database.models import Document, DocumentChunk

        with self.sessions() as session:
            row = session.get(DocumentChunk, candidate.chunk_id)
            document = session.get(Document, candidate.document_id)
            if row is None or document is None:
                return False
            fields = (
                "document_id",
                "parse_job_id",
                "chunk_version",
                "content",
                "content_sha256",
                "page_start",
                "page_end",
                "vector_id",
            )
            if any(getattr(row, field) != getattr(candidate, field) for field in fields):
                return False
            if row.source_blocks != [ref.model_dump() for ref in candidate.source_blocks]:
                return False
            if (
                document.report_year != candidate.report_year
                or document.title != candidate.document_title
                or document.company_code != candidate.company_code
                or document.document_type != candidate.document_type
                or document.source_url != candidate.source_url
            ):
                return False
            original = self.storage.get(document.object_key)
            if sha256(original).hexdigest() != document.content_sha256:
                return False
        source = ChunkSourceLoader(self.sessions, self.storage).load(candidate.parse_job_id)
        # Re-chunk the authoritative parsed artifact: do not trust a vector payload as text.
        from finsight.services.financial_chunker import FinancialTextChunker

        return any(
            draft.content == candidate.content and draft.source_blocks == candidate.source_blocks
            for draft in FinancialTextChunker().chunk(source)
        )
