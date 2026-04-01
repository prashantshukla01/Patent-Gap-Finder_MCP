"use client"

import type { WhitespaceOpportunity } from "@/lib/types"

interface Props {
  opportunity: WhitespaceOpportunity
}

function noveltyColor(score: number): string {
  if (score >= 0.75) return "text-green-400"
  if (score >= 0.5) return "text-amber-400"
  return "text-red-400"
}

function noveltyBg(score: number): string {
  if (score >= 0.75) return "bg-green-500/10 border-green-500/20"
  if (score >= 0.5) return "bg-amber-500/10 border-amber-500/20"
  return "bg-red-500/10 border-red-500/20"
}

function scopeBadge(scope: string) {
  const map: Record<string, string> = {
    broad: "bg-blue-500/15 text-blue-300 border-blue-500/20",
    medium: "bg-amber-500/15 text-amber-300 border-amber-500/20",
    narrow: "bg-purple-500/15 text-purple-300 border-purple-500/20",
  }
  return map[scope] ?? map.medium
}

export function OpportunityCard({ opportunity: opp }: Props) {
  const barWidth = Math.round(opp.novelty_score * 100)

  return (
    <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-6 hover:border-gray-700/60 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-4">
        <p className="text-sm text-gray-200 leading-relaxed flex-1">
          {opp.claim_text.length > 250
            ? opp.claim_text.slice(0, 250) + "…"
            : opp.claim_text}
        </p>
        <div className="shrink-0 flex flex-col items-end gap-2">
          <span
            className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold border ${noveltyBg(opp.novelty_score)} ${noveltyColor(opp.novelty_score)}`}
          >
            {(opp.novelty_score * 100).toFixed(0)}% Novel
          </span>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${scopeBadge(opp.recommended_claim_scope)}`}
          >
            {opp.recommended_claim_scope}
          </span>
        </div>
      </div>

      {/* Novelty bar */}
      <div className="mb-4">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>Novelty Score</span>
          <span className="font-mono">
            {opp.novelty_score.toFixed(2)} / 1.0
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              opp.novelty_score >= 0.75
                ? "bg-gradient-to-r from-green-500 to-emerald-400"
                : opp.novelty_score >= 0.5
                  ? "bg-gradient-to-r from-amber-500 to-yellow-400"
                  : "bg-gradient-to-r from-red-500 to-orange-400"
            }`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
      </div>

      {/* Gemini Assessment */}
      {opp.gemini_novelty_assessment && (
        <div className="mb-4 rounded-lg bg-gray-800/40 p-3">
          <p className="text-xs text-gray-500 mb-1 font-medium">
            AI Assessment
          </p>
          <p className="text-sm text-gray-300 leading-relaxed">
            {opp.gemini_novelty_assessment.length > 300
              ? opp.gemini_novelty_assessment.slice(0, 300) + "…"
              : opp.gemini_novelty_assessment}
          </p>
        </div>
      )}

      {/* Prior Art table */}
      {opp.nearest_patent_titles.length > 0 && (
        <div className="mb-4">
          <p className="text-xs text-gray-500 mb-2 font-medium">
            Nearest Prior Art
          </p>
          <div className="space-y-1.5">
            {opp.nearest_patent_titles.slice(0, 3).map((title, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-xs text-gray-400"
              >
                <span className="font-mono text-blue-400 shrink-0">
                  {opp.nearest_patent_ids[i]
                    ? opp.nearest_patent_ids[i].slice(0, 15)
                    : `#${i + 1}`}
                </span>
                <span className="truncate">{title}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* IPC codes */}
      {opp.ipc_whitespace_codes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {opp.ipc_whitespace_codes.map((code) => (
            <span
              key={code}
              className="px-2 py-0.5 rounded bg-gray-800 text-xs text-gray-400 font-mono"
            >
              {code}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
