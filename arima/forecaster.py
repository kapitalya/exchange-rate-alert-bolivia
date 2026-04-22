"""
arima/forecaster.py
───────────────────
Core ARIMA training, grid search, forecasting, and validation module.

Public API:
  grid_search_arima()   : Find best (p,d,q) by AIC
  train_arima()         : Fit ARIMA with given parameters
  generate_forecast()   : Produce 14-day forecast with confidence intervals
  save_forecast_to_db() : Persist forecast to MySQL
  plot_forecast()       : Visualise historical + forecast + CI bands
  walk_forward_validation() : Model accuracy assessment
  generate_metrics_report() : Text report of validation metrics
"""

import itertools
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX

logger = logging.getLogger("arima")


# ─────────────────────────────────────────────────────────────
# 1. GRID SEARCH — BEST (p, d, q) BY AIC
# ─────────────────────────────────────────────────────────────

def grid_search_arima(
    series: pd.Series,
    max_p: int = 3,
    max_d: int = 2,
    max_q: int = 3,
    verbose: bool = True,
    save_to_db: bool = True,
) -> Dict:
    """
    Exhaustive grid search over ARIMA(p,d,q) parameter space.

    Strategy:
      - Evaluates all combinations in range [0..max_p] x [0..max_d] x [0..max_q]
      - Fits each model using Maximum Likelihood Estimation
      - Selects the model minimising AIC (Akaike Information Criterion)
      - AIC balances goodness-of-fit against model complexity

    Why AIC over BIC?
      AIC tends to select richer models, which is preferable for forecasting
      tasks (vs. BIC which is more parsimonious — better for inference).

    Args:
        series:     Stationary or raw series (d handles differencing)
        max_p:      Maximum AR order to test
        max_d:      Maximum integration order to test
        max_q:      Maximum MA order to test
        verbose:    Print progress table
        save_to_db: Persist best params to ARIMAModelConfig table

    Returns:
        dict with keys: best_p, best_d, best_q, best_aic, best_bic,
                        all_results, duration_seconds
    """
    orders = list(itertools.product(range(max_p + 1), range(max_d + 1), range(max_q + 1)))
    results = []
    best_aic = np.inf
    best_order = (1, 1, 1)  # sensible default
    best_result = None

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Grid Search ARIMA — {len(orders)} combinations")
        print(f"  p ∈ [0,{max_p}] · d ∈ [0,{max_d}] · q ∈ [0,{max_q}]")
        print(f"{'='*60}")
        print(f"  {'Order':>12} | {'AIC':>10} | {'BIC':>10} | Status")
        print(f"  {'-'*50}")

    start_time = time.time()

    for (p, d, q) in orders:
        if p == 0 and q == 0:
            continue  # Skip trivial random walk (no AR or MA terms)
        try:
            model = ARIMA(series, order=(p, d, q))
            fitted = model.fit(method="innovations_mle")
            aic = fitted.aic
            bic = fitted.bic
            results.append({"p": p, "d": d, "q": q, "aic": aic, "bic": bic, "status": "ok"})

            if verbose:
                marker = " ◄ BEST" if aic < best_aic else ""
                print(f"  ARIMA({p},{d},{q}):   AIC={aic:10.3f} | BIC={bic:10.3f}{marker}")

            if aic < best_aic:
                best_aic = aic
                best_order = (p, d, q)
                best_result = fitted

        except Exception as exc:
            results.append({"p": p, "d": d, "q": q, "aic": np.nan, "bic": np.nan, "status": str(exc)[:60]})
            if verbose:
                print(f"  ARIMA({p},{d},{q}):   FAILED — {str(exc)[:50]}")

    duration = time.time() - start_time
    best_p, best_d, best_q = best_order

    if verbose:
        print(f"\n{'='*60}")
        print(f"  ✅ BEST MODEL: ARIMA({best_p},{best_d},{best_q})")
        print(f"     AIC = {best_aic:.4f}")
        print(f"     Duration: {duration:.1f}s")
        print(f"{'='*60}\n")

    logger.info(
        "Grid search complete. Best: ARIMA(%d,%d,%d) AIC=%.4f in %.1fs",
        best_p, best_d, best_q, best_aic, duration,
    )

    # Persist to database
    if save_to_db:
        try:
            from exchange_monitor.models import ARIMAModelConfig
            ARIMAModelConfig.objects.create(
                p=best_p, d=best_d, q=best_q,
                aic=best_aic,
                bic=best_result.bic if best_result else None,
                log_likelihood=best_result.llf if best_result else None,
                is_current=True,
                trained_on_observations=len(series),
                grid_search_duration_seconds=duration,
                notes=f"Grid search {max_p}x{max_d}x{max_q}, {len(results)} models evaluated.",
            )
            logger.info("ARIMA config saved to DB.")
        except Exception as exc:
            logger.warning("Could not save ARIMA config to DB: %s", exc)

    return {
        "best_p": best_p, "best_d": best_d, "best_q": best_q,
        "best_aic": best_aic,
        "best_bic": best_result.bic if best_result else None,
        "fitted_model": best_result,
        "all_results": results,
        "duration_seconds": duration,
    }


# ─────────────────────────────────────────────────────────────
# 2. TRAIN ARIMA MODEL
# ─────────────────────────────────────────────────────────────

def train_arima(
    series: pd.Series,
    p: int,
    d: int,
    q: int,
    verbose: bool = True,
) -> ARIMA:
    """
    Fit ARIMA(p,d,q) to the provided series.

    Args:
        series: Historical exchange rate series (DatetimeIndex)
        p:      AR order
        d:      Integration order
        q:      MA order
        verbose: Print model summary

    Returns:
        Fitted statsmodels ARIMAResults object

    Raises:
        RuntimeError: If model fails to converge
    """
    logger.info("Training ARIMA(%d,%d,%d) on %d observations...", p, d, q, len(series))

    try:
        model = ARIMA(series, order=(p, d, q), freq=series.index.inferred_freq or "B")
        fitted = model.fit(method="innovations_mle")
    except Exception:
        # Fallback: try without freq specification
        try:
            model = ARIMA(series, order=(p, d, q))
            fitted = model.fit()
        except Exception as exc:
            logger.error("ARIMA(%d,%d,%d) failed to converge: %s", p, d, q, exc)
            raise RuntimeError(f"ARIMA({p},{d},{q}) failed: {exc}") from exc

    if verbose:
        print(fitted.summary())

    logger.info(
        "ARIMA(%d,%d,%d) fitted. AIC=%.4f BIC=%.4f",
        p, d, q, fitted.aic, fitted.bic,
    )
    return fitted


# ─────────────────────────────────────────────────────────────
# 3. GENERATE FORECAST
# ─────────────────────────────────────────────────────────────

def generate_forecast(
    fitted_model,
    forecast_days: int = 14,
    confidence_levels: Tuple[float, ...] = (0.80, 0.95),
    series: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Generate multi-step ahead forecast with confidence intervals.

    Args:
        fitted_model:       Fitted ARIMAResults object
        forecast_days:      Number of business days to forecast
        confidence_levels:  Tuple of CI levels (e.g. 0.80 and 0.95)
        series:             Original series (used to derive future dates)

    Returns:
        DataFrame with columns:
          date, predicted, ci_lower_80, ci_upper_80, ci_lower_95, ci_upper_95, step
    """
    forecast_result = fitted_model.get_forecast(steps=forecast_days)
    predicted_mean = forecast_result.predicted_mean
    summary_frame = forecast_result.summary_frame()

    # Build forecast date range (business days)
    last_date = fitted_model.model.data.dates[-1] if hasattr(fitted_model.model.data, "dates") and \
        fitted_model.model.data.dates is not None else pd.Timestamp.today()

    future_dates = pd.bdate_range(start=last_date + pd.offsets.BDay(1), periods=forecast_days)

    rows = []
    for i, date in enumerate(future_dates):
        rows.append({
            "date": date,
            "predicted": float(predicted_mean.iloc[i]),
            "ci_lower_80": float(forecast_result.conf_int(alpha=0.20).iloc[i, 0]),
            "ci_upper_80": float(forecast_result.conf_int(alpha=0.20).iloc[i, 1]),
            "ci_lower_95": float(forecast_result.conf_int(alpha=0.05).iloc[i, 0]),
            "ci_upper_95": float(forecast_result.conf_int(alpha=0.05).iloc[i, 1]),
            "step": i + 1,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    logger.info(
        "Forecast generated: %d days from %s to %s. Range: [%.4f, %.4f]",
        forecast_days,
        df["date"].min().date(),
        df["date"].max().date(),
        df["predicted"].min(),
        df["predicted"].max(),
    )
    return df


# ─────────────────────────────────────────────────────────────
# 4. SAVE FORECAST TO DATABASE
# ─────────────────────────────────────────────────────────────

def save_forecast_to_db(
    forecast_df: pd.DataFrame,
    fitted_model,
    metrics: Optional[Dict] = None,
) -> "Forecast":
    """
    Persist a forecast run and its data points to MySQL.

    Args:
        forecast_df:    DataFrame from generate_forecast()
        fitted_model:   Fitted ARIMAResults
        metrics:        Optional validation metrics dict

    Returns:
        Forecast instance
    """
    from exchange_monitor.models import Forecast, ForecastPoint

    # Deactivate previous forecasts
    Forecast.objects.filter(is_active=True).update(is_active=False)

    order = fitted_model.model.order
    forecast_obj = Forecast.objects.create(
        forecast_from=forecast_df["date"].min().date(),
        forecast_to=forecast_df["date"].max().date(),
        model_order=f"({order[0]},{order[1]},{order[2]})",
        aic_score=fitted_model.aic,
        bic_score=fitted_model.bic,
        train_observations=len(fitted_model.model.endog),
        mae=metrics.get("mae") if metrics else None,
        rmse=metrics.get("rmse") if metrics else None,
        mape=metrics.get("mape") if metrics else None,
        coverage_80=metrics.get("coverage_80") if metrics else None,
        coverage_95=metrics.get("coverage_95") if metrics else None,
        status="success",
        is_active=True,
    )

    points = [
        ForecastPoint(
            forecast=forecast_obj,
            date=row["date"].date(),
            predicted_value=round(row["predicted"], 4),
            ci_lower_80=round(row["ci_lower_80"], 4),
            ci_upper_80=round(row["ci_upper_80"], 4),
            ci_lower_95=round(row["ci_lower_95"], 4),
            ci_upper_95=round(row["ci_upper_95"], 4),
            step_ahead=row["step"],
        )
        for _, row in forecast_df.iterrows()
    ]
    ForecastPoint.objects.bulk_create(points)

    logger.info("Forecast #%d saved with %d points.", forecast_obj.id, len(points))
    return forecast_obj


# ─────────────────────────────────────────────────────────────
# 5. FORECAST PLOT
# ─────────────────────────────────────────────────────────────

def plot_forecast(
    historical: pd.Series,
    forecast_df: pd.DataFrame,
    lookback_days: int = 90,
    title: str = "Pronóstico ARIMA — Tipo de Cambio Paralelo BOB/USD",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Plot historical data + ARIMA forecast with shaded CI bands.

    Args:
        historical:     Full historical series
        forecast_df:    DataFrame from generate_forecast()
        lookback_days:  How many historical days to show in chart
        title:          Chart title
        save_path:      File path to save
        show:           Show interactive plot

    Returns:
        matplotlib Figure
    """
    recent = historical.last(f"{lookback_days}D")
    fig, ax = plt.subplots(figsize=(14, 6))

    # Historical line
    ax.plot(recent.index, recent.values, color="#1f77b4", linewidth=2,
            label="Histórico real", zorder=3)

    # Forecast line
    ax.plot(forecast_df["date"], forecast_df["predicted"],
            color="#d62728", linewidth=2, linestyle="--",
            marker="o", markersize=4, label="Pronóstico ARIMA", zorder=4)

    # 95% CI band
    ax.fill_between(
        forecast_df["date"],
        forecast_df["ci_lower_95"], forecast_df["ci_upper_95"],
        alpha=0.15, color="#d62728", label="IC 95%",
    )
    # 80% CI band
    ax.fill_between(
        forecast_df["date"],
        forecast_df["ci_lower_80"], forecast_df["ci_upper_80"],
        alpha=0.30, color="#d62728", label="IC 80%",
    )

    # Separator line
    split_date = forecast_df["date"].min()
    ax.axvline(x=split_date, color="gray", linestyle=":", linewidth=1.5, alpha=0.7)
    ax.text(split_date, ax.get_ylim()[0], " hoy", fontsize=8, color="gray", va="bottom")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Fecha")
    ax.set_ylabel("BOB / USD")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=30)
    ax.legend(loc="upper left")
    ax.grid(alpha=0.25)

    # Annotation: last actual + first forecast
    last_actual = recent.iloc[-1]
    first_forecast = forecast_df.iloc[0]["predicted"]
    change = first_forecast - last_actual
    change_pct = (change / last_actual) * 100
    ax.annotate(
        f"Actual: {last_actual:.2f}\n→ Pronóstico D+1: {first_forecast:.2f} ({change_pct:+.2f}%)",
        xy=(forecast_df["date"].iloc[0], first_forecast),
        xytext=(30, 20), textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color="gray"),
        fontsize=9, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8),
    )

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
        logger.info("Forecast plot saved to %s", save_path)
    if show:
        plt.show()

    return fig


# ─────────────────────────────────────────────────────────────
# 6. WALK-FORWARD VALIDATION
# ─────────────────────────────────────────────────────────────

def walk_forward_validation(
    series: pd.Series,
    p: int,
    d: int,
    q: int,
    train_ratio: float = 0.80,
    step_size: int = 1,
    verbose: bool = True,
) -> Dict:
    """
    Walk-forward (expanding window) cross-validation.

    Strategy:
      1. Train on first `train_ratio` of data
      2. Predict next `step_size` steps
      3. Expand window by 1 and repeat
      4. Compare predictions to actuals

    Args:
        series:      Full time series
        p, d, q:     ARIMA order
        train_ratio: Fraction of data for initial training window
        step_size:   Steps ahead per prediction
        verbose:     Print progress

    Returns:
        dict with mae, rmse, mape, coverage_80, coverage_95, predictions_df
    """
    n = len(series)
    train_size = int(n * train_ratio)
    actuals, predictions = [], []
    ci_80_lower, ci_80_upper = [], []
    ci_95_lower, ci_95_upper = [], []

    if verbose:
        print(f"\nWalk-forward validation: ARIMA({p},{d},{q})")
        print(f"Train window: {train_size} obs ({train_ratio*100:.0f}%)")
        print(f"Test window:  {n - train_size} obs")

    for i in range(train_size, n, step_size):
        train = series.iloc[:i]
        try:
            model = ARIMA(train, order=(p, d, q))
            fitted = model.fit()
            fc = fitted.get_forecast(steps=step_size)
            pred = float(fc.predicted_mean.iloc[-1])
            ci_80 = fc.conf_int(alpha=0.20)
            ci_95 = fc.conf_int(alpha=0.05)

            actual = float(series.iloc[min(i, n - 1)])
            actuals.append(actual)
            predictions.append(pred)
            ci_80_lower.append(float(ci_80.iloc[-1, 0]))
            ci_80_upper.append(float(ci_80.iloc[-1, 1]))
            ci_95_lower.append(float(ci_95.iloc[-1, 0]))
            ci_95_upper.append(float(ci_95.iloc[-1, 1]))
        except Exception as exc:
            logger.warning("Walk-forward step %d failed: %s", i, exc)
            continue

        if verbose and i % 50 == 0:
            print(f"  Step {i}/{n} ...", end="\r")

    actuals_arr = np.array(actuals)
    preds_arr = np.array(predictions)

    mae = float(np.mean(np.abs(actuals_arr - preds_arr)))
    rmse = float(np.sqrt(np.mean((actuals_arr - preds_arr) ** 2)))
    mape = float(np.mean(np.abs((actuals_arr - preds_arr) / actuals_arr)) * 100)

    ci_80_arr_l = np.array(ci_80_lower)
    ci_80_arr_u = np.array(ci_80_upper)
    ci_95_arr_l = np.array(ci_95_lower)
    ci_95_arr_u = np.array(ci_95_upper)

    coverage_80 = float(np.mean((actuals_arr >= ci_80_arr_l) & (actuals_arr <= ci_80_arr_u)) * 100)
    coverage_95 = float(np.mean((actuals_arr >= ci_95_arr_l) & (actuals_arr <= ci_95_arr_u)) * 100)

    predictions_df = pd.DataFrame({
        "date": series.index[train_size:train_size + len(actuals)],
        "actual": actuals,
        "predicted": predictions,
        "ci_lower_80": ci_80_lower,
        "ci_upper_80": ci_80_upper,
        "ci_lower_95": ci_95_lower,
        "ci_upper_95": ci_95_upper,
        "error": actuals_arr - preds_arr,
    })

    metrics = {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 4),
        "coverage_80": round(coverage_80, 2),
        "coverage_95": round(coverage_95, 2),
        "n_test": len(actuals),
        "predictions_df": predictions_df,
    }

    if verbose:
        print(f"\n{'='*45}")
        print(f"  Validation Metrics — ARIMA({p},{d},{q})")
        print(f"{'='*45}")
        print(f"  MAE    : {mae:.4f} BOB")
        print(f"  RMSE   : {rmse:.4f} BOB")
        print(f"  MAPE   : {mape:.2f}%")
        print(f"  IC 80% coverage: {coverage_80:.1f}% (target ≥ 80%)")
        print(f"  IC 95% coverage: {coverage_95:.1f}% (target ≥ 95%)")
        print(f"{'='*45}\n")

    return metrics


# ─────────────────────────────────────────────────────────────
# 7. METRICS TEXT REPORT
# ─────────────────────────────────────────────────────────────

def generate_metrics_report(metrics: Dict, model_order: Tuple[int, int, int]) -> str:
    """
    Generate a formatted text report of model validation metrics.

    Args:
        metrics:     Output from walk_forward_validation()
        model_order: (p, d, q) tuple

    Returns:
        Multi-line string report
    """
    p, d, q = model_order
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 60,
        "  EXCHANGE RATE ALERT SYSTEM — Kapitalya",
        "  ARIMA Model Validation Report",
        "=" * 60,
        f"  Generated at : {timestamp}",
        f"  Model        : ARIMA({p},{d},{q})",
        f"  Test samples : {metrics.get('n_test', 'N/A')}",
        "-" * 60,
        "  ACCURACY METRICS",
        "-" * 60,
        f"  MAE  (Mean Absolute Error)       : {metrics['mae']:.4f} BOB",
        f"  RMSE (Root Mean Square Error)    : {metrics['rmse']:.4f} BOB",
        f"  MAPE (Mean Abs % Error)          : {metrics['mape']:.2f}%",
        "-" * 60,
        "  CONFIDENCE INTERVAL COVERAGE",
        "-" * 60,
        f"  80% CI coverage : {metrics['coverage_80']:.1f}%  (theoretical target: 80.0%)",
        f"  95% CI coverage : {metrics['coverage_95']:.1f}%  (theoretical target: 95.0%)",
        "-" * 60,
        "  INTERPRETATION",
        "-" * 60,
    ]

    # Auto-interpretation
    mape = metrics["mape"]
    if mape < 2:
        lines.append(f"  ✅ Excellent accuracy — MAPE < 2% is outstanding for this market.")
    elif mape < 5:
        lines.append(f"  ✅ Good accuracy — MAPE {mape:.1f}% is acceptable for forecasting.")
    elif mape < 10:
        lines.append(f"  ⚠️  Moderate accuracy — MAPE {mape:.1f}% may indicate structural breaks.")
    else:
        lines.append(f"  ❌ Poor accuracy — MAPE {mape:.1f}% suggests model re-specification needed.")

    cov = metrics["coverage_95"]
    if abs(cov - 95.0) <= 5:
        lines.append(f"  ✅ CI coverage well-calibrated ({cov:.1f}%).")
    elif cov < 90:
        lines.append(f"  ⚠️  CI under-coverage ({cov:.1f}%) — prediction bands may be too narrow.")
    else:
        lines.append(f"  ⚠️  CI over-coverage ({cov:.1f}%) — bands may be too conservative.")

    lines.append("=" * 60)
    return "\n".join(lines)
