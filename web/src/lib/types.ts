// All UUIDs as strings, all dates as ISO format strings

export type PipelineStep =
  | "idle"
  | "parsing"
  | "extracting"
  | "classifying"
  | "searching"
  | "mapping"
  | "analyzing"
  | "drafting"
  | "complete"
  | "error"

export enum PatentSource {
  USPTO = "uspto",
  EPO = "epo",
  GOOGLE_PATENTS = "google_patents",
}

export enum ClaimType {
  INDEPENDENT = "independent",
  DEPENDENT = "dependent",
}

// ==============
// Phase 1 Models
// ==============
export interface ParsedSection {
  title: string
  content: string
}

export interface CandidateClaim {
  id: string
  text: string
  type: string
}

export interface ParsedPaper {
  session_id: string
  title: string
  authors: string[]
  abstract: string
  sections: ParsedSection[]
  heuristic_claims_extracted: CandidateClaim[]
}

// ==============
// Phase 2 Models
// ==============
export interface AIExtractedClaim {
  claim_number: number
  claim_text: string
  claim_type: ClaimType
  dependent_on: number | null
  primary_ipc: string | null
  confidence: number
  domain: string | null
}

export interface IPCClassificationResponse {
  top_ipc_codes: string[]
  search_keywords: string[]
  primary_domain: string
  summary: string
  confidence: number
}

export interface ClaimIPCMapping {
  claim_number: number
  ipc_codes: string[]
}

// ==============
// Phase 3 Models
// ==============
export interface PatentSearchResult {
  job_id: string
  result_count: number
  duration_seconds: number
  status: string
  error_message: string | null
}

// Note: Using Patent instead of a DB model
export interface Patent {
  patent_id: string
  title: string
  abstract: string | null
  publication_date: string | null
  source_url: string | null
  source: PatentSource
  assignee: string | null
  inventors: string[]
  ipc_codes: string[]
  abstract_similarity: number | null
  cluster_id: number | null
  cluster_label: string | null
}

export interface SearchJob {
  job_id: string
  session_id: string
  status: string
  total_results: number
  started_at: string
  completed_at: string | null
  error_message: string | null
}

// ==============
// Phase 4 Models
// ==============
export interface ClusterInfo {
  cluster_id: number
  label: string
  technical_domain: string
  patent_count: number
  centroid_patent_ids: string[]
  representative_titles: string[]
  avg_internal_similarity: number
}

export interface LandscapeJob {
  job_id: string
  session_id: string
  status: string
  n_clusters: number | null
  total_patents_embedded: number | null
  started_at: string
  completed_at: string | null
  cluster_records?: ClusterInfo[]
}

export interface LandscapeMap {
  n_clusters: number
  total_patents_embedded: number
  pca_variance_explained: number[]
  clusters: ClusterInfo[]
}

export interface WhitespaceOpportunity {
  opportunity_id: string
  claim_text: string
  novelty_score: number
  nearest_cluster_id: number | null
  nearest_cluster_label: string
  nearest_patent_ids: string[]
  nearest_patent_titles: string[]
  gemini_novelty_assessment: string | null
  gemini_confidence: number | null
  recommended_claim_scope: string
  ipc_whitespace_codes: string[]
  is_whitespace: boolean
}

export interface WhitespaceReport {
  session_id: string
}

// ==============
// Tool Response Models (Used in api.ts)
// ==============

export interface MCPError {
  code?: number
  message?: string
}

export interface ParsePaperResponse {
  session_id: string
  claims_extracted: number
}

export interface ClassifyIPCResponse {
  session_id: string
  top_ipc_codes: string[]
  search_keywords: string[]
  primary_domain: string
  summary: string
  confidence: number
}

export interface SearchPriorArtResponse {
  session_id: string
  job_id: string
}

export interface SearchStatusResponse {
  job_id: string
  status: string
  result_count?: number
  duration_seconds?: number
  error_message?: string | null
}

export interface MapLandscapeResponse {
  session_id: string
  n_clusters: number
  total_patents_embedded: number
}

export interface FindWhitespaceResponse {
  session_id: string
  whitespace_opportunities: WhitespaceOpportunity[]
}

export interface DraftClaimsResponse {
  session_id: string
  total_claim_sets: number
  claim_sets: Record<string, unknown>[]
  drafting_summary: string
  recommended_filing_order: string[]
  disclaimer: string
  next_step: string
}

export interface ExportReportResponse {
  session_id: string
  filename: string
  pdf_base64: string
  size_bytes: number
  pages_estimated: number
  generated_at: string
  sections: string[]
  total_chunks?: number
  // dynamic chunk keys for large PDFs
  [key: string]: unknown
}

export interface HealthCheckResponse {
  status: string
  checks: Record<string, string>
  version: string
  timestamp: string
}

// ==============
// Phase 5 Models
// ==============
export interface DraftedClaim {
  claim_number: number
  claim_text: string
  claim_type: ClaimType
  depends_on: number | null
  patent_claim_category: string
}

export interface ClaimSet {
  opportunity_id: string
  claim_text_original: string
  novelty_score: number
  recommended_scope: string
  claims: DraftedClaim[]
  drafting_rationale: string
  distinguishing_features: string[]
  ipc_codes: string[]
  gemini_disclaimer: string
}

export interface ClaimDraftReport {
  session_id: string
  paper_title: string
  total_opportunities: number
  claim_sets: ClaimSet[]
  drafting_summary: string
  recommended_filing_order: string[]
  created_at: string
  disclaimer: string
}

// ==============
// Session Model
// ==============
export interface GetSessionResponse {
  id: string
  source_uri: string
  status: string
  paper_title: string | null
  paper_authors: string[] | null
  paper_summary: string | null
  primary_domain: string | null
  top_ipc_codes: string[] | null
  total_patents_found: number | null
  landscape_complete: boolean
  whitespace_analysis_complete: boolean
  claims_drafted: boolean
  top_opportunity_count: number | null
  created_at: string
  
  // These get populated depending on how much of the pipeline is complete
  whitespace_opportunities?: WhitespaceOpportunity[]
  landscape_jobs?: LandscapeJob[]
  claim_sets?: ClaimSet[]
  patents?: Patent[]
}
