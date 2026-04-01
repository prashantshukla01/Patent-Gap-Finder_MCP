"use client"

import { useEffect, useState, useCallback } from "react"
import { getSession } from "@/lib/api"
import type { GetSessionResponse } from "@/lib/types"

interface UseSessionReturn {
  session: GetSessionResponse | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

/**
 * Hook that fetches and optionally polls a session by ID.
 *
 * @param sessionId - UUID of the session
 * @param pollIntervalMs - if > 0, re-fetches on this interval (stops when status === "complete")
 */
export function useSession(
  sessionId: string | null,
  pollIntervalMs = 0,
): UseSessionReturn {
  const [session, setSession] = useState<GetSessionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchSession = useCallback(async () => {
    if (!sessionId) return
    try {
      const data = await getSession(sessionId)
      setSession(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch session")
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  // Initial fetch
  useEffect(() => {
    if (!sessionId) {
      setLoading(false)
      return
    }
    setLoading(true)
    fetchSession()
  }, [sessionId, fetchSession])

  // Polling
  useEffect(() => {
    if (!sessionId || pollIntervalMs <= 0) return
    if (session?.status === "complete") return

    const timer = setInterval(fetchSession, pollIntervalMs)
    return () => clearInterval(timer)
  }, [sessionId, pollIntervalMs, session?.status, fetchSession])

  return { session, loading, error, refresh: fetchSession }
}
