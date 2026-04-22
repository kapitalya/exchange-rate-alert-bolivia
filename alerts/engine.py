"""
alerts/engine.py
─────────────────
Alert evaluation engine for the Exchange Rate Alert System.

Four alert types:
  1. absolute_threshold  — Rate exceeds a fixed BOB value
  2. pct_change          — Forecast shows X% change in next 7 days
  3. high_volatility     — Recent std dev > 2× 90-day historical std dev
  4. unusual_spread      — Parallel-official spread exceeds 90th percentile

Each evaluator returns an AlertResult dataclass.
The engine evaluates all active configurations and fires alerts.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("alerts")


# ─────────────────────────────────────────────────────────────
# DATA STRUCTURE
# ─────────────────────────────────────────────────────────────

@dataclass
class AlertResult:
    """Result of a single alert evaluation."""
    fired: bool
    alert_type: str
    severity: str           # green | yellow | red
    trigger_value: float
    current_rate: float
    message_es: str
    message_en: str
    metadata: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# TYPE 1 — ABSOLUTE THRESHOLD
# ─────────────────────────────────────────────────────────────

def evaluate_absolute_threshold(
    forecast_values: List[float],
    threshold: float,
    current_rate: float,
    severity: str = "yellow",
) -> AlertResult:
    """
    Fire when any forecasted value exceeds a fixed BOB/USD threshold.

    Rationale: When the parallel rate breaches a key psychological level
    (e.g. 9.00, 10.00, 12.00 BOB/USD), it signals significant market stress
    and requires immediate attention from financial managers.

    Args:
        forecast_values: List of next 14 days forecasted rates
        threshold:       BOB/USD level that triggers the alert
        current_rate:    Today's exchange rate
        severity:        Alert severity (green/yellow/red)

    Returns:
        AlertResult
    """
    max_forecast = max(forecast_values)
    fired = max_forecast > threshold
    days_to_breach = None

    if fired:
        for i, val in enumerate(forecast_values):
            if val > threshold:
                days_to_breach = i + 1
                break

    message_es = (
        f"⚠️ UMBRAL SUPERADO: El pronóstico proyecta un tipo de cambio de "
        f"BOB {max_forecast:.4f}, superando el umbral definido de BOB {threshold:.4f} "
        f"en aproximadamente {days_to_breach} día(s) hábil(es)."
        if fired else
        f"✅ Umbral OK: Pronóstico máximo BOB {max_forecast:.4f} < umbral BOB {threshold:.4f}."
    )
    message_en = (
        f"⚠️ THRESHOLD BREACHED: Forecast projects BOB {max_forecast:.4f}, "
        f"exceeding the defined threshold of BOB {threshold:.4f} "
        f"in approximately {days_to_breach} business day(s)."
        if fired else
        f"✅ Threshold OK: Max forecast BOB {max_forecast:.4f} < threshold BOB {threshold:.4f}."
    )

    return AlertResult(
        fired=fired,
        alert_type="absolute_threshold",
        severity=severity if fired else "green",
        trigger_value=max_forecast,
        current_rate=current_rate,
        message_es=message_es,
        message_en=message_en,
        metadata={"threshold": threshold, "days_to_breach": days_to_breach, "max_forecast": max_forecast},
    )


# ─────────────────────────────────────────────────────────────
# TYPE 2 — PERCENTAGE CHANGE
# ─────────────────────────────────────────────────────────────

def evaluate_pct_change(
    forecast_values: List[float],
    threshold_pct: float,
    current_rate: float,
    lookback_days: int = 7,
    severity: str = "yellow",
) -> AlertResult:
    """
    Fire when forecast shows >= X% change over next `lookback_days` days.

    Rationale: Sudden directional moves — even if still below an absolute
    threshold — may indicate a regime change in the parallel market.
    A 5% weekly move is exceptional and financially material.

    Args:
        forecast_values:  Forecasted values (first N used for lookback_days)
        threshold_pct:    Percentage change that triggers alert
        current_rate:     Today's rate (base for % change)
        lookback_days:    Days ahead to measure change
        severity:         Alert severity

    Returns:
        AlertResult
    """
    window = forecast_values[:lookback_days]
    if not window:
        return AlertResult(
            fired=False, alert_type="pct_change", severity="green",
            trigger_value=0.0, current_rate=current_rate,
            message_es="Sin datos suficientes de pronóstico.",
            message_en="Insufficient forecast data.",
        )

    max_val = max(window)
    min_val = min(window)

    # Measure both upside and downside risk
    pct_up = ((max_val - current_rate) / current_rate) * 100
    pct_down = ((current_rate - min_val) / current_rate) * 100
    max_change_pct = max(abs(pct_up), abs(pct_down))
    direction = "ALZA" if pct_up >= abs(pct_down) else "BAJA"
    direction_en = "UP" if pct_up >= abs(pct_down) else "DOWN"

    fired = max_change_pct >= threshold_pct

    message_es = (
        f"⚠️ VARIACIÓN SIGNIFICATIVA: Se proyecta un movimiento de "
        f"{max_change_pct:.2f}% en {direction} en los próximos {lookback_days} días "
        f"(umbral: {threshold_pct:.1f}%). Actual: BOB {current_rate:.4f}."
        if fired else
        f"✅ Variación dentro del rango: {max_change_pct:.2f}% < umbral {threshold_pct:.1f}%."
    )
    message_en = (
        f"⚠️ SIGNIFICANT VARIATION: A {max_change_pct:.2f}% move {direction_en} projected "
        f"in the next {lookback_days} days (threshold: {threshold_pct:.1f}%). "
        f"Current: BOB {current_rate:.4f}."
        if fired else
        f"✅ Variation within range: {max_change_pct:.2f}% < threshold {threshold_pct:.1f}%."
    )

    return AlertResult(
        fired=fired,
        alert_type="pct_change",
        severity=severity if fired else "green",
        trigger_value=max_change_pct,
        current_rate=current_rate,
        message_es=message_es,
        message_en=message_en,
        metadata={
            "threshold_pct": threshold_pct,
            "pct_change": max_change_pct,
            "direction": direction,
            "lookback_days": lookback_days,
        },
    )


# ─────────────────────────────────────────────────────────────
# TYPE 3 — HIGH VOLATILITY
# ─────────────────────────────────────────────────────────────

def evaluate_high_volatility(
    historical_rates: pd.Series,
    current_rate: float,
    short_window: int = 7,
    long_window: int = 90,
    multiplier: float = 2.0,
    severity: str = "red",
) -> AlertResult:
    """
    Fire when recent volatility exceeds `multiplier` times the long-run baseline.

    Rationale: The Bolivian parallel market can spike in volatility during
    political events (elections, policy announcements, dollar restrictions).
    This alert detects abnormal clustering of volatility — the hallmark
    of market stress episodes.

    Formula:
        recent_std   = std(rates, last short_window days)
        baseline_std = std(rates, last long_window days)
        fired        = recent_std > multiplier * baseline_std

    Args:
        historical_rates: Full daily rate series
        current_rate:     Latest rate
        short_window:     Recent volatility window (days)
        long_window:      Baseline volatility window (days)
        multiplier:       How many times above baseline to trigger
        severity:         Alert severity

    Returns:
        AlertResult
    """
    if len(historical_rates) < long_window:
        return AlertResult(
            fired=False, alert_type="high_volatility", severity="green",
            trigger_value=0.0, current_rate=current_rate,
            message_es="Insuficiente historial para evaluar volatilidad.",
            message_en="Insufficient history for volatility evaluation.",
        )

    recent_std = float(historical_rates.iloc[-short_window:].std())
    baseline_std = float(historical_rates.iloc[-long_window:].std())

    if baseline_std == 0:
        return AlertResult(
            fired=False, alert_type="high_volatility", severity="green",
            trigger_value=0.0, current_rate=current_rate,
            message_es="Desviación histórica cero. No se puede evaluar.",
            message_en="Zero historical std dev. Cannot evaluate.",
        )

    volatility_ratio = recent_std / baseline_std
    fired = volatility_ratio > multiplier

    message_es = (
        f"🔴 ALTA VOLATILIDAD: La volatilidad reciente ({short_window}d) es "
        f"{volatility_ratio:.2f}x la volatilidad histórica ({long_window}d). "
        f"σ reciente={recent_std:.4f} vs σ base={baseline_std:.4f}. "
        f"Umbral: {multiplier:.1f}x."
        if fired else
        f"✅ Volatilidad normal: ratio={volatility_ratio:.2f} < umbral={multiplier:.1f}x."
    )
    message_en = (
        f"🔴 HIGH VOLATILITY: Recent ({short_window}d) volatility is "
        f"{volatility_ratio:.2f}x the historical ({long_window}d) baseline. "
        f"Recent σ={recent_std:.4f} vs baseline σ={baseline_std:.4f}. "
        f"Threshold: {multiplier:.1f}x."
        if fired else
        f"✅ Normal volatility: ratio={volatility_ratio:.2f} < threshold={multiplier:.1f}x."
    )

    return AlertResult(
        fired=fired,
        alert_type="high_volatility",
        severity=severity if fired else "green",
        trigger_value=volatility_ratio,
        current_rate=current_rate,
        message_es=message_es,
        message_en=message_en,
        metadata={
            "recent_std": recent_std,
            "baseline_std": baseline_std,
            "volatility_ratio": volatility_ratio,
            "multiplier": multiplier,
            "short_window": short_window,
            "long_window": long_window,
        },
    )


# ─────────────────────────────────────────────────────────────
# TYPE 4 — UNUSUAL SPREAD
# ─────────────────────────────────────────────────────────────

def evaluate_unusual_spread(
    parallel_rate: float,
    official_rate: float,
    historical_spreads: pd.Series,
    percentile_threshold: float = 90.0,
    severity: str = "red",
) -> AlertResult:
    """
    Fire when the parallel-official spread exceeds its historical 90th percentile.

    Rationale: The spread between the official BCB rate (fixed at ~6.96 BOB/USD
    for years) and the parallel market rate is the key indicator of
    macroeconomic stress in Bolivia. A widening spread signals capital flight,
    dollar shortage, or policy uncertainty. Monitoring the spread is arguably
    more informative than the absolute rate alone.

    Args:
        parallel_rate:         Today's parallel market rate
        official_rate:         Today's official BCB rate
        historical_spreads:    Series of historical spread values
        percentile_threshold:  Percentile cutoff for "unusual" (default 90th)
        severity:              Alert severity

    Returns:
        AlertResult
    """
    current_spread = parallel_rate - official_rate
    p_threshold = float(np.percentile(historical_spreads.dropna(), percentile_threshold))
    fired = current_spread > p_threshold

    pct_above = ((current_spread - p_threshold) / p_threshold * 100) if p_threshold > 0 else 0

    message_es = (
        f"🔴 SPREAD INUSUAL: El spread actual entre el tipo paralelo (BOB {parallel_rate:.4f}) "
        f"y el oficial (BOB {official_rate:.4f}) es BOB {current_spread:.4f}, "
        f"superando el percentil {percentile_threshold:.0f} histórico (BOB {p_threshold:.4f}) "
        f"en un {pct_above:.1f}%."
        if fired else
        f"✅ Spread dentro del rango histórico: BOB {current_spread:.4f} < P{percentile_threshold:.0f} BOB {p_threshold:.4f}."
    )
    message_en = (
        f"🔴 UNUSUAL SPREAD: Current parallel (BOB {parallel_rate:.4f}) vs "
        f"official (BOB {official_rate:.4f}) spread is BOB {current_spread:.4f}, "
        f"exceeding the historical {percentile_threshold:.0f}th percentile (BOB {p_threshold:.4f}) "
        f"by {pct_above:.1f}%."
        if fired else
        f"✅ Spread within historical range: BOB {current_spread:.4f} < P{percentile_threshold:.0f} BOB {p_threshold:.4f}."
    )

    return AlertResult(
        fired=fired,
        alert_type="unusual_spread",
        severity=severity if fired else "green",
        trigger_value=current_spread,
        current_rate=parallel_rate,
        message_es=message_es,
        message_en=message_en,
        metadata={
            "current_spread": current_spread,
            "percentile_threshold": percentile_threshold,
            "p_threshold_value": p_threshold,
            "official_rate": official_rate,
            "pct_above_threshold": pct_above,
        },
    )


# ─────────────────────────────────────────────────────────────
# MAIN ENGINE — EVALUATE ALL ACTIVE CONFIGURATIONS
# ─────────────────────────────────────────────────────────────

def run_alert_engine(verbose: bool = True) -> List[AlertResult]:
    """
    Main entry point. Evaluates all active AlertConfiguration records
    and persists TriggeredAlert entries for any that fire.

    Called by the APScheduler job every business day after data update.

    Returns:
        List of AlertResult objects (fired ones only)
    """
    from exchange_monitor.models import (
        AlertConfiguration, ExchangeRate, Forecast,
        ForecastPoint, TriggeredAlert,
    )

    fired_results = []

    # ── Load latest data ──────────────────────────────────────
    latest_rate_obj = ExchangeRate.objects.order_by("-date").first()
    if not latest_rate_obj:
        logger.warning("No exchange rate data available. Skipping alert evaluation.")
        return []

    current_rate = float(latest_rate_obj.rate_parallel)
    official_rate = float(latest_rate_obj.rate_official or 6.96)

    # Historical series (last 180 days)
    qs = ExchangeRate.objects.order_by("date").filter(
        rate_parallel__isnull=False
    ).values_list("date", "rate_parallel", "spread")
    hist_df = pd.DataFrame(list(qs), columns=["date", "rate_parallel", "spread"])
    hist_df["date"] = pd.to_datetime(hist_df["date"])
    hist_df = hist_df.set_index("date").sort_index()

    hist_series = hist_df["rate_parallel"].astype(float)
    spread_series = hist_df["spread"].dropna().astype(float)

    # Active forecast points
    active_forecast = Forecast.objects.filter(is_active=True, status="success").first()
    forecast_values = []
    if active_forecast:
        fps = list(
            ForecastPoint.objects.filter(forecast=active_forecast)
            .order_by("step_ahead")
            .values_list("predicted_value", flat=True)
        )
        forecast_values = [float(v) for v in fps]

    # ── Evaluate each active alert configuration ──────────────
    active_configs = AlertConfiguration.objects.filter(is_active=True)
    logger.info("Evaluating %d active alert configurations...", active_configs.count())

    for config in active_configs:
        result = None

        try:
            if config.alert_type == "absolute_threshold" and forecast_values:
                result = evaluate_absolute_threshold(
                    forecast_values=forecast_values,
                    threshold=float(config.threshold_value),
                    current_rate=current_rate,
                    severity=config.severity,
                )

            elif config.alert_type == "pct_change" and forecast_values:
                result = evaluate_pct_change(
                    forecast_values=forecast_values,
                    threshold_pct=float(config.threshold_value),
                    current_rate=current_rate,
                    lookback_days=config.lookback_days,
                    severity=config.severity,
                )

            elif config.alert_type == "high_volatility":
                result = evaluate_high_volatility(
                    historical_rates=hist_series,
                    current_rate=current_rate,
                    short_window=config.lookback_days,
                    long_window=90,
                    multiplier=float(config.threshold_value or 2.0),
                    severity=config.severity,
                )

            elif config.alert_type == "unusual_spread" and len(spread_series) >= 30:
                result = evaluate_unusual_spread(
                    parallel_rate=current_rate,
                    official_rate=official_rate,
                    historical_spreads=spread_series,
                    percentile_threshold=float(config.threshold_value or 90.0),
                    severity=config.severity,
                )

        except Exception as exc:
            logger.error("Error evaluating config %d (%s): %s", config.id, config.alert_type, exc)
            continue

        if result is None:
            continue

        if verbose:
            status = "🔔 FIRED" if result.fired else "  quiet"
            logger.info("[%s] %s — %s: %s", status, config.name, result.alert_type, result.message_es[:80])

        if result.fired:
            fired_results.append(result)

            # Persist triggered alert
            triggered = TriggeredAlert.objects.create(
                configuration=config,
                forecast=active_forecast,
                current_rate=current_rate,
                trigger_value=result.trigger_value,
                message_es=result.message_es,
                message_en=result.message_en,
                severity=result.severity,
            )

            # Dispatch notifications
            from alerts.notifications import send_alert_notifications
            send_alert_notifications(triggered, config)

    logger.info("Alert engine complete. %d alerts fired.", len(fired_results))
    return fired_results
