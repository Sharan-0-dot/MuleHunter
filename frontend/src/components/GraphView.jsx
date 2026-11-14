import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import ForceGraph2D from "react-force-graph-2d";
import { apiFetch } from "../api/client";

function getNodeColor(node) {
  if (node.frozen) return "#38BDF8"; // ice-blue
  if (node.__dimmed) return "rgba(55, 65, 100, 0.35)";

  const risk = Number(node.risk ?? 0);
  if (risk >= 0.85) return "#EF4444"; // red
  if (risk >= 0.65) return "#F59E0B"; // yellow
  if (risk >= 0.4) return "#EAB308"; // amber
  return "#60A5FA"; // calm blue
}

function getNodeVal(node) {
  const vol = Number(node.volume || node.in_amount || 50000);
  const size = Math.max(3, Math.min(14, Math.log10(vol + 1) * 2));
  if (node.__isCluster) return size * 1.5;
  return size;
}

export default function GraphView({
  selectedClusterId,
  selectedNodeId,
  onSelectNode,
  onClearSelection,
  onToast,
}) {
  const [is2D, setIs2D] = useState(false);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const graphRef = useRef();
  const existingNodesRef = useRef(new Map());
  const isSelectedClusterRef = useRef(selectedClusterId);
  isSelectedClusterRef.current = selectedClusterId;

  // ESC key clears selection
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        onClearSelection();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClearSelection]);

  // Merge incoming nodes into existing node objects so force simulation doesn't jump
  const mergeGraphData = useCallback((incoming) => {
    if (!incoming || !incoming.nodes) return;

    const rawNodes = (incoming.nodes || []).slice(0, 600);
    const rawLinks = (incoming.links || []).slice(0, 1000);

    const existingMap = existingNodesRef.current;
    const newNodes = [];

    rawNodes.forEach((node) => {
      const existing = existingMap.get(node.id);
      if (existing) {
        // Mutate existing object in place to preserve x, y, z, vx, vy, vz
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

    // Prune evicted nodes from map
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
    }
  }, [mergeGraphData]);

  // Polling graph every 3 seconds
  useEffect(() => {
    fetchGraph();
    const timer = setInterval(fetchGraph, 3000);
    return () => clearInterval(timer);
  }, [fetchGraph, selectedClusterId]);

  // Camera fly when cluster or node selected
  useEffect(() => {
    if (!graphRef.current) return;

    if (selectedNodeId) {
      const targetNode = existingNodesRef.current.get(selectedNodeId);
      if (targetNode && typeof targetNode.x === "number") {
        if (!is2D && graphRef.current.cameraPosition) {
          graphRef.current.cameraPosition(
            { x: targetNode.x, y: targetNode.y, z: (targetNode.z || 0) + 160 },
            { x: targetNode.x, y: targetNode.y, z: targetNode.z || 0 },
            1200
          );
        } else if (is2D && graphRef.current.centerAt) {
          graphRef.current.centerAt(targetNode.x, targetNode.y, 800);
          graphRef.current.zoom(2.5, 800);
        }
      }
    } else if (selectedClusterId) {
      // Find cluster center of mass
      const clusterNodes = Array.from(existingNodesRef.current.values()).filter(
        (n) => n.cluster_id === selectedClusterId
      );
      if (clusterNodes.length > 0 && typeof clusterNodes[0].x === "number") {
        let avgX = 0, avgY = 0, avgZ = 0;
        clusterNodes.forEach((n) => {
          avgX += n.x || 0;
          avgY += n.y || 0;
          avgZ += n.z || 0;
        });
        avgX /= clusterNodes.length;
        avgY /= clusterNodes.length;
        avgZ /= clusterNodes.length;

        if (!is2D && graphRef.current.cameraPosition) {
          graphRef.current.cameraPosition(
            { x: avgX, y: avgY, z: avgZ + 240 },
            { x: avgX, y: avgY, z: avgZ },
            1200
          );
        } else if (is2D && graphRef.current.centerAt) {
          graphRef.current.centerAt(avgX, avgY, 800);
          graphRef.current.zoom(1.8, 800);
        }
      }
    }
  }, [selectedClusterId, selectedNodeId, is2D]);

  const handleNodeClick = useCallback(
    (node) => {
      if (!node) return;
      onSelectNode(node.id);
    },
    [onSelectNode]
  );

  return (
    <div className="center-viewport">
      <div className="graph-controls">
        <button
          className={`graph-btn ${!is2D ? "active" : ""}`}
          onClick={() => setIs2D(false)}
        >
          3D Force View
        </button>
        <button
          className={`graph-btn ${is2D ? "active" : ""}`}
          onClick={() => setIs2D(true)}
        >
          2D Canvas Fallback
        </button>
        {(selectedClusterId || selectedNodeId) && (
          <button className="graph-btn" onClick={onClearSelection}>
            ✕ Clear Focus (Esc)
          </button>
        )}
      </div>

      <div className="graph-legend">
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: "#EF4444" }} />
          <span>High Risk (≥ 85%)</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: "#F59E0B" }} />
          <span>Medium Risk (65–85%)</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: "#60A5FA" }} />
          <span>Calm Background (&lt; 40%)</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: "#38BDF8" }} />
          <span>Frozen Account</span>
        </div>
      </div>

      <div className="graph-canvas-wrapper">
        {is2D ? (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            nodeLabel={(n) => `${n.id} (Risk: ${Math.round((n.risk || 0) * 100)}%)`}
            nodeColor={getNodeColor}
            nodeVal={getNodeVal}
            linkColor={(l) => (l.__dimmed ? "rgba(43,48,84,0.2)" : l.__isCluster ? "#9254DE" : "rgba(96,165,250,0.4)")}
            linkWidth={(l) => (l.__dimmed ? 1 : Math.max(1.5, Math.min(5, Math.log10(l.amount || 1000) - 2)))}
            linkDirectionalParticles={(l) => (l.__dimmed ? 0 : 2)}
            linkDirectionalParticleSpeed={0.007}
            linkDirectionalParticleWidth={(l) => Math.max(1.5, Math.min(3.5, Math.log10(l.amount || 1000) - 2))}
            onNodeClick={handleNodeClick}
            backgroundColor="#0B0D17"
            cooldownTicks={100}
          />
        ) : (
          <ForceGraph3D
            ref={graphRef}
            graphData={graphData}
            nodeLabel={(n) => `${n.id} (Risk: ${Math.round((n.risk || 0) * 100)}%)`}
            nodeColor={getNodeColor}
            nodeVal={getNodeVal}
            nodeResolution={16}
            linkColor={(l) => (l.__dimmed ? "rgba(43,48,84,0.2)" : l.__isCluster ? "#9254DE" : "rgba(96,165,250,0.4)")}
            linkWidth={(l) => (l.__dimmed ? 0.6 : Math.max(1.2, Math.min(4.5, Math.log10(l.amount || 1000) - 2)))}
            linkDirectionalParticles={(l) => (l.__dimmed ? 0 : 2)}
            linkDirectionalParticleSpeed={0.007}
            linkDirectionalParticleWidth={(l) => Math.max(1.5, Math.min(3.5, Math.log10(l.amount || 1000) - 2))}
            linkDirectionalParticleColor={(l) => (l.__isCluster ? "#F59E0B" : "#60A5FA")}
            onNodeClick={handleNodeClick}
            backgroundColor="#0B0D17"
            showNavInfo={false}
          />
        )}
      </div>
    </div>
  );
}
