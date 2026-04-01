"use client"

import { useState } from "react"
import type { ClaimSet } from "@/lib/types"

interface Props {
  claimSet: ClaimSet
  index: number
}

export function ClaimDraft({ claimSet: cs, index }: Props) {
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const formattedClaims = cs.claims
    .map((c) => {
      const lines = c.claim_text.split("\n")
      const indented = lines
        .map((l, i) => (i === 0 ? l : "   " + l))
        .join("\n")
      return `${c.claim_number}. ${indented}`
    })
    .join("\n\n")

  const fullText = `CLAIMS\n\n${formattedClaims}`

  const handleCopy = async () => {
    await navigator.clipboard.writeText(fullText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const independentCount = cs.claims.filter(
    (c) => c.claim_type === "independent",
  ).length
  const dependentCount = cs.claims.filter(
    (c) => c.claim_type === "dependent",
  ).length

  return (
    <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-800/40 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">
            Claim Set #{index + 1}
          </h3>
          <p className="text-xs text-gray-500 mt-1 max-w-lg truncate">
            {cs.claim_text_original}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs font-mono text-amber-300 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded">
            {cs.recommended_scope}
          </span>
          <span className="text-xs font-mono text-green-300 bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded">
            {(cs.novelty_score * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Stats bar */}
      <div className="px-6 py-2.5 bg-gray-800/20 flex items-center gap-4 text-xs text-gray-500">
        <span>
          {independentCount} independent · {dependentCount} dependent
        </span>
        <span className="text-gray-700">|</span>
        <span>
          Category: {cs.claims[0]?.patent_claim_category ?? "method"}
        </span>
        {cs.ipc_codes.length > 0 && (
          <>
            <span className="text-gray-700">|</span>
            <span className="font-mono">{cs.ipc_codes.join(", ")}</span>
          </>
        )}
      </div>

      {/* Claims body */}
      <div className="px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {expanded ? "Collapse claims ▲" : "Expand claims ▼"}
          </button>
          <button
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors"
          >
            {copied ? (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  className="h-3.5 w-3.5 text-green-400"
                >
                  <path
                    fillRule="evenodd"
                    d="M12.416 3.376a.75.75 0 01.208 1.04l-5 7.5a.75.75 0 01-1.154.114l-3-3a.75.75 0 011.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 011.04-.207z"
                    clipRule="evenodd"
                  />
                </svg>
                Copied!
              </>
            ) : (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  className="h-3.5 w-3.5"
                >
                  <path d="M5.5 3.5A1.5 1.5 0 017 2h2.879a1.5 1.5 0 011.06.44l2.122 2.12a1.5 1.5 0 01.439 1.061V9.5A1.5 1.5 0 0112 11V8.621a3 3 0 00-.879-2.121L9 4.379A3 3 0 006.879 3.5H5.5z" />
                  <path d="M4 5a1.5 1.5 0 00-1.5 1.5v6A1.5 1.5 0 004 14h5a1.5 1.5 0 001.5-1.5V8.621a1.5 1.5 0 00-.44-1.06L7.94 5.439A1.5 1.5 0 006.878 5H4z" />
                </svg>
                Copy
              </>
            )}
          </button>
        </div>

        {expanded && (
          <pre className="text-xs font-mono text-gray-300 bg-gray-950/50 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed border border-gray-800/40">
            {fullText}
          </pre>
        )}

        {!expanded && cs.claims.length > 0 && (
          <pre className="text-xs font-mono text-gray-400 bg-gray-950/50 rounded-lg p-4 overflow-hidden whitespace-pre-wrap leading-relaxed border border-gray-800/40 max-h-24 relative">
            {`1. ${cs.claims[0].claim_text}`}
            <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-gray-950/90 to-transparent" />
          </pre>
        )}
      </div>

      {/* Distinguishing features */}
      {cs.distinguishing_features.length > 0 && (
        <div className="px-6 py-3 border-t border-gray-800/30">
          <p className="text-xs text-gray-500 mb-1.5 font-medium">
            Distinguishing Features
          </p>
          <ul className="space-y-1">
            {cs.distinguishing_features.map((f, i) => (
              <li key={i} className="text-xs text-gray-400 flex gap-1.5">
                <span className="text-green-400 shrink-0">•</span>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Disclaimer */}
      <div className="px-6 py-3 bg-amber-500/5 border-t border-amber-500/10">
        <p className="text-[10px] text-amber-400/60 leading-relaxed">
          {cs.gemini_disclaimer}
        </p>
      </div>
    </div>
  )
}
