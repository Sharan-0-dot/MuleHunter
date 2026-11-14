/**
 * Mock Data for Offline Demo Mode (Mule Hunter)
 */

export const MOCK_CLUSTERS = [
  {
    cluster_id: "C-0001",
    typology: "round_tripping",
    level: "red",
    risk_score: 0.92,
    accounts_count: 7,
    total_amount_inr: 420000,
    created_at: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
    accounts: [
      "ACC-1001",
      "ACC-1002",
      "ACC-1003",
      "ACC-1004",
      "ACC-1005",
      "ACC-1006",
      "ACC-1007",
    ],
    summary_text:
      "Red alert. 7 accounts moved 4.2 lakh rupees in a loop. Money entered through ACC-1001 and returned to origin. Risk 92 percent. Log in to the dashboard for linked accounts.",
    frozen: false,
    risk_components: {
      cycle_score: 0.95,
      retention_ratio: 0.97,
      rapid_turnover: 0.89,
    },
    timeline: [
      { event: "cluster_alert", ts: new Date(Date.now() - 1000 * 60 * 12).toISOString() },
      { event: "pi_received", ts: new Date(Date.now() - 1000 * 60 * 11).toISOString() },
      { event: "explain_voice", ts: new Date(Date.now() - 1000 * 60 * 10).toISOString() },
      { event: "audio_played", ts: new Date(Date.now() - 1000 * 60 * 9).toISOString() },
    ],
    pi_status: "played",
  },
  {
    cluster_id: "C-0002",
    typology: "smurfing_fan_out_fan_in",
    level: "red",
    risk_score: 0.88,
    accounts_count: 9,
    total_amount_inr: 850000,
    created_at: new Date(Date.now() - 1000 * 60 * 35).toISOString(),
    accounts: [
      "ACC-2001",
      "ACC-2002",
      "ACC-2003",
      "ACC-2004",
      "ACC-2005",
      "ACC-2006",
      "ACC-2007",
      "ACC-2008",
      "ACC-2009",
    ],
    summary_text:
      "Red alert. 9 accounts moved 8.5 lakh rupees in a fan-out fan-in pattern. High structuring below threshold. Risk 88 percent. Log in to the dashboard for linked accounts.",
    frozen: false,
    risk_components: {
      fan_out_cv: 0.12,
      reconvergence_score: 0.91,
      mule_pass_through: 0.94,
    },
    timeline: [
      { event: "cluster_alert", ts: new Date(Date.now() - 1000 * 60 * 35).toISOString() },
      { event: "pi_received", ts: new Date(Date.now() - 1000 * 60 * 34).toISOString() },
      { event: "explain_joystick", ts: new Date(Date.now() - 1000 * 60 * 33).toISOString() },
    ],
    pi_status: "heard",
  },
  {
    cluster_id: "C-0003",
    typology: "mule_chain",
    level: "yellow",
    risk_score: 0.74,
    accounts_count: 5,
    total_amount_inr: 310000,
    created_at: new Date(Date.now() - 1000 * 60 * 65).toISOString(),
    accounts: ["ACC-3001", "ACC-3002", "ACC-3003", "ACC-3004", "ACC-3005"],
    summary_text:
      "Yellow alert. 5 accounts moved 3.1 lakh rupees in a rapid mule chain with short hold times. Risk 74 percent. Log in to the dashboard for linked accounts.",
    frozen: false,
    risk_components: {
      chain_length: 5,
      median_hold_seconds: 320,
      pass_through: 0.96,
    },
    timeline: [
      { event: "cluster_alert", ts: new Date(Date.now() - 1000 * 60 * 65).toISOString() },
      { event: "pi_received", ts: new Date(Date.now() - 1000 * 60 * 64).toISOString() },
      { event: "timeout", ts: new Date(Date.now() - 1000 * 60 * 63).toISOString() },
    ],
    pi_status: "timeout",
  },
  {
    cluster_id: "C-0004",
    typology: "hybrid",
    level: "red",
    risk_score: 0.95,
    accounts_count: 11,
    total_amount_inr: 1420000,
    created_at: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    accounts: [
      "ACC-4001", "ACC-4002", "ACC-4003", "ACC-4004", "ACC-4005",
      "ACC-4006", "ACC-4007", "ACC-4008", "ACC-4009", "ACC-4010", "ACC-4011"
    ],
    summary_text:
      "Red alert. 11 accounts moved 14.2 lakh rupees across multi-stage dispersion and cycle. Risk 95 percent. Log in to the dashboard for linked accounts.",
    frozen: true,
    prevented_inr: 1420000,
    timeline: [
      { event: "cluster_alert", ts: new Date(Date.now() - 1000 * 60 * 120).toISOString() },
      { event: "pi_received", ts: new Date(Date.now() - 1000 * 60 * 119).toISOString() },
      { event: "explain_voice", ts: new Date(Date.now() - 1000 * 60 * 118).toISOString() },
      { event: "audio_played", ts: new Date(Date.now() - 1000 * 60 * 117).toISOString() },
      { event: "frozen", ts: new Date(Date.now() - 1000 * 60 * 110).toISOString() },
    ],
    pi_status: "played",
  },
];

// Master 8.6 account details dictionary
export const MOCK_ACCOUNTS = {
  "ACC-1001": {
    account_id: "ACC-1001",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.92,
    in_amount: 420000,
    out_amount: 418000,
    retention_ratio: 0.005,
    in_degree: 2,
    out_degree: 2,
    median_hold_seconds: 360,
    frozen: false,
    recent_tx: [
      { from: "ACC-1007", to: "ACC-1001", amount: 418000, ts: "2026-11-15T10:41:00Z" },
      { from: "ACC-1001", to: "ACC-1002", amount: 210000, ts: "2026-11-15T10:15:00Z" },
      { from: "ACC-1001", to: "ACC-1003", amount: 208000, ts: "2026-11-15T10:16:00Z" },
    ],
  },
  "ACC-1002": {
    account_id: "ACC-1002",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.91,
    in_amount: 210000,
    out_amount: 207000,
    retention_ratio: 0.014,
    in_degree: 1,
    out_degree: 1,
    median_hold_seconds: 240,
    frozen: false,
    recent_tx: [
      { from: "ACC-1001", to: "ACC-1002", amount: 210000, ts: "2026-11-15T10:15:00Z" },
      { from: "ACC-1002", to: "ACC-1004", amount: 207000, ts: "2026-11-15T10:20:00Z" },
    ],
  },
  "ACC-1003": {
    account_id: "ACC-1003",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.89,
    in_amount: 208000,
    out_amount: 205000,
    retention_ratio: 0.014,
    in_degree: 1,
    out_degree: 1,
    median_hold_seconds: 180,
    frozen: false,
    recent_tx: [
      { from: "ACC-1001", to: "ACC-1003", amount: 208000, ts: "2026-11-15T10:16:00Z" },
      { from: "ACC-1003", to: "ACC-1005", amount: 205000, ts: "2026-11-15T10:22:00Z" },
    ],
  },
  "ACC-1004": {
    account_id: "ACC-1004",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.90,
    in_amount: 207000,
    out_amount: 205000,
    retention_ratio: 0.009,
    in_degree: 1,
    out_degree: 1,
    median_hold_seconds: 420,
    frozen: false,
    recent_tx: [
      { from: "ACC-1002", to: "ACC-1004", amount: 207000, ts: "2026-11-15T10:20:00Z" },
      { from: "ACC-1004", to: "ACC-1006", amount: 205000, ts: "2026-11-15T10:28:00Z" },
    ],
  },
  "ACC-1005": {
    account_id: "ACC-1005",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.88,
    in_amount: 205000,
    out_amount: 203000,
    retention_ratio: 0.009,
    in_degree: 1,
    out_degree: 1,
    median_hold_seconds: 300,
    frozen: false,
    recent_tx: [
      { from: "ACC-1003", to: "ACC-1005", amount: 205000, ts: "2026-11-15T10:22:00Z" },
      { from: "ACC-1005", to: "ACC-1006", amount: 203000, ts: "2026-11-15T10:30:00Z" },
    ],
  },
  "ACC-1006": {
    account_id: "ACC-1006",
    type: "individual",
    cluster_id: "C-0001",
    risk: 0.93,
    in_amount: 408000,
    out_amount: 405000,
    retention_ratio: 0.007,
    in_degree: 2,
    out_degree: 1,
    median_hold_seconds: 210,
    frozen: false,
    recent_tx: [
      { from: "ACC-1004", to: "ACC-1006", amount: 205000, ts: "2026-11-15T10:28:00Z" },
      { from: "ACC-1005", to: "ACC-1006", amount: 203000, ts: "2026-11-15T10:30:00Z" },
      { from: "ACC-1006", to: "ACC-1007", amount: 405000, ts: "2026-11-15T10:35:00Z" },
    ],
  },
  "ACC-1007": {
    account_id: "ACC-1007",
    type: "merchant",
    cluster_id: "C-0001",
    risk: 0.94,
    in_amount: 405000,
    out_amount: 400000,
    retention_ratio: 0.012,
    in_degree: 1,
    out_degree: 1,
    median_hold_seconds: 150,
    frozen: false,
    recent_tx: [
      { from: "ACC-1006", to: "ACC-1007", amount: 405000, ts: "2026-11-15T10:35:00Z" },
      { from: "ACC-1007", to: "ACC-1001", amount: 400000, ts: "2026-11-15T10:41:00Z" },
    ],
  },
  // ACC-4001 is frozen
  "ACC-4001": {
    account_id: "ACC-4001",
    type: "business",
    cluster_id: "C-0004",
    risk: 0.95,
    in_amount: 1420000,
    out_amount: 1400000,
    retention_ratio: 0.014,
    in_degree: 3,
    out_degree: 4,
    median_hold_seconds: 400,
    frozen: true,
    recent_tx: [
      { from: "ACC-4001", to: "ACC-4002", amount: 350000, ts: "2026-11-15T09:10:00Z" },
      { from: "ACC-4001", to: "ACC-4003", amount: 350000, ts: "2026-11-15T09:12:00Z" },
    ],
  },
};

// Generates a mock graph with a visible, clear ring for C-0001
export function generateMockGraph(selectedClusterId = null) {
  const nodes = [];
  const links = [];

  // Ring 1 (C-0001 - 7 nodes arranged in a cycle)
  const ring1Accounts = [
    { id: "ACC-1001", risk: 0.92, amount: 420000, frozen: false },
    { id: "ACC-1002", risk: 0.91, amount: 210000, frozen: false },
    { id: "ACC-1004", risk: 0.90, amount: 207000, frozen: false },
    { id: "ACC-1006", risk: 0.93, amount: 408000, frozen: false },
    { id: "ACC-1007", risk: 0.94, amount: 405000, frozen: false },
    { id: "ACC-1005", risk: 0.88, amount: 205000, frozen: false },
    { id: "ACC-1003", risk: 0.89, amount: 208000, frozen: false },
  ];

  ring1Accounts.forEach((acc, i) => {
    const angle = (i / ring1Accounts.length) * Math.PI * 2;
    nodes.push({
      id: acc.id,
      name: acc.id,
      cluster_id: "C-0001",
      risk: acc.risk,
      volume: acc.amount,
      frozen: acc.frozen,
      x: Math.cos(angle) * 120,
      y: Math.sin(angle) * 120,
      z: 0,
    });
  });

  // Cycle links
  links.push(
    { source: "ACC-1001", target: "ACC-1002", amount: 210000, cluster_id: "C-0001" },
    { source: "ACC-1001", target: "ACC-1003", amount: 208000, cluster_id: "C-0001" },
    { source: "ACC-1002", target: "ACC-1004", amount: 207000, cluster_id: "C-0001" },
    { source: "ACC-1003", target: "ACC-1005", amount: 205000, cluster_id: "C-0001" },
    { source: "ACC-1004", target: "ACC-1006", amount: 205000, cluster_id: "C-0001" },
    { source: "ACC-1005", target: "ACC-1006", amount: 203000, cluster_id: "C-0001" },
    { source: "ACC-1006", target: "ACC-1007", amount: 405000, cluster_id: "C-0001" },
    { source: "ACC-1007", target: "ACC-1001", amount: 400000, cluster_id: "C-0001" }
  );

  // Ring 2 (C-0002 - Smurfing Fan-out Fan-in)
  const smurfAccounts = [
    "ACC-2001", "ACC-2002", "ACC-2003", "ACC-2004",
    "ACC-2005", "ACC-2006", "ACC-2007", "ACC-2008", "ACC-2009"
  ];
  smurfAccounts.forEach((id, idx) => {
    nodes.push({
      id,
      name: id,
      cluster_id: "C-0002",
      risk: 0.88,
      volume: 85000,
      frozen: false,
      x: 250 + (idx % 3) * 60,
      y: -100 + Math.floor(idx / 3) * 60,
      z: 30,
    });
  });
  // Connect smurfing
  for (let i = 1; i <= 7; i++) {
    links.push({ source: "ACC-2001", target: `ACC-200${i + 1}`, amount: 95000, cluster_id: "C-0002" });
    links.push({ source: `ACC-200${i + 1}`, target: "ACC-2009", amount: 93000, cluster_id: "C-0002" });
  }

  // Ring 4 (Frozen cluster C-0004)
  const frozenAccounts = ["ACC-4001", "ACC-4002", "ACC-4003", "ACC-4004"];
  frozenAccounts.forEach((id, idx) => {
    nodes.push({
      id,
      name: id,
      cluster_id: "C-0004",
      risk: 0.95,
      volume: 350000,
      frozen: true,
      x: -250 + idx * 50,
      y: 120,
      z: -20,
    });
  });
  links.push(
    { source: "ACC-4001", target: "ACC-4002", amount: 350000, cluster_id: "C-0004" },
    { source: "ACC-4002", target: "ACC-4003", amount: 345000, cluster_id: "C-0004" },
    { source: "ACC-4003", target: "ACC-4004", amount: 340000, cluster_id: "C-0004" }
  );

  // Background Calm Nodes (~50 nodes)
  for (let i = 1; i <= 45; i++) {
    const id = `ACC-BG-${1000 + i}`;
    nodes.push({
      id,
      name: id,
      cluster_id: null,
      risk: 0.05 + (i % 5) * 0.05,
      volume: 12000 + (i % 10) * 4000,
      frozen: false,
      x: (Math.sin(i * 1.7) * 350) + (i % 2 === 0 ? 50 : -50),
      y: (Math.cos(i * 1.3) * 320) + (i % 3 === 0 ? 40 : -40),
      z: (Math.sin(i * 0.9) * 200),
    });
    // add links between background nodes
    if (i > 1 && i % 2 === 0) {
      links.push({
        source: `ACC-BG-${1000 + i - 1}`,
        target: id,
        amount: 8000 + (i % 5) * 2000,
        cluster_id: null,
      });
    }
  }

  // Filter or highlight if cluster selected
  if (selectedClusterId) {
    const clusterNodes = nodes.filter((n) => n.cluster_id === selectedClusterId);
    const clusterNodeIds = new Set(clusterNodes.map((n) => n.id));
    const clusterLinks = links.filter(
      (l) => clusterNodeIds.has(typeof l.source === "object" ? l.source.id : l.source) ||
             clusterNodeIds.has(typeof l.target === "object" ? l.target.id : l.target)
    );
    // Include 1-hop neighbours
    const oneHopNodeIds = new Set(clusterNodeIds);
    clusterLinks.forEach((l) => {
      oneHopNodeIds.add(typeof l.source === "object" ? l.source.id : l.source);
      oneHopNodeIds.add(typeof l.target === "object" ? l.target.id : l.target);
    });

    // Mark dimmed property
    nodes.forEach((n) => {
      n.__isCluster = clusterNodeIds.has(n.id);
      n.__isOneHop = oneHopNodeIds.has(n.id);
      n.__dimmed = !oneHopNodeIds.has(n.id);
    });
    links.forEach((l) => {
      const sId = typeof l.source === "object" ? l.source.id : l.source;
      const tId = typeof l.target === "object" ? l.target.id : l.target;
      l.__isCluster = clusterNodeIds.has(sId) && clusterNodeIds.has(tId);
      l.__dimmed = !l.__isCluster;
    });
  } else {
    nodes.forEach((n) => {
      n.__isCluster = false;
      n.__isOneHop = false;
      n.__dimmed = false;
    });
    links.forEach((l) => {
      l.__isCluster = false;
      l.__dimmed = false;
    });
  }

  // Cap at 600 nodes
  return {
    nodes: nodes.slice(0, 600),
    links: links.slice(0, 1000),
  };
}

// Mock Metrics (exact shape of backend/data/metrics_val_full.json)
export const MOCK_METRICS = {
  tx_processed: 18750,
  alerts_count: 14,
  prevented_inr: 66402367.02,
  mean_tick_ms: 248.88,
  sim_time: "2026-11-15T18:45:00Z",
  sim_speed: 10.0,
  is_running: true,
  metrics: {
    split: "val",
    account_level: {
      baseline_fixed: {
        precision: 0.0094,
        recall: 0.6917,
        f1: 0.0186,
      },
      baseline_tuned: {
        precision: 0.0201,
        recall: 0.4778,
        f1: 0.0386,
      },
      rules_only: {
        precision: 0.0109,
        recall: 0.928,
        f1: 0.0215,
      },
      rules_plus_xgboost: {
        precision: 0.6345,
        recall: 0.8718,
        f1: 0.7345,
      },
    },
    by_difficulty: {
      "1": {
        baseline_fixed: { precision: 0.0099, recall: 1.0, f1: 0.0196 },
        baseline_tuned: { precision: 0.0303, recall: 1.0, f1: 0.0588 },
        rules_only: { precision: 0.0081, recall: 0.944, f1: 0.016 },
        rules_plus_xgboost: { precision: 0.561, recall: 0.92, f1: 0.697 },
      },
      "2": {
        baseline_fixed: { precision: 0.0099, recall: 1.0, f1: 0.0196 },
        baseline_tuned: { precision: 0.0303, recall: 1.0, f1: 0.0589 },
        rules_only: { precision: 0.008, recall: 0.936, f1: 0.0159 },
        rules_plus_xgboost: { precision: 0.6056, recall: 0.872, f1: 0.7148 },
      },
      "3": {
        baseline_fixed: { precision: 0.0143, recall: 0.9784, f1: 0.0282 },
        baseline_tuned: { precision: 0.0272, recall: 0.6054, f1: 0.0521 },
        rules_only: { precision: 0.0121, recall: 0.9568, f1: 0.0238 },
        rules_plus_xgboost: { precision: 0.6641, recall: 0.9297, f1: 0.7748 },
      },
      "4": {
        baseline_fixed: { precision: 0.0091, recall: 0.5561, f1: 0.0178 },
        baseline_tuned: { precision: 0.017, recall: 0.3366, f1: 0.0323 },
        rules_only: { precision: 0.0132, recall: 0.9415, f1: 0.026 },
        rules_plus_xgboost: { precision: 0.6067, recall: 0.8878, f1: 0.7208 },
      },
      "5": {
        baseline_fixed: { precision: 0.0066, recall: 0.3532, f1: 0.013 },
        baseline_tuned: { precision: 0.0037, recall: 0.0638, f1: 0.0071 },
        rules_only: { precision: 0.0144, recall: 0.8979, f1: 0.0283 },
        rules_plus_xgboost: { precision: 0.7143, recall: 0.8085, f1: 0.7585 },
      },
    },
    stealth: {
      baseline_fixed: { precision: 0.008, recall: 0.3623, f1: 0.0156, ring_recall: 0.2 },
      baseline_tuned: { precision: 0.005, recall: 0.0725, f1: 0.0093, ring_recall: 0.0 },
      rules_only: { precision: 0.0163, recall: 0.8696, f1: 0.032, ring_recall: 0.8 },
      rules_plus_xgboost: { precision: 0.6322, recall: 0.7971, f1: 0.7051, ring_recall: 0.8 },
    },
    ring_recall: {
      baseline_fixed: 0.6571,
      baseline_tuned: 0.581,
      rules_only: 0.9143,
      rules_plus_xgboost: 0.9333,
    },
    latency_sec: {
      mean: 3069.7,
      median: 391.3,
    },
    prevented_inr: 66402367.02,
    false_alerts_per_day: {
      green: 0.0,
      yellow: 0.0,
      red: 0.0,
      total_ge_040: 0.0,
    },
  },
};

// Mock Audit Log
export const MOCK_AUDIT = [
  {
    id: 1,
    ts: "2026-11-15T10:42:11Z",
    event_type: "alert_created",
    payload: { alert_id: "A-0001", cluster_id: "C-0001", risk_score: 0.92, typology: "round_tripping" },
    prev_hash: "0000000000000000000000000000000000000000000000000000000000000000",
    hash: "6e2ba6db7817e923e498c47f52627e1d5308638064619623838276f272a27a4d",
  },
  {
    id: 2,
    ts: "2026-11-15T10:42:15Z",
    event_type: "pi_ack_received",
    payload: { alert_id: "A-0001", event: "received" },
    prev_hash: "6e2ba6db7817e923e498c47f52627e1d5308638064619623838276f272a27a4d",
    hash: "982cf4608c2a417531eb44d9f10f8ad496bb7cf0d6fb9ad14c62d047b312788e",
  },
  {
    id: 3,
    ts: "2026-11-15T10:42:25Z",
    event_type: "officer_login",
    payload: { officer_id: "O-1", officer_name: "Officer A", method: "biometric_fingerprint" },
    prev_hash: "982cf4608c2a417531eb44d9f10f8ad496bb7cf0d6fb9ad14c62d047b312788e",
    hash: "3b0008544d97f5bca4f4c28f3ea7e31ecba537b08d484439cba916a03b51f0c2",
  },
  {
    id: 4,
    ts: "2026-11-15T10:43:02Z",
    event_type: "cluster_frozen",
    payload: { cluster_id: "C-0004", officer_id: "O-1", accounts_frozen: 4, prevented_inr: 1420000 },
    prev_hash: "3b0008544d97f5bca4f4c28f3ea7e31ecba537b08d484439cba916a03b51f0c2",
    hash: "a430d2fcba6e9cb2b115456f50c05fe9bf3ef86915b88132aa982cfb02135678",
  },
];
