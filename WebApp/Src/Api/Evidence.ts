export type CitationStatus = "pending" | "verified" | "rejected";

export interface EvidenceSearchRequest {
  query: string;
  knowledge_base_id: string;
  company_code?: string;
  document_type?: "annual_report" | "semiannual_report" | "quarterly_report" | "announcement" | "regulatory_policy";
  report_year?: number;
}

export interface Citation {
  citation_id: string;
  quoted_text: string;
  status: CitationStatus;
  verification_reason: string | null;
  evidence: {
    final_rank: number;
    rerank_score: number;
    candidate: {
      document_id: number;
      chunk_id: number;
      chunk_version: number;
      document_title: string;
      document_type: string;
      company_code: string | null;
      report_year: number | null;
      source_url: string | null;
      page_start: number;
      page_end: number;
      section_path: string[];
    };
  };
}

export interface EvidenceSearchResponse {
  bundle: { query_sha256: string; candidate_count: number; citations: Citation[] };
  retrieval: {
    model_name: string;
    query_token_count: number | null;
    filtered_document_ids: number[] | null;
    candidate_vector_ids: string[];
    accepted_chunk_ids: number[];
    rejected_hit_count: number;
  };
  reranking: {
    input_count: number;
    candidate_count: number;
    scored_chunk_ids: number[];
    selected_chunk_ids: number[];
    duplicate_chunk_ids: number[];
    redundant_chunk_ids: number[];
  };
}

export interface EvidenceRun {
  requestId: string | null;
  request: EvidenceSearchRequest;
  response: EvidenceSearchResponse;
}

export function citationLabel(status: CitationStatus): string {
  if (status === "verified") return "已核验";
  if (status === "rejected") return "核验未通过";
  return "待核验 · 不能视为结论依据";
}
