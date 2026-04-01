"use client"

import { useState, useRef } from "react"

interface Props {
  onSubmit: (source: string) => void
}

export function UploadForm({ onSubmit }: Props) {
  const [mode, setMode] = useState<"url" | "file">("url")
  const [url, setUrl] = useState("")
  const [fileName, setFileName] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (file: File | null) => {
    if (!file) return
    setFileName(file.name)
    // For now we pass a file path; in production this would upload to a temp endpoint
    // and return a URL. We use the file name as a placeholder.
    const reader = new FileReader()
    reader.onload = () => {
      // Store the data URL temporarily
      if (reader.result) {
        setUrl(reader.result as string)
        setMode("file")
      }
    }
    reader.readAsDataURL(file)
  }

  const handleSubmit = () => {
    if (mode === "url" && url.trim()) {
      onSubmit(url.trim())
    } else if (mode === "file" && url) {
      onSubmit(url)
    }
  }

  const isValid = url.trim().length > 0

  return (
    <div className="rounded-2xl border border-gray-800/60 bg-gray-900/30 p-8 backdrop-blur-sm">
      {/* Mode toggle */}
      <div className="flex gap-1 p-1 bg-gray-800/50 rounded-lg w-fit mb-6">
        <button
          onClick={() => setMode("url")}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
            mode === "url"
              ? "bg-gray-700 text-white shadow-sm"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          arXiv URL
        </button>
        <button
          onClick={() => setMode("file")}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
            mode === "file"
              ? "bg-gray-700 text-white shadow-sm"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          Upload PDF
        </button>
      </div>

      {mode === "url" ? (
        <div className="space-y-2">
          <label className="block text-sm text-gray-400">
            arXiv URL or Paper URL
          </label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://arxiv.org/abs/2005.14165"
            className="w-full rounded-lg border border-gray-700/60 bg-gray-800/40 px-4 py-3 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30 transition-all"
          />
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file?.type === "application/pdf") handleFileChange(file)
          }}
          onClick={() => fileRef.current?.click()}
          className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12 cursor-pointer transition-all ${
            dragging
              ? "border-blue-500 bg-blue-500/5"
              : fileName
                ? "border-green-500/40 bg-green-500/5"
                : "border-gray-700 hover:border-gray-600 bg-gray-800/20"
          }`}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
          />
          {fileName ? (
            <>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-8 w-8 text-green-400 mb-2"
              >
                <path
                  fillRule="evenodd"
                  d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                  clipRule="evenodd"
                />
              </svg>
              <span className="text-sm text-green-300">{fileName}</span>
              <span className="text-xs text-gray-500 mt-1">
                Click to change
              </span>
            </>
          ) : (
            <>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-8 w-8 text-gray-500 mb-2"
              >
                <path d="M9.25 13.25a.75.75 0 001.5 0V4.636l2.955 3.129a.75.75 0 001.09-1.03l-4.25-4.5a.75.75 0 00-1.09 0l-4.25 4.5a.75.75 0 101.09 1.03L9.25 4.636v8.614z" />
                <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
              </svg>
              <span className="text-sm text-gray-400">
                Drop a PDF here or click to browse
              </span>
            </>
          )}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={!isValid}
        className="mt-6 w-full rounded-lg bg-gradient-to-r from-blue-600 to-cyan-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/20 hover:shadow-blue-500/40 hover:from-blue-500 hover:to-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:shadow-blue-500/20 transition-all"
      >
        Analyze Paper
      </button>
    </div>
  )
}
