"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import dynamic from "next/dynamic"
import { getSession } from "@/lib/api"
import { SessionSummary } from "@/components/SessionSummary"
import { OpportunityCard } from "@/components/OpportunityCard"
import { ClaimDraft } from "@/components/ClaimDraft"
import type {
  GetSessionResponse,
  WhitespaceOpportunity,
  ClusterInfo,
  Patent,
  ClaimSet,
} from "@/lib/types"
import { downloadReport } from "@/lib/api"

// D3 uses window — must disable SSR
const PatentLandscape = dynamic(
  () =>
    import("@/components/PatentLandscape").then((m) => m.PatentLandscape),
  { ssr: false },
)

type Tab = "opportunities" | "claims" | "prior-art"

export default function SessionPage() {
  const { id } = useParams<{ id: string }>()
  const [session, setSession] = useState<GetSessionResponse | null>(null)
  const [opportunities, setOpportunities] = useState<WhitespaceOpportunity[]>(
    [],
  )
  const [clusters, setClusters] = useState<ClusterInfo[]>([])
  const [claimSets, setClaimSets] = useState<ClaimSet[]>([])
  const [patents, setPatents] = useState<Patent[]>([])
  const [activeTab, setActiveTab] = useState<Tab>("opportunities")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    if (!id) return
    ;(async () => {
      try {
        const data = await getSession(id)
        setSession(data)

        // Extract nested data from the session response
        // Opportunities come from whitespace analysis
        if (data.whitespace_opportunities) {
          setOpportunities(data.whitespace_opportunities)
        }

        // Clusters from landscape jobs
        if (data.landscape_jobs && data.landscape_jobs.length > 0) {
          const latestJob = data.landscape_jobs[data.landscape_jobs.length - 1]
          if (latestJob.cluster_records) {
            setClusters(
              latestJob.cluster_records.map((cr: ClusterInfo) => ({
                cluster_id: cr.cluster_id,
                label: cr.label ?? "",
                technical_domain: cr.technical_domain ?? "",
                patent_count: cr.patent_count,
                centroid_patent_ids: cr.centroid_patent_ids ?? [],
                avg_internal_similarity: cr.avg_internal_similarity ?? 0,
                representative_titles: [],
              })),
            )
          }
        }

        // Claim sets from drafted claims
        if (data.claim_sets) {
          setClaimSets(data.claim_sets)
        }

        // Patents
        if (data.patents) {
          setPatents(data.patents)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load session")
      } finally {
        setLoading(false)
      }
    })()
  }, [id])

  const handleDownload = async () => {
    if (!id) return
    setDownloading(true)
    try {
      await downloadReport(id)
    } catch {
      alert("Failed to download report. Please try again.")
    } finally {
      setDownloading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <span className="text-sm text-gray-400">Loading session…</span>
        </div>
      </div>
    )
  }

  if (error || !session) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-3">
          <p className="text-red-400 text-sm">{error ?? "Session not found"}</p>
          <a
            href="/"
            className="text-sm text-blue-400 hover:underline underline-offset-4"
          >
            ← Back to home
          </a>
        </div>
      </div>
    )
  }

  const tabs: { key: Tab; label: string; count?: number }[] = [
    {
      key: "opportunities",
      label: "Opportunities",
      count: opportunities.length,
    },
    { key: "claims", label: "Drafted Claims", count: claimSets.length },
    { key: "prior-art", label: "Prior Art", count: patents.length },
  ]

  return (
    <div className="space-y-10">
      {/* Summary cards */}
      <SessionSummary session={session} />

      {/* Download button */}
      <div className="flex justify-end">
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium hover:from-blue-500 hover:to-blue-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30"
        >
          {downloading ? (
            <>
              <span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-4 w-4"
              >
                <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
                <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
              </svg>
              Download PDF Report
            </>
          )}
        </button>
      </div>

      {/* Patent Landscape visualization */}
      {clusters.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-gray-200 mb-4">
            Patent Landscape
          </h2>
          <PatentLandscape
            clusters={clusters}
            opportunities={opportunities}
          />
        </section>
      )}

      {/* Tabs */}
      <div>
        <div className="flex gap-1 border-b border-gray-800">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
                activeTab === t.key
                  ? "text-blue-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {t.label}
              {t.count != null && t.count > 0 && (
                <span className="ml-1.5 text-xs bg-gray-800 px-1.5 py-0.5 rounded-full">
                  {t.count}
                </span>
              )}
              {activeTab === t.key && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 rounded-full" />
              )}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {activeTab === "opportunities" && (
            <div className="space-y-4">
              {opportunities.length === 0 ? (
                <p className="text-gray-500 text-sm text-center py-12">
                  No whitespace opportunities found for this session.
                </p>
              ) : (
                opportunities
                  .sort((a, b) => b.novelty_score - a.novelty_score)
                  .map((opp) => (
                    <OpportunityCard key={opp.opportunity_id} opportunity={opp} />
                  ))
              )}
            </div>
          )}

          {activeTab === "claims" && (
            <div className="space-y-6">
              {claimSets.length === 0 ? (
                <p className="text-gray-500 text-sm text-center py-12">
                  No drafted claims yet. Run the claim drafting pipeline first.
                </p>
              ) : (
                claimSets.map((cs, i) => (
                  <ClaimDraft key={cs.opportunity_id} claimSet={cs} index={i} />
                ))
              )}
            </div>
          )}

          {activeTab === "prior-art" && (
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-900/80 text-gray-400 text-left">
                    <th className="px-4 py-3 font-medium">Patent ID</th>
                    <th className="px-4 py-3 font-medium">Title</th>
                    <th className="px-4 py-3 font-medium">Assignee</th>
                    <th className="px-4 py-3 font-medium">Source</th>
                    <th className="px-4 py-3 font-medium text-right">
                      Similarity
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60">
                  {patents.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-4 py-12 text-center text-gray-500"
                      >
                        No patents retrieved yet.
                      </td>
                    </tr>
                  ) : (
                    patents
                      .sort(
                        (a, b) =>
                          (b.abstract_similarity ?? 0) -
                          (a.abstract_similarity ?? 0),
                      )
                      .map((p) => (
                        <tr
                          key={p.patent_id}
                          className="hover:bg-gray-900/40 transition-colors"
                        >
                          <td className="px-4 py-3 font-mono text-xs text-blue-400">
                            {p.source_url ? (
                              <a
                                href={p.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="hover:underline"
                              >
                                {p.patent_id}
                              </a>
                            ) : (
                              p.patent_id
                            )}
                          </td>
                          <td className="px-4 py-3 max-w-xs truncate text-gray-300">
                            {p.title}
                          </td>
                          <td className="px-4 py-3 text-gray-400">
                            {p.assignee ?? "—"}
                          </td>
                          <td className="px-4 py-3">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-300 uppercase tracking-wider">
                              {p.source}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs">
                            {p.abstract_similarity != null
                              ? (p.abstract_similarity * 100).toFixed(1) + "%"
                              : "—"}
                          </td>
                        </tr>
                      ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
