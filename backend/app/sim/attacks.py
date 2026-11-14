"""
Attack ring injectors for AML synthetic dataset generation.

Defines 5 attack typologies:
1. smurfing: source splits amount to mules; mules forward to destination(s)
2. round_trip: cycle of accounts returning money to origin minus fee
3. mule_chain: pass-through chain where each hop retains a small fee
4. hybrid: smurfing -> pass-through chain -> cyclic return to source
5. stealth: always runs at difficulty 5, structuring below threshold and heavy decoys

Preserves transaction volume across difficulty levels (structuring into smaller transfers).
Zero label leakage: ring transactions use normal kinds (p2p, etc.) and GroundTruth
is stored completely separately.
Every ground-truth account appears in at least one ring transaction,
and ring transactions form a single weakly connected graph.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
import networkx as nx
import numpy as np

from app.config import SIM_NAIVE_THRESHOLD

# ---------------------------------------------------------------------------
# Difficulty Knobs Table
# ---------------------------------------------------------------------------
DIFFICULTY_KNOBS = {
    1: {
        "split_noise": 0.00,
        "hop_delay_min_sec": 60,          # 1 min
        "hop_delay_max_sec": 180,         # 3 min
        "num_decoys": 0,
        "retention_range": (0.97, 0.99),  # 1-3% fee
        "legit_mix_count": 0,             # No mixing
    },
    2: {
        "split_noise": 0.05,
        "hop_delay_min_sec": 600,         # 10 min
        "hop_delay_max_sec": 1500,        # 25 min
        "num_decoys": 0,
        "retention_range": (0.95, 0.98),
        "legit_mix_count": 0,
    },
    3: {
        "split_noise": 0.10,
        "hop_delay_min_sec": 2400,        # 40 min
        "hop_delay_max_sec": 4500,        # 1.25 hours
        "num_decoys": 2,                  # 2 decoy hops
        "retention_range": (0.92, 0.96),
        "legit_mix_count": 2,             # Light mixing
    },
    4: {
        "split_noise": 0.20,
        "hop_delay_min_sec": 7200,        # 2 hours
        "hop_delay_max_sec": 12600,       # 3.5 hours
        "num_decoys": 3,                  # 3 decoys
        "retention_range": (0.88, 0.93),
        "legit_mix_count": 5,             # Moderate mixing
    },
    5: {
        "split_noise": 0.30,
        "hop_delay_min_sec": 14400,       # 4 hours
        "hop_delay_max_sec": 21600,       # 6 hours
        "num_decoys": 4,                  # 4 decoys
        "retention_range": (0.85, 0.90),  # 10-15% fee
        "legit_mix_count": 8,             # Heavy mixing
    },
}

# Base laundering volume preserved across difficulties
BASE_VOLUMES = {
    "smurfing": 750_000.0,
    "round_trip": 420_000.0,
    "mule_chain": 420_000.0,
    "hybrid": 1_200_000.0,
}


def _get_hop_delay(rng: np.random.Generator, difficulty: int) -> float:
    """Sample a hop delay in seconds strictly scaled to ensure time span increases with difficulty."""
    cfg = DIFFICULTY_KNOBS[difficulty]
    return float(rng.uniform(cfg["hop_delay_min_sec"], cfg["hop_delay_max_sec"]))


def _compress_ring_span(
    ring_txs: List,
    max_span_hours: float = 35.0,
) -> List:
    """
    Ensure the ring's first-to-last tx span does not exceed max_span_hours (36h default).
    Compresses hop delays proportionally while keeping split transfers spaced.
    """
    if len(ring_txs) <= 1:
        return ring_txs

    first_ts = min(t.ts for t in ring_txs)
    last_ts = max(t.ts for t in ring_txs)
    span_sec = (last_ts - first_ts).total_seconds()
    max_sec = max_span_hours * 3600.0

    if span_sec <= max_sec:
        return ring_txs

    scale = max_sec / span_sec
    from app.sim.generator import Transaction
    compressed = []
    for t in ring_txs:
        offset = (t.ts - first_ts).total_seconds() * scale
        compressed.append(
            Transaction(
                tx_id=t.tx_id,
                ts=first_ts + timedelta(seconds=offset),
                src=t.src,
                dst=t.dst,
                amount=t.amount,
                kind=t.kind,
            )
        )
    compressed.sort(key=lambda t: t.ts)
    return compressed


def _scale_ring_total(
    ring_tx_list: List,
    total_amount_inr: Optional[float],
    difficulty: int,
    rng: np.random.Generator,
) -> List:
    """
    Scales ring transactions so their total matches total_amount_inr exactly.
    Preserves timing and splits any chunks >= threshold at difficulty 5.
    """
    if total_amount_inr is None or not ring_tx_list:
        return ring_tx_list

    curr_sum = sum(t.amount for t in ring_tx_list)
    if curr_sum <= 0:
        return ring_tx_list

    scale = float(total_amount_inr) / curr_sum
    scaled_txs = []
    from app.sim.generator import Transaction

    for t in ring_tx_list:
        new_amt = round(t.amount * scale, 2)
        if difficulty == 5 and new_amt >= SIM_NAIVE_THRESHOLD:
            chunks = _split_into_chunks(new_amt, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks):
                scaled_txs.append(
                    Transaction(
                        tx_id=t.tx_id,
                        ts=t.ts + timedelta(seconds=c_idx * 120.0),
                        src=t.src,
                        dst=t.dst,
                        amount=c_amt,
                        kind=t.kind,
                    )
                )
        else:
            scaled_txs.append(
                Transaction(
                    tx_id=t.tx_id,
                    ts=t.ts,
                    src=t.src,
                    dst=t.dst,
                    amount=new_amt,
                    kind=t.kind,
                )
            )

    scaled_txs.sort(key=lambda t: t.ts)
    return scaled_txs


def _pick_accounts(
    rng: np.random.Generator,
    accounts: list,
    n: int,
    exclude: Optional[Set[str]] = None,
) -> List[str]:
    """Pick n distinct accounts from pool, avoiding excluded accounts."""
    exclude_set = exclude or set()
    eligible = [a.account_id for a in accounts if a.account_id not in exclude_set and a.account_type == "individual"]
    if len(eligible) < n:
        eligible = [a.account_id for a in accounts if a.account_id not in exclude_set]
    chosen = rng.choice(eligible, size=n, replace=False).tolist()
    return chosen


def _split_into_chunks(
    amount: float,
    difficulty: int,
    rng: np.random.Generator,
    max_chunk: float = 45_000.0,
) -> List[float]:
    """
    Split a transfer amount into sub-transfers.
    At difficulty 5: strictly all chunks are < SIM_NAIVE_THRESHOLD (structuring below threshold).
    At difficulty 4: mostly below threshold.
    At difficulty 3: mixed.
    At difficulty 2: mostly above threshold.
    At difficulty 1: single large transfer >= threshold.
    """
    amount = round(amount, 2)
    if difficulty == 5:
        if amount < max_chunk:
            return [amount]
        chunks = []
        rem = amount
        while rem > 0:
            if rem < max_chunk:
                chunks.append(round(rem, 2))
                break
            low = min(18_000.0, rem * 0.4)
            high = min(max_chunk - 500.0, rem)
            if high <= low:
                target = round(rem / 2.0, 2)
            else:
                target = round(float(rng.uniform(low, high)), 2)
            target = min(target, max_chunk - 500.0)
            chunks.append(target)
            rem = round(rem - target, 2)
        return chunks

    elif difficulty == 4:
        # Mostly below threshold (~10-20% above)
        if amount >= 50_000.0 and rng.random() > 0.15:
            return _split_into_chunks(amount, 5, rng, max_chunk)
        return [round(amount, 2)]

    elif difficulty == 3:
        # Mixed: split ~50% of the time if large
        if amount >= 55_000.0 and rng.random() > 0.45:
            c1 = round(amount * float(rng.uniform(0.4, 0.6)), 2)
            c2 = round(amount - c1, 2)
            return [c1, c2]
        return [round(amount, 2)]

    elif difficulty == 2:
        return [round(amount, 2)]

    else:  # difficulty == 1
        return [round(amount, 2)]


def _generate_legit_mixing(
    rng: np.random.Generator,
    accounts: list,
    ring_accounts: Set[str],
    start_ts: datetime,
    end_ts: datetime,
    count_per_mule: int,
) -> List:
    """Generate legit-looking transactions involving ring accounts during the attack window."""
    from app.sim.generator import Transaction

    mixed_txs = []
    if count_per_mule <= 0 or not ring_accounts:
        return mixed_txs

    non_ring = [a.account_id for a in accounts if a.account_id not in ring_accounts]
    all_acc_dict = {a.account_id: a for a in accounts}
    duration_sec = max(60.0, (end_ts - start_ts).total_seconds())

    for mule_id in ring_accounts:
        n_tx = rng.integers(1, count_per_mule + 1)
        for _ in range(n_tx):
            offset = rng.uniform(0, duration_sec)
            tx_ts = start_ts + timedelta(seconds=offset)
            counterparty = str(rng.choice(non_ring))

            is_outflow = bool(rng.choice([True, False]))
            src = mule_id if is_outflow else counterparty
            dst = counterparty if is_outflow else mule_id

            amount = float(np.round(rng.lognormal(mean=7.5, sigma=0.8), 2))
            amount = max(150.0, min(amount, 25_000.0))

            dst_acc = all_acc_dict.get(dst)
            kind = "merchant_payment" if dst_acc and dst_acc.account_type == "merchant" else "p2p"

            mixed_txs.append(
                Transaction(
                    tx_id="",
                    ts=tx_ts,
                    src=src,
                    dst=dst,
                    amount=amount,
                    kind=kind,
                )
            )
    return mixed_txs


def inject_smurfing(
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 1,
    ring_id: str = "RING-0001",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """
    Smurfing: Source S splits total amount T into k mules;
    mules forward to destination D (or two destinations) within delay window.
    Decoys route intermediate branches.
    """
    from app.sim.generator import Transaction, GroundTruth

    cfg = DIFFICULTY_KNOBS[difficulty]
    k = 6 if difficulty <= 2 else (8 if difficulty <= 4 else 10)
    num_decoys = cfg["num_decoys"]
    picked = _pick_accounts(rng, accounts, 1 + k + 1 + num_decoys)

    src = picked[0]
    mules = picked[1 : 1 + k]
    dst = picked[1 + k]
    decoys = picked[1 + k + 1 :]

    base_volume = float(total_amount_inr) if total_amount_inr is not None else BASE_VOLUMES["smurfing"]
    # Preserve volume across difficulty: distribute base_volume among mules
    chunk_base = base_volume / k

    transactions: List[Transaction] = []
    current_time = start_ts

    # 1. Layer 1: S -> Mules
    layer1_time = current_time
    mule_amounts = []
    for i, mule in enumerate(mules):
        noise = float(rng.uniform(-cfg["split_noise"], cfg["split_noise"]))
        amt = round(chunk_base * (1.0 + noise), 2)
        mule_amounts.append(amt)

        # At high difficulty, split into sub-threshold transfers
        chunks = _split_into_chunks(amt, difficulty, rng)
        for c_idx, c_amt in enumerate(chunks):
            tx_time = layer1_time + timedelta(seconds=float(rng.uniform(10, 60)) + c_idx * 120.0)
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=tx_time,
                    src=src,
                    dst=mule,
                    amount=c_amt,
                    kind="p2p",
                )
            )

    # Hop delay to next layer
    step_delay = _get_hop_delay(rng, difficulty)
    current_time = layer1_time + timedelta(seconds=step_delay)

    # 2. Layer 2: Mules forward to destination (some routed via decoys)
    retention_min, retention_max = cfg["retention_range"]
    decoy_assignment = {}
    for d_idx, d_acc in enumerate(decoys):
        mule_idx = d_idx % len(mules)
        decoy_assignment[mule_idx] = d_acc

    for i, mule in enumerate(mules):
        amt = mule_amounts[i]
        retention = float(rng.uniform(retention_min, retention_max))
        forward_amt = round(amt * retention, 2)

        if i in decoy_assignment:
            # Route mule -> decoy -> dst (guarantees decoy is used!)
            decoy_acc = decoy_assignment[i]
            d_time1 = current_time + timedelta(seconds=float(rng.uniform(10, 60)))
            chunks1 = _split_into_chunks(forward_amt, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks1):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=d_time1 + timedelta(seconds=c_idx * 120.0),
                        src=mule,
                        dst=decoy_acc,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

            decoy_delay = _get_hop_delay(rng, difficulty)
            d_time2 = d_time1 + timedelta(seconds=decoy_delay)
            ret2 = float(rng.uniform(retention_min, 1.0))
            chunks2 = _split_into_chunks(round(forward_amt * ret2, 2), difficulty, rng)
            for c_idx, c_amt in enumerate(chunks2):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=d_time2 + timedelta(seconds=c_idx * 120.0),
                        src=decoy_acc,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )
        else:
            # Direct mule -> dst
            tx_time = current_time + timedelta(seconds=float(rng.uniform(10, 60)))
            chunks = _split_into_chunks(forward_amt, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=tx_time + timedelta(seconds=c_idx * 120.0),
                        src=mule,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

    transactions.sort(key=lambda t: t.ts)
    ring_tx_list = _compress_ring_span(transactions, max_span_hours=35.0)
    # Scale to requested total if provided (preserves structure, rescales amounts)
    ring_tx_list = _scale_ring_total(ring_tx_list, total_amount_inr, difficulty, rng)
    laundering_accounts = {t.src for t in ring_tx_list} | {t.dst for t in ring_tx_list}

    first_ts = ring_tx_list[0].ts
    last_ts = ring_tx_list[-1].ts

    mixed_txs = _generate_legit_mixing(
        rng, accounts, laundering_accounts, first_ts, last_ts, cfg["legit_mix_count"]
    )
    all_txs = ring_tx_list + mixed_txs
    all_txs.sort(key=lambda t: t.ts)

    total_amt = sum(t.amount for t in ring_tx_list)

    gt = GroundTruth(
        ring_id=ring_id,
        ring_type="smurfing",
        difficulty=difficulty,
        ring_accounts=laundering_accounts,
        ring_tx_ids=set(),
        total_amount=total_amt,
        start_ts=first_ts,
        end_ts=last_ts,
        metadata={"num_mules": k, "num_decoys": len(decoys), "mixed_legit_count": len(mixed_txs), "ring_txs": ring_tx_list},
    )
    return all_txs, gt


def inject_round_trip(
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 1,
    ring_id: str = "RING-0002",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """
    Round-trip: Cycle of 3-6 accounts; money returns to origin minus fee.
    Decoys route intermediate branches across distinct hops, ensuring all are connected.
    """
    from app.sim.generator import Transaction, GroundTruth

    cfg = DIFFICULTY_KNOBS[difficulty]
    cycle_len = 4
    num_decoys = cfg["num_decoys"]
    picked = _pick_accounts(rng, accounts, cycle_len + num_decoys)

    cycle_accounts = picked[:cycle_len]
    decoys = picked[cycle_len:]

    base_volume = float(total_amount_inr) if total_amount_inr is not None else BASE_VOLUMES["round_trip"]
    initial_amount = base_volume
    retention_min, retention_max = cfg["retention_range"]

    transactions: List[Transaction] = []
    current_time = start_ts
    current_amount = initial_amount

    # Map each decoy to a cycle hop so ALL decoys are connected
    decoy_map = {d_idx % cycle_len: [] for d_idx in range(len(decoys))}
    for d_idx, d_acc in enumerate(decoys):
        decoy_map[d_idx % cycle_len].append(d_acc)

    for i in range(cycle_len):
        src = cycle_accounts[i]
        dst = cycle_accounts[(i + 1) % cycle_len]

        hop_delay = _get_hop_delay(rng, difficulty)
        current_time = current_time + timedelta(seconds=hop_delay)

        hop_decoys = decoy_map.get(i, [])
        if hop_decoys:
            # Route through each decoy assigned to this hop
            split_share = 0.4 / len(hop_decoys)
            main_share = 1.0 - (split_share * len(hop_decoys))

            # Main hop
            amt_main = round(current_amount * main_share, 2)
            chunks_main = _split_into_chunks(amt_main, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks_main):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=current_time + timedelta(seconds=c_idx * 120.0),
                        src=src,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

            # Decoy branches: src -> decoy -> dst
            decoy_received_total = 0.0
            for d_idx, decoy_acc in enumerate(hop_decoys):
                amt_decoy = round(current_amount * split_share, 2)
                chunks_d1 = _split_into_chunks(amt_decoy, difficulty, rng)
                for c_idx, c_amt in enumerate(chunks_d1):
                    transactions.append(
                        Transaction(
                            tx_id="",
                            ts=current_time + timedelta(seconds=(d_idx + 1) * 30.0 + c_idx * 120.0),
                            src=src,
                            dst=decoy_acc,
                            amount=c_amt,
                            kind="p2p",
                        )
                    )

                decoy_delay = _get_hop_delay(rng, difficulty)
                d_time2 = current_time + timedelta(seconds=decoy_delay)
                ret_d = float(rng.uniform(retention_min, 1.0))
                amt_d_out = round(amt_decoy * ret_d, 2)
                decoy_received_total += amt_d_out
                chunks_d2 = _split_into_chunks(amt_d_out, difficulty, rng)
                for c_idx, c_amt in enumerate(chunks_d2):
                    transactions.append(
                        Transaction(
                            tx_id="",
                            ts=d_time2 + timedelta(seconds=c_idx * 120.0),
                            src=decoy_acc,
                            dst=dst,
                            amount=c_amt,
                            kind="p2p",
                        )
                    )

            current_amount = amt_main + decoy_received_total
        else:
            # Direct hop
            chunks = _split_into_chunks(current_amount, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=current_time + timedelta(seconds=c_idx * 120.0),
                        src=src,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )
            ret = float(rng.uniform(retention_min, retention_max))
            current_amount = current_amount * ret

    transactions.sort(key=lambda t: t.ts)
    ring_tx_list = _compress_ring_span(transactions, max_span_hours=35.0)
    # Scale to requested total if provided
    ring_tx_list = _scale_ring_total(ring_tx_list, total_amount_inr, difficulty, rng)
    laundering_accounts = {t.src for t in ring_tx_list} | {t.dst for t in ring_tx_list}

    first_ts = ring_tx_list[0].ts
    last_ts = ring_tx_list[-1].ts

    mixed_txs = _generate_legit_mixing(
        rng, accounts, laundering_accounts, first_ts, last_ts, cfg["legit_mix_count"]
    )
    all_txs = ring_tx_list + mixed_txs
    all_txs.sort(key=lambda t: t.ts)

    total_amt = sum(t.amount for t in ring_tx_list)

    gt = GroundTruth(
        ring_id=ring_id,
        ring_type="round_trip",
        difficulty=difficulty,
        ring_accounts=laundering_accounts,
        ring_tx_ids=set(),
        total_amount=total_amt,
        start_ts=first_ts,
        end_ts=last_ts,
        metadata={"cycle_length": cycle_len, "num_decoys": len(decoys), "mixed_legit_count": len(mixed_txs), "ring_txs": ring_tx_list},
    )
    return all_txs, gt


def inject_mule_chain(
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 1,
    ring_id: str = "RING-0003",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """
    Mule Chain: Linear chain of 4-8 accounts; each forwards 95-99% within delay window.
    Decoys route intermediate branches, ensuring all are connected.
    """
    from app.sim.generator import Transaction, GroundTruth

    cfg = DIFFICULTY_KNOBS[difficulty]
    chain_len = 5
    num_decoys = cfg["num_decoys"]
    picked = _pick_accounts(rng, accounts, chain_len + num_decoys)

    chain_accounts = picked[:chain_len]
    decoys = picked[chain_len:]

    base_volume = float(total_amount_inr) if total_amount_inr is not None else BASE_VOLUMES["mule_chain"]
    current_amount = base_volume
    retention_min, retention_max = cfg["retention_range"]

    transactions: List[Transaction] = []
    current_time = start_ts

    decoy_map = {d_idx % (chain_len - 1): [] for d_idx in range(len(decoys))}
    for d_idx, d_acc in enumerate(decoys):
        decoy_map[d_idx % (chain_len - 1)].append(d_acc)

    for i in range(chain_len - 1):
        src = chain_accounts[i]
        dst = chain_accounts[i + 1]

        hop_delay = _get_hop_delay(rng, difficulty)
        current_time = current_time + timedelta(seconds=hop_delay)

        hop_decoys = decoy_map.get(i, [])
        if hop_decoys:
            split_share = 0.4 / len(hop_decoys)
            main_share = 1.0 - (split_share * len(hop_decoys))

            amt_main = round(current_amount * main_share, 2)
            chunks_main = _split_into_chunks(amt_main, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks_main):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=current_time + timedelta(seconds=c_idx * 120.0),
                        src=src,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

            decoy_received_total = 0.0
            for d_idx, decoy_acc in enumerate(hop_decoys):
                amt_decoy = round(current_amount * split_share, 2)
                chunks_d1 = _split_into_chunks(amt_decoy, difficulty, rng)
                for c_idx, c_amt in enumerate(chunks_d1):
                    transactions.append(
                        Transaction(
                            tx_id="",
                            ts=current_time + timedelta(seconds=(d_idx + 1) * 30.0 + c_idx * 120.0),
                            src=src,
                            dst=decoy_acc,
                            amount=c_amt,
                            kind="p2p",
                        )
                    )

                decoy_delay = _get_hop_delay(rng, difficulty)
                d_time2 = current_time + timedelta(seconds=decoy_delay)
                ret_d = float(rng.uniform(retention_min, 1.0))
                amt_d_out = round(amt_decoy * ret_d, 2)
                decoy_received_total += amt_d_out
                chunks_d2 = _split_into_chunks(amt_d_out, difficulty, rng)
                for c_idx, c_amt in enumerate(chunks_d2):
                    transactions.append(
                        Transaction(
                            tx_id="",
                            ts=d_time2 + timedelta(seconds=c_idx * 120.0),
                            src=decoy_acc,
                            dst=dst,
                            amount=c_amt,
                            kind="p2p",
                        )
                    )

            current_amount = amt_main + decoy_received_total
        else:
            chunks = _split_into_chunks(current_amount, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=current_time + timedelta(seconds=c_idx * 120.0),
                        src=src,
                        dst=dst,
                        amount=c_amt,
                        kind="p2p",
                    )
                )
            ret = float(rng.uniform(retention_min, retention_max))
            current_amount = current_amount * ret

    transactions.sort(key=lambda t: t.ts)
    ring_tx_list = _compress_ring_span(transactions, max_span_hours=35.0)
    # Scale to requested total if provided
    ring_tx_list = _scale_ring_total(ring_tx_list, total_amount_inr, difficulty, rng)
    laundering_accounts = {t.src for t in ring_tx_list} | {t.dst for t in ring_tx_list}

    first_ts = ring_tx_list[0].ts
    last_ts = ring_tx_list[-1].ts

    mixed_txs = _generate_legit_mixing(
        rng, accounts, laundering_accounts, first_ts, last_ts, cfg["legit_mix_count"]
    )
    all_txs = ring_tx_list + mixed_txs
    all_txs.sort(key=lambda t: t.ts)

    total_amt = sum(t.amount for t in ring_tx_list)

    gt = GroundTruth(
        ring_id=ring_id,
        ring_type="mule_chain",
        difficulty=difficulty,
        ring_accounts=laundering_accounts,
        ring_tx_ids=set(),
        total_amount=total_amt,
        start_ts=first_ts,
        end_ts=last_ts,
        metadata={"chain_length": chain_len, "num_decoys": len(decoys), "mixed_legit_count": len(mixed_txs), "ring_txs": ring_tx_list},
    )
    return all_txs, gt


def inject_hybrid(
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 1,
    ring_id: str = "RING-0004",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """
    Hybrid: Smurfing -> chain -> cycle back to source.
    Source S splits to mules M1..Mk -> mules funnel into chain C1 -> C2 -> loop back to S.
    """
    from app.sim.generator import Transaction, GroundTruth

    cfg = DIFFICULTY_KNOBS[difficulty]
    num_mules = 4 if difficulty <= 2 else 6
    chain_len = 3
    num_decoys = cfg["num_decoys"]
    picked = _pick_accounts(rng, accounts, 1 + num_mules + chain_len + num_decoys)

    src = picked[0]
    mules = picked[1 : 1 + num_mules]
    chain_nodes = picked[1 + num_mules : 1 + num_mules + chain_len]
    decoys = picked[1 + num_mules + chain_len :]

    base_volume = float(total_amount_inr) if total_amount_inr is not None else BASE_VOLUMES["hybrid"]
    chunk_base = base_volume / num_mules
    retention_min, retention_max = cfg["retention_range"]

    transactions: List[Transaction] = []
    current_time = start_ts

    # 1. Smurfing phase: S -> Mules
    layer1_time = current_time
    mule_amounts = []
    for i, mule in enumerate(mules):
        amt = round(chunk_base * (1.0 + float(rng.uniform(-cfg["split_noise"], cfg["split_noise"]))), 2)
        mule_amounts.append(amt)
        chunks = _split_into_chunks(amt, difficulty, rng)
        for c_idx, c_amt in enumerate(chunks):
            tx_time = layer1_time + timedelta(seconds=float(rng.uniform(10, 60)) + c_idx * 120.0)
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=tx_time,
                    src=src,
                    dst=mule,
                    amount=c_amt,
                    kind="p2p",
                )
            )

    # Hop delay
    step_delay = _get_hop_delay(rng, difficulty)
    current_time = layer1_time + timedelta(seconds=step_delay)

    # 2. Mules forward into first chain node C1 (some via decoys)
    c1 = chain_nodes[0]
    total_forwarded_to_c1 = 0.0

    decoy_assignment = {}
    for d_idx, d_acc in enumerate(decoys):
        decoy_assignment[d_idx % len(mules)] = d_acc

    for i, mule in enumerate(mules):
        amt = round(mule_amounts[i] * float(rng.uniform(retention_min, retention_max)), 2)

        if i in decoy_assignment:
            decoy_acc = decoy_assignment[i]
            d_time1 = current_time + timedelta(seconds=float(rng.uniform(10, 60)))
            chunks1 = _split_into_chunks(amt, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks1):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=d_time1 + timedelta(seconds=c_idx * 120.0),
                        src=mule,
                        dst=decoy_acc,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

            decoy_delay = _get_hop_delay(rng, difficulty)
            d_time2 = d_time1 + timedelta(seconds=decoy_delay)
            amt_d2 = round(amt * float(rng.uniform(retention_min, 1.0)), 2)
            total_forwarded_to_c1 += amt_d2
            chunks2 = _split_into_chunks(amt_d2, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks2):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=d_time2 + timedelta(seconds=c_idx * 120.0),
                        src=decoy_acc,
                        dst=c1,
                        amount=c_amt,
                        kind="p2p",
                    )
                )
        else:
            total_forwarded_to_c1 += amt
            tx_time = current_time + timedelta(seconds=float(rng.uniform(10, 60)))
            chunks = _split_into_chunks(amt, difficulty, rng)
            for c_idx, c_amt in enumerate(chunks):
                transactions.append(
                    Transaction(
                        tx_id="",
                        ts=tx_time + timedelta(seconds=c_idx * 120.0),
                        src=mule,
                        dst=c1,
                        amount=c_amt,
                        kind="p2p",
                    )
                )

    # 3. Chain phase: C1 -> C2 -> ...
    chain_amt = total_forwarded_to_c1
    current_node = c1
    for next_node in chain_nodes[1:]:
        step_delay = _get_hop_delay(rng, difficulty)
        current_time = current_time + timedelta(seconds=step_delay)
        chain_amt = round(chain_amt * float(rng.uniform(retention_min, retention_max)), 2)
        chunks = _split_into_chunks(chain_amt, difficulty, rng)
        for c_idx, c_amt in enumerate(chunks):
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=current_time + timedelta(seconds=c_idx * 120.0),
                    src=current_node,
                    dst=next_node,
                    amount=c_amt,
                    kind="p2p",
                )
            )
        current_node = next_node

    # 4. Cycle phase: Last chain node loops back to Source S
    step_delay = _get_hop_delay(rng, difficulty)
    current_time = current_time + timedelta(seconds=step_delay)
    final_amt = round(chain_amt * float(rng.uniform(retention_min, retention_max)), 2)
    chunks = _split_into_chunks(final_amt, difficulty, rng)
    for c_idx, c_amt in enumerate(chunks):
        transactions.append(
            Transaction(
                tx_id="",
                ts=current_time + timedelta(seconds=c_idx * 120.0),
                src=current_node,
                dst=src,
                amount=c_amt,
                kind="p2p",
            )
        )

    transactions.sort(key=lambda t: t.ts)
    ring_tx_list = _compress_ring_span(transactions, max_span_hours=35.0)
    # Scale to requested total if provided
    ring_tx_list = _scale_ring_total(ring_tx_list, total_amount_inr, difficulty, rng)
    laundering_accounts = {t.src for t in ring_tx_list} | {t.dst for t in ring_tx_list}

    first_ts = ring_tx_list[0].ts
    last_ts = ring_tx_list[-1].ts

    mixed_txs = _generate_legit_mixing(
        rng, accounts, laundering_accounts, first_ts, last_ts, cfg["legit_mix_count"]
    )
    all_txs = ring_tx_list + mixed_txs
    all_txs.sort(key=lambda t: t.ts)

    total_amt = sum(t.amount for t in ring_tx_list)

    gt = GroundTruth(
        ring_id=ring_id,
        ring_type="hybrid",
        difficulty=difficulty,
        ring_accounts=laundering_accounts,
        ring_tx_ids=set(),
        total_amount=total_amt,
        start_ts=first_ts,
        end_ts=last_ts,
        metadata={"num_mules": num_mules, "chain_length": chain_len, "num_decoys": len(decoys), "mixed_legit_count": len(mixed_txs), "ring_txs": ring_tx_list},
    )
    return all_txs, gt


def inject_stealth(
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 5,
    ring_id: str = "RING-0005",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """
    Stealth: ALWAYS runs at difficulty 5, ignoring the difficulty argument.
    All transactions are strictly below SIM_NAIVE_THRESHOLD.
    """
    difficulty = 5  # Rule: stealth always runs at difficulty 5!

    base_types = ["smurfing", "round_trip", "mule_chain", "hybrid"]
    base_type = str(rng.choice(base_types))

    if base_type == "smurfing":
        txs, gt = inject_smurfing(rng, accounts, start_ts, difficulty=5, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif base_type == "round_trip":
        txs, gt = inject_round_trip(rng, accounts, start_ts, difficulty=5, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif base_type == "mule_chain":
        txs, gt = inject_mule_chain(rng, accounts, start_ts, difficulty=5, ring_id=ring_id, total_amount_inr=total_amount_inr)
    else:
        txs, gt = inject_hybrid(rng, accounts, start_ts, difficulty=5, ring_id=ring_id, total_amount_inr=total_amount_inr)

    gt.ring_type = "stealth"
    gt.difficulty = 5
    gt.metadata["base_type"] = base_type
    return txs, gt


def inject_attack(
    attack_type: str,
    rng: np.random.Generator,
    accounts: list,
    start_ts: datetime,
    difficulty: int = 1,
    ring_id: str = "RING-0001",
    total_amount_inr: Optional[float] = None,
) -> Tuple[List, "GroundTruth"]:
    """Dispatch to specific attack injector by name."""
    if attack_type == "smurfing":
        return inject_smurfing(rng, accounts, start_ts, difficulty=difficulty, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif attack_type == "round_trip":
        return inject_round_trip(rng, accounts, start_ts, difficulty=difficulty, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif attack_type == "mule_chain":
        return inject_mule_chain(rng, accounts, start_ts, difficulty=difficulty, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif attack_type == "hybrid":
        return inject_hybrid(rng, accounts, start_ts, difficulty=difficulty, ring_id=ring_id, total_amount_inr=total_amount_inr)
    elif attack_type == "stealth":
        return inject_stealth(rng, accounts, start_ts, difficulty=difficulty, ring_id=ring_id, total_amount_inr=total_amount_inr)
    else:
        raise ValueError(f"Unknown attack type: {attack_type}")
