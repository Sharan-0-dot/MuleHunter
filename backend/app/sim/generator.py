"""
Transaction simulator and legit traffic generator with hard negatives.

Generates:
1. ~2,000 Accounts: ~1,400 individual, ~400 merchant, ~200 business.
2. Legit traffic patterns:
   - P2P transfers (individual -> individual)
   - Merchant payments (legit fan-in: individuals -> merchants)
   - Payroll (legit fan-out: business -> employee individuals)
   - Rent & utilities (individual -> business)
   - Large purchases (hard negatives: individual -> merchant, >= 60,000 INR)
3. Deterministic reproducibility via explicit numpy.random.Generator.
4. Zero label leakage: Transaction dataclass carries only observable fields.
   Ground truth is stored strictly in separate structures.
5. Batch and streaming interfaces.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional, Set, Tuple
import numpy as np

from app.config import SIM_NAIVE_THRESHOLD


# ---------------------------------------------------------------------------
# Core Data Models (Strictly observable transaction features, no label leakage)
# ---------------------------------------------------------------------------
@dataclass
class Transaction:
    tx_id: str
    ts: datetime
    src: str
    dst: str
    amount: float
    kind: str  # p2p, merchant_payment, payroll, rent, large_purchase, ring_hop


@dataclass
class GroundTruth:
    ring_id: str
    ring_type: str
    difficulty: int
    ring_accounts: Set[str]
    ring_tx_ids: Set[str]
    total_amount: float
    start_ts: datetime
    end_ts: datetime
    metadata: dict = field(default_factory=dict)


@dataclass
class DatasetGroundTruth:
    rings: Dict[str, GroundTruth] = field(default_factory=dict)
    ring_accounts: Set[str] = field(default_factory=set)
    ring_tx_ids: Set[str] = field(default_factory=set)
    tx_to_ring: Dict[str, str] = field(default_factory=dict)
    account_to_rings: Dict[str, Set[str]] = field(default_factory=dict)
    prevented_tx_count: int = 0
    prevented_amount_inr: float = 0.0


@dataclass
class Account:
    account_id: str
    account_type: str  # individual, merchant, business
    baseline_activity_rate: float
    typical_amount: float


# ---------------------------------------------------------------------------
# Accounts Pool Generator
# ---------------------------------------------------------------------------
def generate_accounts_pool(
    n_individuals: int = 1400,
    n_merchants: int = 400,
    n_businesses: int = 200,
) -> List[Account]:
    """Generate fixed deterministic ~2,000 account pool."""
    accounts: List[Account] = []
    idx = 1

    # 1. Individuals (~1,400): ACC-0001 to ACC-1400
    for _ in range(n_individuals):
        acc = Account(
            account_id=f"ACC-{idx:04d}",
            account_type="individual",
            baseline_activity_rate=1.5,   # ~1-3 tx / day
            typical_amount=2500.0,
        )
        accounts.append(acc)
        idx += 1

    # 2. Merchants (~400): ACC-1401 to ACC-1800
    for _ in range(n_merchants):
        acc = Account(
            account_id=f"ACC-{idx:04d}",
            account_type="merchant",
            baseline_activity_rate=20.0,  # receives many payments
            typical_amount=800.0,
        )
        accounts.append(acc)
        idx += 1

    # 3. Businesses (~200): ACC-1801 to ACC-2000
    for _ in range(n_businesses):
        acc = Account(
            account_id=f"ACC-{idx:04d}",
            account_type="business",
            baseline_activity_rate=5.0,
            typical_amount=50000.0,
        )
        accounts.append(acc)
        idx += 1

    return accounts


# ---------------------------------------------------------------------------
# Simulated Clock
# ---------------------------------------------------------------------------
class SimulatedClock:
    """Simulated clock with speed multiplier (1x-20x) and advance controls."""

    def __init__(
        self,
        start_ts: Optional[datetime] = None,
        speed: float = 1.0,
    ):
        self.current_ts = start_ts or datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
        self.speed = max(1.0, min(20.0, float(speed)))
        self.is_running = False

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def set_speed(self, speed: float):
        self.speed = max(1.0, min(20.0, float(speed)))

    def advance(self, seconds: float):
        self.current_ts += timedelta(seconds=float(seconds))

    def now(self) -> datetime:
        return self.current_ts


# ---------------------------------------------------------------------------
# Legit Traffic Generator
# ---------------------------------------------------------------------------
def _generate_legit_traffic(
    rng: np.random.Generator,
    accounts: List[Account],
    start_ts: datetime,
    duration_hours: float,
) -> List[Transaction]:
    """
    Generate all legitimate background traffic including hard negatives:
    - P2P (individual to individual)
    - Merchant payment (legit fan-in)
    - Payroll (legit fan-out)
    - Rent & utilities
    - Large one-off purchases (hard negatives >= threshold)
    """
    transactions: List[Transaction] = []
    total_seconds = max(1.0, duration_hours * 3600.0)

    individuals = [a.account_id for a in accounts if a.account_type == "individual"]
    merchants = [a.account_id for a in accounts if a.account_type == "merchant"]
    businesses = [a.account_id for a in accounts if a.account_type == "business"]

    n_ind = len(individuals)
    n_merch = len(merchants)
    n_biz = len(businesses)

    # 1. P2P transfers: ~2,500 tx per 24 hours (~104/hr)
    n_p2p = int(round(104.0 * duration_hours))
    if n_p2p > 0:
        src_idx = rng.integers(0, n_ind, size=n_p2p)
        dst_offset = rng.integers(1, n_ind, size=n_p2p)
        dst_idx = (src_idx + dst_offset) % n_ind
        ts_offsets = rng.uniform(0, total_seconds, size=n_p2p)
        amounts = rng.lognormal(mean=7.5, sigma=0.9, size=n_p2p)
        amounts = np.clip(amounts, 200.0, 25000.0)

        for i in range(n_p2p):
            t = start_ts + timedelta(seconds=float(ts_offsets[i]))
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=t,
                    src=individuals[src_idx[i]],
                    dst=individuals[dst_idx[i]],
                    amount=float(np.round(amounts[i], 2)),
                    kind="p2p",
                )
            )

    # 2. Merchant Payments (Legit Fan-In): ~3,500 tx per 24 hours (~145/hr)
    n_merch_tx = int(round(145.0 * duration_hours))
    if n_merch_tx > 0:
        src_idx = rng.integers(0, n_ind, size=n_merch_tx)
        # Power-law popularity for merchants (fan-in pattern)
        weights = 1.0 / np.linspace(1, 20, n_merch)
        probs = weights / np.sum(weights)
        dst_idx = rng.choice(n_merch, size=n_merch_tx, p=probs)
        ts_offsets = rng.uniform(0, total_seconds, size=n_merch_tx)
        amounts = rng.lognormal(mean=6.8, sigma=0.8, size=n_merch_tx)
        amounts = np.clip(amounts, 100.0, 15000.0)

        for i in range(n_merch_tx):
            t = start_ts + timedelta(seconds=float(ts_offsets[i]))
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=t,
                    src=individuals[src_idx[i]],
                    dst=merchants[dst_idx[i]],
                    amount=float(np.round(amounts[i], 2)),
                    kind="merchant_payment",
                )
            )

    # 3. Payroll (Legit Fan-Out): businesses pay their assigned employees
    # Assign 10 to 25 employees to each business deterministically
    emp_assignments = {}
    for b_idx, b_id in enumerate(businesses):
        start_emp = (b_idx * 7) % (n_ind - 25)
        emp_count = 10 + (b_idx % 15)
        emp_assignments[b_id] = [individuals[start_emp + j] for j in range(emp_count)]

    # Run payroll for a subset of businesses depending on duration
    # E.g. ~10 businesses run payroll per 24 hours
    n_payroll_runs = max(1, int(round(10.0 * (duration_hours / 24.0))))
    payroll_biz = rng.choice(businesses, size=min(n_biz, n_payroll_runs), replace=False)

    for biz_id in payroll_biz:
        employees = emp_assignments[biz_id]
        p_time_offset = float(rng.uniform(0, total_seconds))
        biz_p_time = start_ts + timedelta(seconds=p_time_offset)
        # Base salary between 35k and 85k (some above 50k threshold!)
        base_salary = float(rng.uniform(35000.0, 85000.0))

        for emp_id in employees:
            # Small jitter in amount (±1%) and time (within 15 minutes)
            jitter = float(rng.uniform(0.99, 1.01))
            amt = float(np.round(base_salary * jitter, 2))
            t_jitter = float(rng.uniform(0, 900))
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=biz_p_time + timedelta(seconds=t_jitter),
                    src=biz_id,
                    dst=emp_id,
                    amount=amt,
                    kind="payroll",
                )
            )

    # 4. Rent / Utilities: ~250 tx per 24 hours (~10/hr)
    n_rent = int(round(10.0 * duration_hours))
    if n_rent > 0:
        src_idx = rng.integers(0, n_ind, size=n_rent)
        dst_idx = rng.integers(0, n_biz, size=n_rent)
        ts_offsets = rng.uniform(0, total_seconds, size=n_rent)
        amounts = rng.uniform(8000.0, 42000.0, size=n_rent)

        for i in range(n_rent):
            t = start_ts + timedelta(seconds=float(ts_offsets[i]))
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=t,
                    src=individuals[src_idx[i]],
                    dst=businesses[dst_idx[i]],
                    amount=float(np.round(amounts[i], 2)),
                    kind="rent",
                )
            )

    # 5. Large One-Off Purchases (Hard Negatives >= 60,000 INR):
    # ~35 tx per 24 hours (~1.5/hr)
    n_large = max(5, int(round(1.5 * duration_hours)))
    if n_large > 0:
        src_idx = rng.integers(0, n_ind, size=n_large)
        dst_idx = rng.integers(0, n_merch, size=n_large)
        ts_offsets = rng.uniform(0, total_seconds, size=n_large)
        # Uniformly distributed between 60,000 and 300,000 INR
        amounts = rng.uniform(60000.0, 300000.0, size=n_large)

        for i in range(n_large):
            t = start_ts + timedelta(seconds=float(ts_offsets[i]))
            transactions.append(
                Transaction(
                    tx_id="",
                    ts=t,
                    src=individuals[src_idx[i]],
                    dst=merchants[dst_idx[i]],
                    amount=float(np.round(amounts[i], 2)),
                    kind="large_purchase",
                )
            )

    return transactions


# ---------------------------------------------------------------------------
# Batch Dataset Generator (For M3 training & evaluation)
# ---------------------------------------------------------------------------
def generate_dataset(
    seed: int,
    difficulty: int = 1,
    duration_hours: float = 24.0,
    attacks: Optional[List[str]] = None,
    start_ts: Optional[datetime] = None,
    frozen_accounts: Optional[Set[str]] = None,
) -> Tuple[List[Transaction], DatasetGroundTruth]:
    """
    Generate complete dataset (legit traffic + injected attacks) sorted by ts.
    Fast batch execution. Zero label leakage on Transaction.
    """
    from app.sim.attacks import inject_attack

    rng = np.random.default_rng(seed)
    base_ts = start_ts or datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
    accounts = generate_accounts_pool()
    frozen = frozen_accounts or set()

    # 1. Generate legit traffic
    transactions = _generate_legit_traffic(rng, accounts, base_ts, duration_hours)

    # 2. Inject attacks if specified
    dataset_gt = DatasetGroundTruth()
    attack_list = attacks or []
    ring_tx_obj_to_ring: Dict[int, str] = {}

    if attack_list:
        total_seconds = duration_hours * 3600.0
        n_attacks = len(attack_list)
        interval = total_seconds / (n_attacks + 1)

        for i, atk_type in enumerate(attack_list):
            ring_id = f"RING-{i + 1:04d}"
            atk_start = base_ts + timedelta(seconds=(i + 1) * interval * 0.5)
            atk_txs, atk_gt = inject_attack(
                attack_type=atk_type,
                rng=rng,
                accounts=accounts,
                start_ts=atk_start,
                difficulty=difficulty,
                ring_id=ring_id,
            )
            transactions.extend(atk_txs)
            dataset_gt.rings[ring_id] = atk_gt
            dataset_gt.ring_accounts.update(atk_gt.ring_accounts)

            # Map ring transaction objects to this ring
            for r_tx in atk_gt.metadata.get("ring_txs", []):
                ring_tx_obj_to_ring[id(r_tx)] = ring_id

            for acc in atk_gt.ring_accounts:
                if acc not in dataset_gt.account_to_rings:
                    dataset_gt.account_to_rings[acc] = set()
                dataset_gt.account_to_rings[acc].add(ring_id)

    # 3. Sort strictly by timestamp
    transactions.sort(key=lambda tx: tx.ts)

    # 4. Apply frozen account filter (prevention hook)
    filtered_txs: List[Transaction] = []
    prevented_count = 0
    prevented_inr = 0.0

    for tx in transactions:
        if tx.src in frozen:
            prevented_count += 1
            prevented_inr += tx.amount
        else:
            filtered_txs.append(tx)

    dataset_gt.prevented_tx_count = prevented_count
    dataset_gt.prevented_amount_inr = float(np.round(prevented_inr, 2))

    # 5. Assign consecutive tx_id and finalize ground truth ring_tx_ids without relying on kind
    final_txs: List[Transaction] = []
    for idx, tx in enumerate(filtered_txs, start=1):
        tx.tx_id = f"TX-{idx:08d}"
        final_txs.append(tx)

        # Check if this transaction object belongs to a ring
        r_id = ring_tx_obj_to_ring.get(id(tx))
        if r_id:
            dataset_gt.rings[r_id].ring_tx_ids.add(tx.tx_id)
            dataset_gt.ring_tx_ids.add(tx.tx_id)
            dataset_gt.tx_to_ring[tx.tx_id] = r_id

    return final_txs, dataset_gt


# ---------------------------------------------------------------------------
# Streaming Interface (For live demo & background tasks)
# ---------------------------------------------------------------------------
class TransactionStream:
    """
    Streaming iterator that yields transactions in timestamp order.
    Supports dynamic attack injection, clock speed controls, and account freezing.
    """

    def __init__(
        self,
        seed: int = 42,
        speed: float = 1.0,
        start_ts: Optional[datetime] = None,
        frozen_accounts: Optional[Set[str]] = None,
    ):
        self.rng = np.random.default_rng(seed)
        self.clock = SimulatedClock(start_ts, speed)
        self.accounts = generate_accounts_pool()
        self.frozen_accounts = set(frozen_accounts or [])
        self.pending_queue: List[Transaction] = []
        self.ground_truth = DatasetGroundTruth()
        self.ring_tx_obj_to_ring: Dict[int, str] = {}
        self.tx_counter = 0
        self.prevented_inr = 0.0
        self.prevented_count = 0

    def start(self):
        self.clock.start()

    def stop(self):
        self.clock.stop()

    def set_speed(self, speed: float):
        self.clock.set_speed(speed)

    def freeze_account(self, account_id: str):
        self.frozen_accounts.add(account_id)

    def inject_attack(self, attack_type: str, difficulty: int = 1) -> str:
        """Inject an attack starting at the current simulated time."""
        from app.sim.attacks import inject_attack

        ring_id = f"RING-{len(self.ground_truth.rings) + 1:04d}"
        atk_txs, atk_gt = inject_attack(
            attack_type=attack_type,
            rng=self.rng,
            accounts=self.accounts,
            start_ts=self.clock.now(),
            difficulty=difficulty,
            ring_id=ring_id,
        )

        self.ground_truth.rings[ring_id] = atk_gt
        self.ground_truth.ring_accounts.update(atk_gt.ring_accounts)
        for r_tx in atk_gt.metadata.get("ring_txs", []):
            self.ring_tx_obj_to_ring[id(r_tx)] = ring_id

        for acc in atk_gt.ring_accounts:
            if acc not in self.ground_truth.account_to_rings:
                self.ground_truth.account_to_rings[acc] = set()
            self.ground_truth.account_to_rings[acc].add(ring_id)

        self.pending_queue.extend(atk_txs)
        self.pending_queue.sort(key=lambda t: t.ts)
        return ring_id

    def advance(self, sim_seconds: float) -> List[Transaction]:
        """Advance simulated clock by sim_seconds and return transactions generated in that window."""
        target_ts = self.clock.now() + timedelta(seconds=float(sim_seconds))
        duration_hours = sim_seconds / 3600.0

        # Generate legit transactions in this window if queue is running low
        if len(self.pending_queue) < 100:
            new_legit = _generate_legit_traffic(
                self.rng, self.accounts, self.clock.now(), max(duration_hours, 1.0)
            )
            self.pending_queue.extend(new_legit)
            self.pending_queue.sort(key=lambda t: t.ts)

        ready_txs = []
        remaining = []

        for tx in self.pending_queue:
            if tx.ts <= target_ts:
                # Check frozen account
                if tx.src in self.frozen_accounts:
                    self.prevented_count += 1
                    self.prevented_inr += tx.amount
                else:
                    self.tx_counter += 1
                    tx.tx_id = f"TX-{self.tx_counter:08d}"
                    r_id = self.ring_tx_obj_to_ring.get(id(tx))
                    if r_id:
                        self.ground_truth.rings[r_id].ring_tx_ids.add(tx.tx_id)
                        self.ground_truth.ring_tx_ids.add(tx.tx_id)
                        self.ground_truth.tx_to_ring[tx.tx_id] = r_id
                    ready_txs.append(tx)
            else:
                remaining.append(tx)

        self.pending_queue = remaining
        self.clock.current_ts = target_ts
        return ready_txs

    def __iter__(self) -> Iterator[Transaction]:
        return self

    def __next__(self) -> Transaction:
        # Advance by 10 simulated seconds if queue empty
        while not self.pending_queue:
            self.advance(10.0)

        tx = self.pending_queue.pop(0)
        if tx.src in self.frozen_accounts:
            self.prevented_count += 1
            self.prevented_inr += tx.amount
            return self.__next__()

        self.tx_counter += 1
        tx.tx_id = f"TX-{self.tx_counter:08d}"
        r_id = self.ring_tx_obj_to_ring.get(id(tx))
        if r_id:
            self.ground_truth.rings[r_id].ring_tx_ids.add(tx.tx_id)
            self.ground_truth.ring_tx_ids.add(tx.tx_id)
            self.ground_truth.tx_to_ring[tx.tx_id] = r_id
        self.clock.current_ts = tx.ts
        return tx
