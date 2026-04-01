import { NextRequest, NextResponse } from "next/server"

const MCP_URL = process.env.MCP_URL ?? "http://localhost:8000"
const API_KEY = process.env.MCP_API_KEY ?? ""

/**
 * API proxy that forwards requests to the MCP HTTP server.
 * Keeps the API key server-side so it is never exposed to the browser.
 *
 * Usage: POST /api/proxy  body: { tool: "parse_paper", params: {...} }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { tool, params } = body as {
      tool: string
      params: Record<string, unknown>
    }

    if (!tool) {
      return NextResponse.json(
        { error: "Missing 'tool' field" },
        { status: 400 },
      )
    }

    const mcpBody = {
      jsonrpc: "2.0",
      id: crypto.randomUUID(),
      method: "tools/call",
      params: { name: tool, arguments: params ?? {} },
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    }
    if (API_KEY) {
      headers["Authorization"] = `Bearer ${API_KEY}`
    }

    const upstream = await fetch(`${MCP_URL}/mcp`, {
      method: "POST",
      headers,
      body: JSON.stringify(mcpBody),
    })

    const data = await upstream.json()

    if (!upstream.ok) {
      return NextResponse.json(data, { status: upstream.status })
    }

    return NextResponse.json(data)
  } catch (err) {
    const message = err instanceof Error ? err.message : "Proxy error"
    return NextResponse.json({ error: message }, { status: 502 })
  }
}

/**
 * Health check passthrough.
 */
export async function GET() {
  try {
    const headers: Record<string, string> = {}
    if (API_KEY) {
      headers["Authorization"] = `Bearer ${API_KEY}`
    }

    const upstream = await fetch(`${MCP_URL}/health`, { headers })
    const data = await upstream.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json(
      { status: "unreachable", error: "Cannot reach MCP server" },
      { status: 502 },
    )
  }
}
