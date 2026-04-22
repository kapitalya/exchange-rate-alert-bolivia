"""
arima/analysis.py
─────────────────
Exploratory data analysis module for the Exchange Rate Alert System.

Provides:
  - load_rates()            : Load historical rates from MySQL via Django ORM
  - plot_series()           : Full time-series chart
  - run_adf_test()          : Augmented Dickey-Fuller stationarity test
  - plot_acf_pacf()         : ACF/PACF diagnostic plots
  - make_stationary()       : Difference series until stationary
  - infer_d()               : Automatically infer integration order d
"""

import logging
from typing import Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — safe for server use
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.tsa.stattools import adfuller

logger = logging.getLogger("arima")


# ─────────────────────────────────────────────────────────────
# 1. DATA LOADING
# ─────────────────────────────────────────────────────────────

def load_rates(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    column: str = "rate_parallel",
) -> pd.Series:
    """
    Load exchange rate data from MySQL via Django ORM.

    Args:
        start_date: ISO date string 'YYYY-MM-DD', default = all history
        end_date:   ISO date string 'YYYY-MM-DD', default = today
        column:     'rate_parallel' (default) or 'rate_official'

    Returns:
        pd.Series with DatetimeIndex, float dtype, sorted ascending.
    """
    # Import here to allow using this module standalone (with Django setup)
    from exchange_monitor.models import ExchangeRate

    qs = ExchangeRate.objects.filter(rate_parallel__isnull=False).order_by("date")
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)

    records = list(qs.values("date", column))
    if not records:
        raise ValueError("No exchange rate data found in the database.")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    series = df[column].astype(float)

    logger.info(
        "Loaded %d observations from %s to %s",
        len(series), series.index.min().date(), series.index.max().date(),
    )
    return series


# ─────────────────────────────────────────────────────────────
# 2. TIME-SERIES PLOT
# ─────────────────────────────────────────────────────────────

def plot_series(
    series: pd.Series,
    title: str = "Tipo de Cambio Paralelo BOB/USD",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Plot the full historical exchange rate series with trend annotation.

    Args:
        series:     pd.Series with DatetimeIndex
        title:      Chart title
        save_path:  If provided, saves figure to this path
        show:       If True, calls plt.show() (use only in notebooks)

    Returns:
        matplotlib Figure object
    """
    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(series.index, series.values, linewidth=1.5, color="#1f77b4", label="Tipo paralelo")

    # 30-day rolling mean overlay
    rolling = series.rolling(window=30, min_periods=10).mean()
    ax.plot(rolling.index, rolling.values, linewidth=2, color="#ff7f0e",
            linestyle="--", label="Media móvil 30 días", alpha=0.85)

    # Formatting
    ax.set_title(title, fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel("Fecha")
    ax.set_ylabel("BOB / USD")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=30)
    ax.legend()
    ax.grid(alpha=0.3)

    # Stats annotation
    stats_text = (
        f"Min: {series.min():.2f}  |  "
        f"Max: {series.max():.2f}  |  "
        f"Media: {series.mean():.2f}  |  "
        f"Último: {series.iloc[-1]:.2f}"
    )
    fig.text(0.5, -0.02, stats_text, ha="center", fontsize=9, color="gray")

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
        logger.info("Series plot saved to %s", save_path)
    if show:
        plt.show()

    return fig


# ─────────────────────────────────────────────────────────────
# 3. STATIONARITY TEST — AUGMENTED DICKEY-FULLER
# ─────────────────────────────────────────────────────────────

def run_adf_test(
    series: pd.Series,
    significance_level: float = 0.05,
    verbose: bool = True,
) -> dict:
    """
    Augmented Dickey-Fuller unit-root test for stationarity.

    H₀: Series has a unit root (non-stationary).
    H₁: Series is stationary.

    Args:
        series:             Time series to test
        significance_level: Alpha level (default 0.05)
        verbose:            Print human-readable result

    Returns:
        dict with keys: adf_stat, p_value, is_stationary, critical_values, lags_used
    """
    result = adfuller(series.dropna(), autolag="AIC")
    adf_stat, p_value, lags_used, n_obs, critical_values, _ = result

    is_stationary = p_value < significance_level

    output = {
        "adf_stat": adf_stat,
        "p_value": p_value,
        "is_stationary": is_stationary,
        "critical_values": critical_values,
        "lags_used": lags_used,
        "n_obs": n_obs,
    }

    if verbose:
        print("=" * 55)
        print("  Augmented Dickey-Fuller Test — Stationarity Check")
        print("=" * 55)
        print(f"  ADF statistic  : {adf_stat:>10.4f}")
        print(f"  p-value        : {p_value:>10.6f}")
        print(f"  Lags used      : {lags_used}")
        print(f"  Observations   : {n_obs}")
        print("  Critical values:")
        for key, val in critical_values.items():
            marker = " ◄" if adf_stat < val else ""
            print(f"    {key:>5}  →  {val:8.4f}{marker}")
        print("-" * 55)
        if is_stationary:
            print("  ✅  ESTACIONARIA (reject H₀, p < {})".format(significance_level))
            print("     → ARIMA d=0 puede ser apropiado.")
        else:
            print("  ❌  NO ESTACIONARIA (fail to reject H₀, p ≥ {})".format(significance_level))
            print("     → Se requiere diferenciación (d ≥ 1).")
        print("=" * 55)

    logger.info("ADF test: stat=%.4f p=%.6f stationary=%s", adf_stat, p_value, is_stationary)
    return output


# ─────────────────────────────────────────────────────────────
# 4. ACF / PACF PLOTS
# ─────────────────────────────────────────────────────────────

def plot_acf_pacf(
    series: pd.Series,
    lags: int = 40,
    title_suffix: str = "",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Side-by-side ACF and PACF plots for ARIMA parameter identification.

    Interpretation guide:
      PACF cuts off at lag p  →  AR(p) component
      ACF  cuts off at lag q  →  MA(q) component

    Args:
        series:       Stationary (or differenced) time series
        lags:         Number of lags to display
        title_suffix: Added to subplot titles
        save_path:    File path to save figure
        show:         Show interactive plot

    Returns:
        matplotlib Figure
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 4))

    plot_acf(series.dropna(), lags=lags, ax=axes[0], alpha=0.05)
    axes[0].set_title(f"ACF — Autocorrelation Function {title_suffix}", fontweight="bold")
    axes[0].set_xlabel("Lag")
    axes[0].set_ylabel("Autocorrelation")
    axes[0].grid(alpha=0.3)

    plot_pacf(series.dropna(), lags=lags, ax=axes[1], alpha=0.05, method="ywm")
    axes[1].set_title(f"PACF — Partial Autocorrelation {title_suffix}", fontweight="bold")
    axes[1].set_xlabel("Lag")
    axes[1].set_ylabel("Partial Autocorrelation")
    axes[1].grid(alpha=0.3)

    plt.suptitle(
        "Diagnóstico ACF/PACF — Selección de parámetros ARIMA(p,d,q)",
        fontsize=13, fontweight="bold", y=1.02,
    )
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
        logger.info("ACF/PACF plot saved to %s", save_path)
    if show:
        plt.show()

    return fig


# ─────────────────────────────────────────────────────────────
# 5. DIFFERENCING UTILITY
# ─────────────────────────────────────────────────────────────

def difference_series(series: pd.Series, order: int = 1) -> pd.Series:
    """
    Apply first or seasonal differencing.

    Args:
        series: Original time series
        order:  Number of times to difference (1 = first-difference)

    Returns:
        Differenced series (length = len(series) - order)
    """
    diff = series.copy()
    for i in range(order):
        diff = diff.diff().dropna()
    logger.debug("Applied %d-order differencing. New length: %d", order, len(diff))
    return diff


# ─────────────────────────────────────────────────────────────
# 6. AUTOMATIC d INFERENCE
# ─────────────────────────────────────────────────────────────

def infer_d(
    series: pd.Series,
    max_d: int = 2,
    significance_level: float = 0.05,
    verbose: bool = True,
) -> int:
    """
    Automatically infer the integration order d by differencing until
    the Augmented Dickey-Fuller test rejects the null hypothesis.

    Args:
        series:             Original time series
        max_d:              Maximum differencing order to try
        significance_level: ADF alpha level
        verbose:            Print progress

    Returns:
        Minimum d that achieves stationarity (0, 1, or 2)
    """
    current = series.copy()
    for d in range(max_d + 1):
        result = run_adf_test(current, significance_level=significance_level, verbose=False)
        if verbose:
            status = "ESTACIONARIA ✅" if result["is_stationary"] else "NO estacionaria ❌"
            print(f"  d={d} | ADF p={result['p_value']:.5f} | {status}")
        if result["is_stationary"]:
            if verbose:
                print(f"\n  → d óptimo seleccionado: {d}")
            logger.info("Inferred d=%d (p=%.5f)", d, result["p_value"])
            return d
        current = difference_series(current, order=1)

    logger.warning("Series not stationary after max_d=%d differencing. Defaulting to d=%d.", max_d, max_d)
    return max_d


# ─────────────────────────────────────────────────────────────
# 7. VOLATILITY ANALYSIS
# ─────────────────────────────────────────────────────────────

def compute_rolling_volatility(
    series: pd.Series,
    window: int = 30,
) -> pd.DataFrame:
    """
    Compute rolling standard deviation and coefficient of variation.

    Args:
        series: Exchange rate series
        window: Rolling window in trading days

    Returns:
        DataFrame with columns: rate, rolling_std, rolling_cv, pct_change
    """
    df = pd.DataFrame({"rate": series})
    df["rolling_std"] = series.rolling(window=window, min_periods=10).std()
    df["rolling_mean"] = series.rolling(window=window, min_periods=10).mean()
    df["rolling_cv"] = df["rolling_std"] / df["rolling_mean"]
    df["pct_change"] = series.pct_change() * 100
    return df


def plot_volatility(
    series: pd.Series,
    window: int = 30,
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """Plot rolling volatility alongside the exchange rate."""
    vol_df = compute_rolling_volatility(series, window=window)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    ax1.plot(vol_df.index, vol_df["rate"], color="#1f77b4", linewidth=1.5, label="BOB/USD paralelo")
    ax1.set_ylabel("BOB / USD")
    ax1.set_title("Tipo de Cambio y Volatilidad — Mercado Paralelo Boliviano", fontweight="bold")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.fill_between(vol_df.index, 0, vol_df["rolling_std"],
                     alpha=0.4, color="#d62728", label=f"Desvío estándar móvil ({window}d)")
    ax2.plot(vol_df.index, vol_df["rolling_std"], color="#d62728", linewidth=1)
    ax2.set_ylabel("Volatilidad (σ)")
    ax2.set_xlabel("Fecha")
    ax2.legend()
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=30)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
    if show:
        plt.show()

    return fig
