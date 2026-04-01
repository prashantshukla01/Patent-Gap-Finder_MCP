"use client"

import { useState, useCallback } from "react"
import {
  parsePaper,
  classifyIPC,
  searchPriorArt,
  getSearchStatus,
  mapLandscape,
  findWhitespace,
  draftClaims,
} from "@/lib/api"
import type { PipelineStep } from "@/lib/types"

interface UsePipelineReturn {
  step: PipelineStep
  sessionId: string | null
  error: string | null
  stepDetails: Record<string, string | null>
  runPipeline: (source: string) => Promise<void>
}

/**
 * Orchestrates the full 6-step analysis pipeline with status tracking.
 */
export function usePipeline(): UsePipelineReturn {
  const [step, setStep] = useState<PipelineStep>("idle")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stepDetails, setStepDetails] = useState<Record<string, string | null>>(
    {},
  )

  const detail = (key: string, value: string) => {
    setStepDetails((prev) => ({ ...prev, [key]: value }))
  }

  const runPipeline = useCallback(async (source: string) => {
    setError(null)
    setStepDetails({})

    try {
      // Step 1: Parse paper
      setStep("parsing")
      const parsed = await parsePaper(source, true)
      const sid = parsed.session_id
      setSessionId(sid)
      detail("parsing", `${parsed.claims_extracted} claims extracted`)

      // Step 2: Classify IPC
      setStep("classifying")
      const classified = await classifyIPC(sid)
      detail(
        "classifying",
        `${classified.top_ipc_codes.length} IPC codes assigned`,
      )

      // Step 3: Search prior art
      setStep("searching")
      const searchResult = await searchPriorArt(sid)
      const jobId = searchResult.job_id

      // Poll until search completes
      let searchDone = false
      const maxPollAttempts = 60 // 5 minutes at 5s intervals
      let attempts = 0

      while (!searchDone && attempts < maxPollAttempts) {
        await sleep(5000)
        attempts++

        const status = await getSearchStatus(jobId)
        if (status.status === "complete") {
          searchDone = true
          detail(
            "searching",
            `Found ${status.result_count ?? 0} patents (${status.duration_seconds?.toFixed(1)}s)`,
          )
        } else if (status.status === "failed") {
          throw new Error(status.error_message ?? "Prior art search failed")
        } else {
          detail("searching", `Searching… (${attempts * 5}s)`)
        }
      }

      if (!searchDone) {
        throw new Error("Prior art search timed out after 5 minutes")
      }

      // Step 4: Map landscape
      setStep("mapping")
      const landscape = await mapLandscape(sid)
      detail(
        "mapping",
        `${landscape.n_clusters} clusters from ${landscape.total_patents_embedded} patents`,
      )

      // Step 5: Find whitespace
      setStep("analyzing")
      const whitespace = await findWhitespace(sid, 0.5)
      detail(
        "analyzing",
        `${whitespace.whitespace_opportunities.length} opportunities found`,
      )

      // Step 6: Draft claims
      setStep("drafting")
      const drafts = await draftClaims(sid, 0.5)
      detail("drafting", `${drafts.total_claim_sets} claim sets drafted`)

      // Done
      setStep("complete")
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Pipeline failed"
      setError(msg)
      setStep("error")
    }
  }, [])

  return { step, sessionId, error, stepDetails, runPipeline }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
