import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import ForceGraph2D from "react-force-graph-2d";
import { apiFetch } from "../api/client";

function getNodeColor(node) {
  if (node.frozen) return "#38BDF8"; // ice-blue for frozen
  if (node.__dimmed) return "rgba(55, 65, 100, 0.35)";

  const risk = Number(node.risk ?? 0);
  if (risk >= 0.85) return "#EF4444"; // red
  if (risk >= 0.65) return "#F59E0B"; // yellow
  if (risk >= 0.4) return "#EAB308"; // amber
  return "#60A5FA"; // calm blue
}

function getNodeVal(node) {
  const vol = Number(node.volume || node.in_amount || 50000);
  const size = Math.max(3.5, Math.min(14, Math.log10(vol + 1) * 2));
  if (node.__isCluster) return size * 1.5;
  return size;
}

export default function GraphView({
  selectedClusterId,
  selectedNodeId,
  lastAlertId,
  isRedAlertFlashing,
  onSelectNode,
  onClearSelection,
  onToast,
}) {
  const [is2D, setIs2D] = useState(false);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [isLoading, setIsLoading] = useState(true);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  const graphRef = useRef();
  const containerRef = useRef(null);
  const existingNodesRef = useRef(new Map());
  const isSelectedClusterRef = useRef(selectedClusterId);
  isSelectedClusterRef.current = selectedClusterId;

  // Track the last cluster/alert we auto-centered on so 3s polling never causes jumps
  const lastCenteringTargetRef = useRef(null);

  // ResizeObserver for exact container sizing
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setDimensions({ width: Math.floor(width), height: Math.floor(height) });
        }
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Center camera on a specific cluster's bounding centroid
  const centerOnCluster = useCallback(
    (clusterId) => {
      if (!graphRef.current) return;

      const clusterNodes = Array.from(existingNodesRef.current.values()).filter(
        (n) => n.cluster_id === clusterId
      );
      if (clusterNodes.length === 0) return;

      const validNodes = clusterNodes.filter((n) => typeof n.x === "number");
      if (validNodes.length === 0) return;

      let avgX = 0, avgY = 0, avgZ = 0;
      validNodes.forEach((n) => {
        avgX += n.x;
        avgY += n.y;
        avgZ += n.z || 0;
      });
      avgX /= validNodes.length;
      avgY /= validNodes.length;
      avgZ /= validNodes.length;

      // Compute bounding radius
      let maxR = 40;
      validNodes.forEach((n) => {
        const dx = n.x - avgX;
        const dy = n.y - avgY;
        const dz = (n.z || 0) - avgZ;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist > maxR) maxR = dist;
      });

      const cameraDist = Math.max(180, Math.min(650, maxR * 2.8 + 120));

      if (!is2D && graphRef.current.cameraPosition) {
        graphRef.current.cameraPosition(
          { x: avgX, y: avgY, z: avgZ + cameraDist },
          { x: avgX, y: avgY, z: avgZ },
          800
        );
      } else if (is2D) {
        if (graphRef.current.zoomToFit) {
          graphRef.current.zoomToFit(800, 50, (node) => node.cluster_id === clusterId);
        } else if (graphRef.current.centerAt) {
          graphRef.current.centerAt(avgX, avgY, 800);
          const zoomLevel = Math.max(0.8, Math.min(2.8, 380 / (maxR * 2)));
          graphRef.current.zoom(zoomLevel, 800);
        }
      }
    },
    [is2D]
  );

  // Center camera on a specific node
  const centerOnNode = useCallback(
    (nodeId) => {
      if (!graphRef.current) return;
      const targetNode = existingNodesRef.current.get(nodeId);
      if (targetNode && typeof targetNode.x === "number") {
        if (!is2D && graphRef.current.cameraPosition) {
          graphRef.current.cameraPosition(
            { x: targetNode.x, y: targetNode.y, z: (targetNode.z || 0) + 160 },
            { x: targetNode.x, y: targetNode.y, z: targetNode.z || 0 },
            800
          );
        } else if (is2D && graphRef.current.centerAt) {
          graphRef.current.centerAt(targetNode.x, targetNode.y, 800);
          graphRef.current.zoom(2.5, 800);
        }
      }
    },
    [is2D]
  );

  // Reset view to whole graph ("Re-center" button and Esc key)
  const handleResetView = useCallback(() => {
    lastCenteringTargetRef.current = null;
    if (!graphRef.current) return;
    if (!is2D && graphRef.current.cameraPosition) {
      graphRef.current.cameraPosition({ x: 0, y: 0, z: 420 }, { x: 0, y: 0, z: 0 }, 800);
    } else if (is2D) {
      if (graphRef.current.zoomToFit) {
        graphRef.current.zoomToFit(800, 30);
      } else if (graphRef.current.centerAt) {
        graphRef.current.centerAt(0, 0, 800);
        graphRef.current.zoom(1.0, 800);
      }
    }
    if (onClearSelection) onClearSelection();
  }, [is2D, onClearSelection]);

  // Esc key resets view
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        handleResetView();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleResetView]);

  // Merge incoming nodes into existing node map to preserve physics simulation coordinates
  const mergeGraphData = useCallback((incoming) => {
    if (!incoming || !incoming.nodes) return;

    const rawNodes = (incoming.nodes || []).slice(0, 600);
    const rawLinks = (incoming.links || []).slice(0, 1000);

    const existingMap = existingNodesRef.current;
    const newNodes = [];

    rawNodes.forEach((node) => {
      const existing = existingMap.get(node.id);
      if (existing) {
        // Mutate in-place to preserve x, y, z, vx, vy, vz
        existing.risk = node.risk;
        existing.volume = node.volume;
        existing.frozen = node.frozen;
        existing.cluster_id = node.cluster_id;
        existing.__isCluster = node.__isCluster;
        existing.__isOneHop = node.__isOneHop;
        existing.__dimmed = node.__dimmed;
        newNodes.push(existing);
      } else {
        existingMap.set(node.id, node);
        newNodes.push(node);
      }
    });

    // Prune evicted nodes
    const newIdSet = new Set(newNodes.map((n) => n.id));
    for (const [id] of existingMap.entries()) {
      if (!newIdSet.has(id)) {
        existingMap.delete(id);
      }
    }

    setGraphData({
      nodes: newNodes,
      links: rawLinks,
    });
    setIsLoading(false);
  }, []);

  // Fetch graph data
  const fetchGraph = useCallback(async () => {
    try {
      const query = isSelectedClusterRef.current
        ? `/api/graph?cluster_id=${encodeURIComponent(isSelectedClusterRef.current)}&hops=1`
        : "/api/graph";

      const res = await apiFetch(query);
      if (res && res.nodes) {
        mergeGraphData(res);
      }
    } catch (err) {
      console.warn("Failed to fetch graph data", err);
      setIsLoading(false);
    }
  }, [mergeGraphData]);

  // Polling graph data every 3 seconds (does NOT re-center camera)
  useEffect(() => {
    fetchGraph();
    const timer = setInterval(fetchGraph, 3000);
    return () => clearInterval(timer);
  }, [fetchGraph, selectedClusterId]);

  // Re-center ONLY when selectedClusterId, selectedNodeId, or a NEW alert changes
  useEffect(() => {
    if (selectedNodeId) {
      lastCenteringTargetRef.current = `node:${selectedNodeId}`;
      centerOnNode(selectedNodeId);
      return;
    }

    if (selectedClusterId) {
      const targetKey = `cluster:${selectedClusterId}`;
      if (lastCenteringTargetRef.current !== targetKey) {
        lastCenteringTargetRef.current = targetKey;
        // Allow a frame for nodes to be populated if just selected
        setTimeout(() => centerOnCluster(selectedClusterId), 100);
      }
    }
  }, [selectedClusterId, selectedNodeId, centerOnCluster, centerOnNode]);

  // When a new alert arrives, re-center on it
  useEffect(() => {
    if (lastAlertId && selectedClusterId) {
      const targetKey = `alert:${lastAlertId}:${selectedClusterId}`;
      if (lastCenteringTargetRef.current !== targetKey) {
        lastCenteringTargetRef.current = targetKey;
        setTimeout(() => centerOnCluster(selectedClusterId), 150);
      }
    }
  }, [lastAlertId, selectedClusterId, centerOnCluster]);

  const handleNodeClick = useCallback(
    (node) => {
      if (!node) return;
      onSelectNode(node.id);
    },
    [onSelectNode]
  );

  return (
    <div className="center-viewport">
      {/* Top Toolbar / Header (No longer overlays canvas) */}
      <div className="graph-toolbar">
        <div className="graph-toolbar-left">
          <div className="view-mode-buttons">
            <button
              type="button"
              className={`graph-btn ${!is2D ? "active" : ""}`}
              onClick={() => setIs2D(false)}
            >
              3D Force View
            </button>
            <button
              type="button"
              className={`graph-btn ${is2D ? "active" : ""}`}
              onClick={() => setIs2D(true)}
            >
              2D Fallback
            </button>
          </div>

          <button
            type="button"
            className="graph-btn btn-recenter"
            onClick={handleResetView}
            title="Reset camera view to center (Esc)"
          >
            🎯 Re-center (Esc)
          </button>

          {(selectedClusterId || selectedNodeId) && (
            <button type="button" className="graph-btn btn-clear-focus" onClick={handleResetView}>
              ✕ Clear Focus
            </button>
          )}
        </div>

        {/* Legend */}
        <div className="graph-toolbar-legend">
          <div className="legend-item">
            <span className="legend-swatch" style={{ background: "#EF4444" }} />
            <span>High Risk (≥85%)</span>
          </div>
          <div className="legend-item">
            <span className="legend-swatch" style={{ background: "#F59E0B" }} />
            <span>Medium (65-85%)</span>
          </div>
          <div className="legend-item">
            <span className="legend-swatch" style={{ background: "#60A5FA" }} />
            <span>Legit Background</span>
          </div>
          <div className="legend-item">
            <span className="legend-swatch" style={{ background: "#38BDF8" }} />
            <span>Frozen</span>
          </div>
          <span className="legend-graph-meta">
            {graphData.nodes.length} nodes · {graphData.links.length} links
          </span>
        </div>
      </div>

      {/* Canvas Wrapper with exact ResizeObserver dimensions */}
      <div
        ref={containerRef}
        className={`graph-canvas-wrapper ${isRedAlertFlashing ? "red-alert-pulse" : ""}`}
      >
        {isLoading && graphData.nodes.length === 0 ? (
          <div className="graph-loading-state">
            <span className="loading-spinner" />
            <span>Initializing Financial Transaction Graph...</span>
          </div>
        ) : dimensions.width > 0 && dimensions.height > 0 ? (
          is2D ? (
            <ForceGraph2D
              ref={graphRef}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeLabel={(n) => `${n.id} (Risk: ${Math.round((n.risk || 0) * 100)}%)`}
              nodeColor={getNodeColor}
              nodeVal={getNodeVal}
              linkColor={(l) =>
                l.__dimmed
                  ? "rgba(43,48,84,0.2)"
                  : l.__isCluster
                  ? "#9254DE"
                  : "rgba(96,165,250,0.35)"
              }
              linkWidth={(l) =>
                l.__dimmed ? 1 : Math.max(1.5, Math.min(5, Math.log10(l.amount || 1000) - 2))
              }
              linkDirectionalParticles={(l) => (l.__dimmed ? 0 : 2)}
              linkDirectionalParticleSpeed={0.007}
              linkDirectionalParticleWidth={(l) =>
                Math.max(1.5, Math.min(3.5, Math.log10(l.amount || 1000) - 2))
              }
              onNodeClick={handleNodeClick}
              backgroundColor="#0B0D17"
              cooldownTicks={80}
              d3VelocityDecay={0.25}
            />
          ) : (
            <ForceGraph3D
              ref={graphRef}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeLabel={(n) => `${n.id} (Risk: ${Math.round((n.risk || 0) * 100)}%)`}
              nodeColor={getNodeColor}
              nodeVal={getNodeVal}
              nodeResolution={16}
              linkColor={(l) =>
                l.__dimmed
                  ? "rgba(43,48,84,0.18)"
                  : l.__isCluster
                  ? "#9254DE"
                  : "rgba(96,165,250,0.35)"
              }
              linkWidth={(l) =>
                l.__dimmed ? 0.6 : Math.max(1.2, Math.min(4.5, Math.log10(l.amount || 1000) - 2))
              }
              linkDirectionalParticles={(l) => (l.__dimmed ? 0 : 2)}
              linkDirectionalParticleSpeed={0.007}
              linkDirectionalParticleWidth={(l) =>
                Math.max(1.5, Math.min(3.5, Math.log10(l.amount || 1000) - 2))
              }
              linkDirectionalParticleColor={(l) => (l.__isCluster ? "#F59E0B" : "#60A5FA")}
              onNodeClick={handleNodeClick}
              backgroundColor="#0B0D17"
              showNavInfo={false}
              d3VelocityDecay={0.25}
            />
          )
        ) : null}
      </div>
    </div>
  );
}
