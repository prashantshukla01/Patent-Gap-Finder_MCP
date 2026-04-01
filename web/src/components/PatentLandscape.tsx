"use client"

import { useEffect, useRef, useState } from "react"
import * as d3 from "d3"
import type { ClusterInfo, WhitespaceOpportunity } from "@/lib/types"

const COLORS = [
  "#4a9eed", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
  "#06b6d4", "#f97316", "#ec4899", "#14b8a6",
]

interface Props {
  clusters: ClusterInfo[]
  opportunities: WhitespaceOpportunity[]
}

interface ClusterNode extends ClusterInfo {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  color: string
}

interface OppNode {
  opportunity_id: string
  claim_text: string
  novelty_score: number
  nearest_cluster_label: string
  x: number
  y: number
  vx: number
  vy: number
}

export function PatentLandscape({ clusters, opportunities }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const [selectedCluster, setSelectedCluster] = useState<ClusterInfo | null>(null)

  useEffect(() => {
    if (!svgRef.current || clusters.length === 0) return

    const width = 800
    const height = 500
    const svg = d3.select(svgRef.current)
    svg.selectAll("*").remove()

    const maxPatents = d3.max(clusters, (d) => d.patent_count) ?? 1
    const rScale = d3
      .scaleSqrt()
      .domain([0, maxPatents])
      .range([20, 70])

    const clusterNodes: ClusterNode[] = clusters.map((c, i) => ({
      ...c,
      x: width / 2 + (Math.random() - 0.5) * 200,
      y: height / 2 + (Math.random() - 0.5) * 200,
      vx: 0,
      vy: 0,
      radius: rScale(c.patent_count),
      color: COLORS[i % COLORS.length],
    }))

    const oppNodes: OppNode[] = opportunities
      .filter((o) => o.is_whitespace)
      .map((o) => ({
        opportunity_id: o.opportunity_id,
        claim_text: o.claim_text,
        novelty_score: o.novelty_score,
        nearest_cluster_label: o.nearest_cluster_label,
        x: width / 2 + (Math.random() - 0.5) * 100,
        y: height / 2 + (Math.random() - 0.5) * 100,
        vx: 0,
        vy: 0,
      }))

    // Force simulation for clusters
    const simulation = d3
      .forceSimulation<ClusterNode>(clusterNodes)
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collide",
        d3.forceCollide<ClusterNode>((d) => d.radius + 8).strength(0.8),
      )
      .force("x", d3.forceX(width / 2).strength(0.05))
      .force("y", d3.forceY(height / 2).strength(0.05))
      .on("tick", ticked)

    // Defs for gradients
    const defs = svg.append("defs")
    clusterNodes.forEach((cn) => {
      const grad = defs
        .append("radialGradient")
        .attr("id", `grad-${cn.cluster_id}`)
      grad
        .append("stop")
        .attr("offset", "0%")
        .attr("stop-color", cn.color)
        .attr("stop-opacity", 0.4)
      grad
        .append("stop")
        .attr("offset", "100%")
        .attr("stop-color", cn.color)
        .attr("stop-opacity", 0.1)
    })

    // Cluster bubbles
    const bubbles = svg
      .append("g")
      .selectAll<SVGCircleElement, ClusterNode>("circle")
      .data(clusterNodes)
      .join("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => `url(#grad-${d.cluster_id})`)
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.6)
      .attr("cursor", "pointer")
      .on("mouseover", function (event, d) {
        d3.select(this)
          .transition()
          .duration(200)
          .attr("stroke-width", 3)
          .attr("stroke-opacity", 1)
        showTooltip(event, d)
      })
      .on("mouseout", function () {
        d3.select(this)
          .transition()
          .duration(200)
          .attr("stroke-width", 1.5)
          .attr("stroke-opacity", 0.6)
        hideTooltip()
      })
      .on("click", (_, d) => setSelectedCluster(d))

    // Cluster labels
    const labels = svg
      .append("g")
      .selectAll<SVGTextElement, ClusterNode>("text")
      .data(clusterNodes)
      .join("text")
      .text((d) => d.label || `Cluster ${d.cluster_id}`)
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("font-size", 10)
      .attr("fill", "#e5e7eb")
      .attr("pointer-events", "none")
      .each(function (d) {
        // Truncate labels that are wider than the bubble
        const maxWidth = d.radius * 1.6
        let text = d.label || `Cluster ${d.cluster_id}`
        while (
          this.getComputedTextLength &&
          this.getComputedTextLength() > maxWidth &&
          text.length > 3
        ) {
          text = text.slice(0, -4) + "…"
          d3.select(this).text(text)
        }
      })

    // Whitespace opportunity dots
    const dots = svg
      .append("g")
      .selectAll<SVGCircleElement, OppNode>("circle")
      .data(oppNodes)
      .join("circle")
      .attr("r", 5)
      .attr("fill", "#ef4444")
      .attr("stroke", "#ef4444")
      .attr("stroke-width", 2)
      .attr("stroke-opacity", 0.4)
      .attr("opacity", 0.9)
      .on("mouseover", function (event, d) {
        d3.select(this).transition().duration(200).attr("r", 8)
        showOppTooltip(event, d)
      })
      .on("mouseout", function () {
        d3.select(this).transition().duration(200).attr("r", 5)
        hideTooltip()
      })

    // Pulse animation for opportunity dots
    function pulse() {
      dots
        .transition()
        .duration(1000)
        .attr("stroke-opacity", 0.8)
        .attr("stroke-width", 6)
        .transition()
        .duration(1000)
        .attr("stroke-opacity", 0.2)
        .attr("stroke-width", 2)
        .on("end", pulse)
    }
    pulse()

    function ticked() {
      bubbles.attr("cx", (d) => d.x).attr("cy", (d) => d.y)
      labels.attr("x", (d) => d.x).attr("y", (d) => d.y)

      // Position opp dots near their nearest cluster
      dots.attr("cx", (d) => {
        const parent = clusterNodes.find(
          (c) => c.label === d.nearest_cluster_label,
        )
        if (parent) {
          const angle = Math.random() * Math.PI * 2
          d.x = parent.x + (parent.radius + 15) * Math.cos(angle)
        }
        return d.x
      }).attr("cy", (d) => {
        const parent = clusterNodes.find(
          (c) => c.label === d.nearest_cluster_label,
        )
        if (parent) {
          const angle = Math.random() * Math.PI * 2
          d.y = parent.y + (parent.radius + 15) * Math.sin(angle)
        }
        return d.y
      })
    }

    function showTooltip(event: MouseEvent, d: ClusterNode) {
      const tip = tooltipRef.current
      if (!tip) return
      tip.innerHTML = `
        <div class="font-semibold text-sm">${d.label || `Cluster ${d.cluster_id}`}</div>
        <div class="text-xs text-gray-400 mt-1">${d.technical_domain}</div>
        <div class="text-xs mt-1">${d.patent_count} patents</div>
        <div class="text-xs text-gray-500">Avg similarity: ${(d.avg_internal_similarity * 100).toFixed(0)}%</div>
      `
      tip.style.display = "block"
      tip.style.left = event.offsetX + 12 + "px"
      tip.style.top = event.offsetY - 10 + "px"
    }

    function showOppTooltip(event: MouseEvent, d: OppNode) {
      const tip = tooltipRef.current
      if (!tip) return
      const truncated =
        d.claim_text.length > 100
          ? d.claim_text.slice(0, 100) + "…"
          : d.claim_text
      tip.innerHTML = `
        <div class="font-semibold text-sm text-red-300">⚡ Whitespace Opportunity</div>
        <div class="text-xs mt-1 max-w-[250px]">${truncated}</div>
        <div class="text-xs mt-1">Novelty: <span class="font-mono text-green-300">${(d.novelty_score * 100).toFixed(0)}%</span></div>
      `
      tip.style.display = "block"
      tip.style.left = event.offsetX + 12 + "px"
      tip.style.top = event.offsetY - 10 + "px"
    }

    function hideTooltip() {
      const tip = tooltipRef.current
      if (tip) tip.style.display = "none"
    }

    return () => {
      simulation.stop()
    }
  }, [clusters, opportunities])

  return (
    <div className="relative">
      <div className="relative overflow-hidden rounded-xl border border-gray-800/60 bg-gray-900/30">
        <svg
          ref={svgRef}
          viewBox="0 0 800 500"
          className="w-full h-auto"
          style={{ minHeight: 300 }}
        />
        <div
          ref={tooltipRef}
          className="absolute pointer-events-none hidden bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 shadow-xl z-10"
          style={{ display: "none" }}
        />
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-400">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-blue-400/30 border border-blue-400" />
          Patent Cluster
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
          Whitespace Opportunity
        </div>
        <span className="text-gray-600">|</span>
        <span>Bubble size = patent count</span>
      </div>

      {/* Selected cluster detail */}
      {selectedCluster && (
        <div className="mt-4 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-200">
              {selectedCluster.label || `Cluster ${selectedCluster.cluster_id}`}
            </h3>
            <button
              onClick={() => setSelectedCluster(null)}
              className="text-gray-500 hover:text-gray-300 text-xs"
            >
              Close ✕
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-gray-500">Domain:</span>{" "}
              <span className="text-gray-300">
                {selectedCluster.technical_domain}
              </span>
            </div>
            <div>
              <span className="text-gray-500">Patents:</span>{" "}
              <span className="text-gray-300">
                {selectedCluster.patent_count}
              </span>
            </div>
          </div>
          {selectedCluster.representative_titles.length > 0 && (
            <div className="mt-3">
              <p className="text-xs text-gray-500 mb-1">Top patents:</p>
              <ul className="space-y-1">
                {selectedCluster.representative_titles.slice(0, 5).map((t, i) => (
                  <li key={i} className="text-xs text-gray-400 truncate">
                    • {t}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
