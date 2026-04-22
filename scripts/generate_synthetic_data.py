"""
scripts/generate_synthetic_data.py
────────────────────────────────────
Generate realistic synthetic BOB/USD parallel market exchange rate data
from April 2023 to March 2026 and insert it into MySQL.

Behaviour modelled:
  2023 Q2-Q3  : Stable ~6.98–7.10 (post-pandemic recovery plateau)
  2023 Q4     : Progressive climb toward 8.00 (dollar shortage signals)
  2024 Q1     : High volatility 7.50–9.50 (political uncertainty)
  2024 Q2     : Partial stabilisation 8.80–9.20 (policy intervention)
  2024 Q3-Q4  : New upswing 9.00–10.50 (fuel subsidies pressure)
  2025        : Moderate upward trend with corrections 10.00–12.00
  2026 Q1     : Continuation trend 11.50–13.50

Usage:
  python manage.py shell < scripts/generate_synthetic_data.py
  # OR
  python scripts/generate_synthetic_data.py  (with Django setup)
"""

import os
import sys
import django

# ── Django setup (if running as standalone script) ────────────
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

import random
import numpy as np
import pandas as pd
from datetime import date
from exchange_monitor.models import ExchangeRate

# ─────────────────────────────────────────────────────────────
# SEED FOR REPRODUCIBILITY
# ─────────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)

# ─────────────────────────────────────────────────────────────
# DATE RANGE — Business days only
# ─────────────────────────────────────────────────────────────
START_DATE = "2023-04-03"
END_DATE   = "2026-03-31"

bdays = pd.bdate_range(start=START_DATE, end=END_DATE, freq="B")
print(f"Generating {len(bdays)} trading days from {START_DATE} to {END_DATE}...")


# ─────────────────────────────────────────────────────────────
# SEGMENT DEFINITIONS
# (start_date, end_date, start_price, end_price, daily_vol, event_label)
# ─────────────────────────────────────────────────────────────
SEGMENTS = [
    # (start,      end,         p_start, p_end,  sigma, label)
    ("2023-04-03", "2023-07-31", 6.97,   7.05,   0.008, "stable_plateau"),
    ("2023-08-01", "2023-09-30", 7.05,   7.40,   0.012, "mild_pressure"),
    ("2023-10-01", "2023-12-29", 7.40,   8.00,   0.020, "escalation_q4_2023"),
    ("2024-01-02", "2024-03-29", 8.00,   9.20,   0.045, "high_volatility_q1_2024"),
    ("2024-04-01", "2024-06-28", 9.20,   8.90,   0.025, "stabilisation_q2_2024"),
    ("2024-07-01", "2024-09-30", 8.90,   9.80,   0.030, "new_upswing_q3_2024"),
    ("2024-10-01", "2024-12-31", 9.80,   10.50,  0.035, "continued_pressure_q4_2024"),
    ("2025-01-02", "2025-06-30", 10.50,  11.20,  0.030, "moderate_trend_h1_2025"),
    ("2025-07-01", "2025-12-31", 11.20,  12.00,  0.038, "continuation_h2_2025"),
    ("2026-01-02", "2026-03-31", 12.00,  13.50,  0.040, "trend_q1_2026"),
]

OFFICIAL_RATE = 6.96  # BCB fixed rate throughout this period


def generate_segment_prices(start_price, end_price, n_days, daily_vol, segment_label):
    """
    Generate price path using Geometric Brownian Motion with linear drift.

    Formula:
        S_t = S_{t-1} * exp(μ + σ * ε_t)
        μ = log(end/start) / n  (daily drift toward target)
    """
    if n_days <= 0:
        return []

    drift = np.log(end_price / start_price) / n_days
    prices = [start_price]

    for _ in range(n_days - 1):
        # Add occasional regime-shock events (1% probability per day)
        shock = 0.0
        if random.random() < 0.01:
            shock = random.choice([-1, 1]) * random.uniform(0.02, 0.06)

        noise = np.random.normal(0, daily_vol)
        new_price = prices[-1] * np.exp(drift + noise + shock)

        # Clip to reasonable bounds to avoid numerical explosions
        new_price = max(new_price, 4.0)
        new_price = min(new_price, 25.0)
        prices.append(new_price)

    return prices


# ─────────────────────────────────────────────────────────────
# BUILD FULL PRICE SERIES
# ─────────────────────────────────────────────────────────────
all_dates = []
all_prices = []

for (seg_start, seg_end, p0, p1, sigma, label) in SEGMENTS:
    seg_days = pd.bdate_range(start=seg_start, end=seg_end, freq="B")
    prices = generate_segment_prices(p0, p1, len(seg_days), sigma, label)
    all_dates.extend(seg_days.tolist())
    all_prices.extend(prices[:len(seg_days)])
    print(f"  Segment {label}: {len(seg_days)} days, {p0:.2f} → {p1:.2f}")

# Build DataFrame
df = pd.DataFrame({"date": all_dates, "rate_parallel": all_prices})
df["date"] = pd.to_datetime(df["date"]).dt.date
df = df.drop_duplicates(subset=["date"]).sort_values("date")
df["rate_parallel"] = df["rate_parallel"].round(4)
df["rate_official"] = OFFICIAL_RATE
df["spread"] = (df["rate_parallel"] - OFFICIAL_RATE).round(4)

# Random volume indicator (1-5)
df["volume_indicator"] = np.random.randint(1, 6, size=len(df))

print(f"\nTotal records: {len(df)}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"Rate range: {df['rate_parallel'].min():.4f} — {df['rate_parallel'].max():.4f}")


# ─────────────────────────────────────────────────────────────
# INSERT TO DATABASE
# ─────────────────────────────────────────────────────────────
print("\nInserting into MySQL (skipping existing dates)...")

existing_dates = set(ExchangeRate.objects.values_list("date", flat=True))
records_to_insert = [
    ExchangeRate(
        date=row["date"],
        rate_parallel=row["rate_parallel"],
        rate_official=row["rate_official"],
        spread=row["spread"],
        volume_indicator=int(row["volume_indicator"]),
        source="synthetic_generator",
        notes=f"Synthetic data — {row['date'].strftime('%Y-%m')}",
    )
    for _, row in df.iterrows()
    if row["date"] not in existing_dates
]

if records_to_insert:
    ExchangeRate.objects.bulk_create(records_to_insert, batch_size=500)
    print(f"✅ Inserted {len(records_to_insert)} records.")
else:
    print("⚠️  All dates already exist in database. No records inserted.")

print("\nSynthetic data generation complete!")
print(f"Run 'python manage.py runserver' and visit http://localhost:8000\n")
