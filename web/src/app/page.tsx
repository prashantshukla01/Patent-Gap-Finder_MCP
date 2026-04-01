"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { UploadForm } from "@/components/UploadForm"
import { PipelineStatus } from "@/components/PipelineStatus"
import { usePipeline } from "@/hooks/usePipeline"

export default function HomePage() {
  const router = useRouter()
  const { step, sessionId, error, stepDetails, runPipeline } = usePipeline()
  const [started, setStarted] = useState(false)

  const handleSubmit = async (source: string) => {
    setStarted(true)
    await runPipeline(source)
  }

  // Redirect to session page once pipeline completes
  useEffect(() => {
    if (step === "complete" && sessionId) {
      router.push(`/session/${sessionId}`)
    }
  }, [step, sessionId, router])

  return (
    <div className="flex flex-col items-center">
      {/* Hero Section */}
      <section className="mt-12 mb-16 text-center max-w-3xl">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium mb-6">
          <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
          AI-Powered Patent Analysis
        </div>
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight bg-gradient-to-b from-white to-gray-400 bg-clip-text text-transparent leading-tight">
          Find what&apos;s worth patenting
          <br />
          in your research
        </h1>
        <p className="mt-5 text-lg text-gray-400 max-w-xl mx-auto leading-relaxed">
          Upload a research paper or paste an arXiv URL. We analyze the patent
          landscape, detect white-space opportunities, and draft USPTO-format
          claims — all in minutes.
        </p>
      </section>

      {/* Upload + Pipeline */}
      <section className="w-full max-w-2xl">
        {!started ? (
          <UploadForm onSubmit={handleSubmit} />
        ) : (
          <div className="space-y-8">
            <PipelineStatus
              step={step}
              error={error}
              stepDetails={stepDetails}
            />
            {error && (
              <button
                onClick={() => {
                  setStarted(false)
                }}
                className="mx-auto block text-sm text-blue-400 hover:text-blue-300 underline underline-offset-4 transition-colors"
              >
                Try again with a different paper
              </button>
            )}
          </div>
        )}
      </section>

      {/* Features row */}
      <section className="mt-24 grid gap-6 sm:grid-cols-3 w-full max-w-4xl">
        {[
          {
            icon: "🔍",
            title: "Multi-Source Search",
            desc: "Searches USPTO, EPO, and Google Patents simultaneously for comprehensive prior art coverage.",
          },
          {
            icon: "🧠",
            title: "AI-Driven Analysis",
            desc: "Gemini-powered claim extraction, IPC classification, and novelty assessment.",
          },
          {
            icon: "📝",
            title: "USPTO Claim Drafts",
            desc: "Auto-generates properly formatted independent and dependent patent claims.",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="rounded-xl border border-gray-800/60 bg-gray-900/40 p-6 hover:border-gray-700/80 hover:bg-gray-900/60 transition-all group"
          >
            <span className="text-2xl">{f.icon}</span>
            <h3 className="mt-3 font-semibold text-sm text-gray-200 group-hover:text-white transition-colors">
              {f.title}
            </h3>
            <p className="mt-1.5 text-sm text-gray-500 leading-relaxed">
              {f.desc}
            </p>
          </div>
        ))}
      </section>
    </div>
  )
}
