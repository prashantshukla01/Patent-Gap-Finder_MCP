"use client"

import type { PipelineStep } from "@/lib/types"

interface Props {
  step: PipelineStep
  error: string | null
  stepDetails: Record<string, string | null>
}

const STEPS: {
  key: PipelineStep
  label: string
  icon: string
}[] = [
  { key: "parsing", label: "Parsing Paper", icon: "📄" },
  { key: "classifying", label: "IPC Classification", icon: "🏷️" },
  { key: "searching", label: "Prior Art Search", icon: "🔍" },
  { key: "mapping", label: "Landscape Mapping", icon: "🗺️" },
  { key: "analyzing", label: "White-space Analysis", icon: "🧠" },
  { key: "drafting", label: "Drafting Claims", icon: "📝" },
]

const ORDER: PipelineStep[] = [
  "idle",
  "parsing",
  "extracting",
  "classifying",
  "searching",
  "mapping",
  "analyzing",
  "drafting",
  "complete",
]

function getStepIndex(s: PipelineStep): number {
  return ORDER.indexOf(s)
}

export function PipelineStatus({ step, error, stepDetails }: Props) {
  const currentIdx = getStepIndex(step)

  return (
    <div className="rounded-2xl border border-gray-800/60 bg-gray-900/30 p-8">
      <h2 className="text-lg font-semibold text-gray-200 mb-6">
        Analysis Pipeline
      </h2>

      <div className="space-y-1">
        {STEPS.map((s, i) => {
          const stepIdx = getStepIndex(s.key)
          const isComplete = step === "complete" || currentIdx > stepIdx
          const isActive = step === s.key || (s.key === "classifying" && step === "extracting")
          const isFailed = error !== null && isActive

          return (
            <div key={s.key} className="flex items-start gap-4">
              {/* Connector + Circle */}
              <div className="flex flex-col items-center">
                <div
                  className={`h-9 w-9 rounded-full flex items-center justify-center text-sm shrink-0 transition-all duration-500 ${
                    isFailed
                      ? "bg-red-500/20 border-2 border-red-500"
                      : isComplete
                        ? "bg-green-500/20 border-2 border-green-500"
                        : isActive
                          ? "bg-blue-500/20 border-2 border-blue-500 animate-pulse"
                          : "bg-gray-800/60 border-2 border-gray-700"
                  }`}
                >
                  {isFailed ? (
                    <span className="text-red-400 text-xs font-bold">✕</span>
                  ) : isComplete ? (
                    <span className="text-green-400 text-xs font-bold">✓</span>
                  ) : (
                    <span>{s.icon}</span>
                  )}
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={`w-0.5 h-6 transition-colors duration-500 ${
                      isComplete ? "bg-green-500/40" : "bg-gray-800"
                    }`}
                  />
                )}
              </div>

              {/* Text */}
              <div className="pt-1.5">
                <span
                  className={`text-sm font-medium transition-colors ${
                    isFailed
                      ? "text-red-400"
                      : isComplete
                        ? "text-green-300"
                        : isActive
                          ? "text-blue-300"
                          : "text-gray-500"
                  }`}
                >
                  {s.label}
                </span>
                {/* Sub-detail */}
                {stepDetails[s.key] && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    {stepDetails[s.key]}
                  </p>
                )}
                {isFailed && error && (
                  <p className="text-xs text-red-400/80 mt-0.5">{error}</p>
                )}
                {isActive && !isFailed && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    Processing…
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {step === "complete" && (
        <div className="mt-6 flex items-center gap-2 text-sm text-green-400 bg-green-500/10 px-4 py-3 rounded-lg border border-green-500/20">
          <span className="text-base">🎉</span>
          Analysis complete! Redirecting to results…
        </div>
      )}
    </div>
  )
}
