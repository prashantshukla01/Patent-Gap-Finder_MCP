"use client"

import type { GetSessionResponse } from "@/lib/types"

interface Props {
  session: GetSessionResponse
}

export function SessionSummary({ session }: Props) {
  const cards = [
    {
      label: "Status",
      value: session.status,
      color: session.status === "complete" ? "text-green-400" : "text-blue-400",
      icon: session.status === "complete" ? "✓" : "⏳",
    },
    {
      label: "Patents Found",
      value: session.total_patents_found?.toString() ?? "—",
      color: "text-blue-300",
      icon: "📋",
    },
    {
      label: "Opportunities",
      value: session.top_opportunity_count?.toString() ?? "0",
      color: "text-amber-300",
      icon: "💡",
    },
    {
      label: "Claims Drafted",
      value: session.claims_drafted ? "Yes" : "No",
      color: session.claims_drafted ? "text-green-300" : "text-gray-500",
      icon: "📝",
    },
  ]

  return (
    <div>
      {/* Paper title */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100 leading-tight">
          {session.paper_title}
        </h1>
        {session.paper_authors && session.paper_authors.length > 0 && (
          <p className="mt-1 text-sm text-gray-500">
            {session.paper_authors.join(", ")}
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
          {session.primary_domain && (
            <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-400">
              {session.primary_domain}
            </span>
          )}
          {session.top_ipc_codes &&
            session.top_ipc_codes.slice(0, 3).map((ipc) => (
              <span
                key={ipc}
                className="px-2 py-0.5 rounded bg-gray-800/60 text-gray-500 font-mono"
              >
                {ipc}
              </span>
            ))}
          <span className="text-gray-600">|</span>
          <span className="font-mono">{session.id.slice(0, 8)}</span>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-4 hover:bg-gray-900/50 transition-colors"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500">{c.label}</span>
              <span className="text-base">{c.icon}</span>
            </div>
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Paper summary */}
      {session.paper_summary && (
        <div className="mt-6 rounded-lg bg-gray-800/20 p-4 border border-gray-800/30">
          <p className="text-xs text-gray-500 mb-1 font-medium">
            Paper Summary
          </p>
          <p className="text-sm text-gray-300 leading-relaxed">
            {session.paper_summary}
          </p>
        </div>
      )}
    </div>
  )
}
