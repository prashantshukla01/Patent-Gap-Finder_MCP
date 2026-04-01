/**
 * Typed API client for the Patent Gap Finder MCP HTTP server.
 *
 * All functions call the Next.js API proxy (/api/proxy) which forwards
 * requests to the MCP server, keeping the API key server-side.
 */

import type {
  ParsePaperResponse,
  ClassifyIPCResponse,
  SearchPriorArtResponse,
  SearchStatusResponse,
  MapLandscapeResponse,
  FindWhitespaceResponse,
  DraftClaimsResponse,
  ExportReportResponse,
  GetSessionResponse,
  HealthCheckResponse,
  MCPError,
} from "@/lib/types"

const MCP_URL =
  process.env.NEXT_PUBLIC_MCP_URL ?? "http://localhost:8000"
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? ""

// ── Helper ─────────────────────────────────────────────────────────

async function mcpFetch<T>(
  toolName: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  const res = await fetch(`${MCP_URL}/mcp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {}),
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: crypto.randomUUID(),
      method: "tools/call",
      params: { name: toolName, arguments: params },
    }),
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(
      (body as MCPError).message ?? `HTTP ${res.status}`,
      res.status,
      body as MCPError,
    )
  }

  const json = await res.json()

  if (json.error) {
    throw new ApiError(
      json.error.message ?? "MCP error",
      json.error.code ?? 500,
      json.error,
    )
  }

  // MCP tool responses wrap the actual result in content[0].text
  const content = json.result?.content
  if (Array.isArray(content) && content.length > 0 && content[0].text) {
    return JSON.parse(content[0].text) as T
  }

  return json.result as T
}

export class ApiError extends Error {
  status: number
  body: MCPError | Record<string, unknown>

  constructor(
    message: string,
    status: number,
    body: MCPError | Record<string, unknown>,
  ) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

// ── Phase 1 — Paper Parsing ────────────────────────────────────────

export async function parsePaper(
  source: string,
  extractWithAI: boolean = true,
) {
  return mcpFetch<ParsePaperResponse>("parse_paper", {
    source,
    extract_with_ai: extractWithAI,
  })
}

// ── Phase 2 — IPC Classification ──────────────────────────────────

export async function classifyIPC(sessionId: string) {
  return mcpFetch<ClassifyIPCResponse>("classify_ipc", {
    session_id: sessionId,
  })
}

// ── Phase 3 — Prior Art Search ─────────────────────────────────────

export async function searchPriorArt(sessionId: string) {
  return mcpFetch<SearchPriorArtResponse>("search_prior_art", {
    session_id: sessionId,
  })
}

export async function getSearchStatus(jobId: string) {
  return mcpFetch<SearchStatusResponse>("get_search_status", {
    job_id: jobId,
  })
}

// ── Phase 4 — Landscape & White-space ─────────────────────────────

export async function mapLandscape(sessionId: string) {
  return mcpFetch<MapLandscapeResponse>("map_landscape", {
    session_id: sessionId,
  })
}

export async function findWhitespace(
  sessionId: string,
  minScore: number = 0.5,
) {
  return mcpFetch<FindWhitespaceResponse>("find_whitespace", {
    session_id: sessionId,
    min_score: minScore,
  })
}

// ── Phase 5 — Claim Drafting & Report ─────────────────────────────

export async function draftClaims(
  sessionId: string,
  minNoveltyScore: number = 0.5,
) {
  return mcpFetch<DraftClaimsResponse>("draft_claims", {
    session_id: sessionId,
    min_novelty_score: minNoveltyScore,
  })
}

export async function exportReport(sessionId: string) {
  return mcpFetch<ExportReportResponse>("export_report", {
    session_id: sessionId,
  })
}

// ── Session ────────────────────────────────────────────────────────

export async function getSession(sessionId: string) {
  return mcpFetch<GetSessionResponse>("get_session", {
    session_id: sessionId,
  })
}

// ── Health ─────────────────────────────────────────────────────────

export async function healthCheck(): Promise<HealthCheckResponse> {
  const res = await fetch(`${MCP_URL}/health`, {
    headers: API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {},
  })
  return res.json()
}

// ── PDF download helper ────────────────────────────────────────────

/**
 * Downloads the PDF report by calling export_report, decoding the
 * base64 response, and triggering a browser download.
 */
export async function downloadReport(sessionId: string): Promise<void> {
  const result = await exportReport(sessionId)

  // Handle chunked responses for large PDFs (> 1 MB)
  let base64: string
  if (result.total_chunks && result.total_chunks > 1) {
    const chunks: string[] = []
    for (let i = 1; i <= result.total_chunks; i++) {
      const key = `pdf_base64_chunk_${i}` as keyof ExportReportResponse
      const chunk = result[key]
      if (typeof chunk === "string") chunks.push(chunk)
    }
    base64 = chunks.join("")
  } else {
    base64 = result.pdf_base64
  }

  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: "application/pdf" })
  const url = URL.createObjectURL(blob)

  const a = document.createElement("a")
  a.href = url
  a.download = result.filename
  document.body.appendChild(a)
  a.click()

  // Cleanup
  setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 100)
}
