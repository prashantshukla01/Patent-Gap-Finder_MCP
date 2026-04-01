import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" })

export const metadata: Metadata = {
  title: "Patent Gap Finder — Discover White-Space Opportunities",
  description:
    "AI-powered patent landscape analysis. Upload a research paper and discover patentable white-space opportunities with USPTO-format claim drafting.",
  keywords: [
    "patent analysis",
    "white-space detection",
    "prior art search",
    "patent claims",
    "research paper",
  ],
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} font-sans antialiased bg-gray-950 text-gray-100 min-h-screen`}
      >
        <header className="sticky top-0 z-50 border-b border-gray-800/60 bg-gray-950/80 backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
            <a href="/" className="flex items-center gap-2.5 group">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-blue-500/20 group-hover:shadow-blue-500/40 transition-shadow">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-white"
                >
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <span className="text-lg font-semibold tracking-tight">
                Patent Gap Finder
              </span>
            </a>

            <nav className="flex items-center gap-4">
              <a
                href="https://github.com/prashantshukla01/Patent-Gap-Finder"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
              >
                GitHub
              </a>
              <div className="h-4 w-px bg-gray-700" />
              <span className="text-xs font-mono text-gray-500">v1.0.0</span>
            </nav>
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>

        <footer className="border-t border-gray-800/40 mt-20">
          <div className="mx-auto max-w-7xl px-6 py-6 flex items-center justify-between text-xs text-gray-500">
            <span>© 2026 Patent Gap Finder. For research purposes only.</span>
            <span className="font-mono">Powered by Gemini + FastMCP</span>
          </div>
        </footer>
      </body>
    </html>
  )
}
