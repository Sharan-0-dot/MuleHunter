import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from app.sim.generator import TransactionStream, generate_dataset

seed = 42
start_ts = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

# 1. Batch
batch_txs, _ = generate_dataset(seed=seed, duration_hours=24.0, attacks=None, start_ts=start_ts)

# 2. Existing streaming: advance in 5-second steps for 24h
stream = TransactionStream(seed=seed, start_ts=start_ts)
stream_txs = []
step_sec = 5.0
steps = int(24 * 3600 / step_sec)
for s in range(steps):
    ready = stream.advance(step_sec)
    stream_txs.extend(ready)

df_b = pd.DataFrame([{'kind': t.kind, 'amount': t.amount, 'ts': t.ts} for t in batch_txs])
df_s = pd.DataFrame([{'kind': t.kind, 'amount': t.amount, 'ts': t.ts} for t in stream_txs])

print('=== 1. TOTAL TX COUNT (24h) ===')
print(f'Batch: {len(df_b)} txs | Streaming: {len(df_s)} txs')

print('\n=== 2. KIND MIX ===')
b_mix = df_b['kind'].value_counts()
s_mix = df_s['kind'].value_counts()
mix_cmp = pd.DataFrame({'batch': b_mix, 'streaming': s_mix}).fillna(0)
print(mix_cmp)

print('\n=== 3. AMOUNT PERCENTILES ===')
print('BATCH:')
print(df_b['amount'].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.99]))
print('\nSTREAMING:')
print(df_s['amount'].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.99]))

print('\n=== 4. PAYROLL BATCH SIZE AND TIMING ===')
b_pay = df_b[df_b['kind'] == 'payroll']
s_pay = df_s[df_s['kind'] == 'payroll']
print(f'Batch payroll txs: {len(b_pay)} | Streaming payroll txs: {len(s_pay)}')

print('\n=== 5. TX PER HOUR ===')
df_b['hour'] = df_b['ts'].apply(lambda t: int((t - start_ts).total_seconds() // 3600))
df_s['hour'] = df_s['ts'].apply(lambda t: int((t - start_ts).total_seconds() // 3600))
print(f'Batch mean tx/hr: {df_b.groupby("hour").size().mean():.1f}')
print(f'Streaming mean tx/hr: {df_s.groupby("hour").size().mean():.1f}')
