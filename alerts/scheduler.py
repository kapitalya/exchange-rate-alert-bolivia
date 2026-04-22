"""
alerts/scheduler.py
────────────────────
APScheduler integration with Django.

Schedule:
  - Mon–Fri 09:00 La Paz time  : Evaluate alerts
  - Every Monday 09:30         : Re-run ARIMA grid search + forecast
  - Daily 08:45                : Data freshness check

Registration: Called from AppConfig.ready() in alerts/apps.py
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger("scheduler")


# ─────────────────────────────────────────────────────────────
# JOB DEFINITIONS
# ─────────────────────────────────────────────────────────────

def job_evaluate_alerts():
    """Run alert engine — every business day at 09:00."""
    logger.info("[SCHEDULER] Starting daily alert evaluation...")
    try:
        from alerts.engine import run_alert_engine
        results = run_alert_engine(verbose=True)
        logger.info("[SCHEDULER] Alert evaluation complete. %d alerts fired.", len(results))
    except Exception as exc:
        logger.error("[SCHEDULER] Alert evaluation FAILED: %s", exc, exc_info=True)


def job_run_forecast():
    """Re-train ARIMA and generate new 14-day forecast — every Monday."""
    logger.info("[SCHEDULER] Starting weekly ARIMA forecast run...")
    try:
        import django
        django.setup()

        from arima.analysis import load_rates, infer_d
        from arima.forecaster import (
            grid_search_arima, train_arima,
            generate_forecast, save_forecast_to_db,
            walk_forward_validation,
        )
        from django.conf import settings as cfg

        arima_cfg = cfg.ARIMA_CONFIG

        # Load data
        series = load_rates()
        if len(series) < arima_cfg["MIN_OBSERVATIONS"]:
            logger.warning("Insufficient data (%d obs < min %d). Skipping forecast.",
                           len(series), arima_cfg["MIN_OBSERVATIONS"])
            return

        # Grid search
        gs_result = grid_search_arima(
            series=series,
            max_p=arima_cfg["MAX_P"],
            max_d=arima_cfg["MAX_D"],
            max_q=arima_cfg["MAX_Q"],
            verbose=True,
            save_to_db=True,
        )
        p, d, q = gs_result["best_p"], gs_result["best_d"], gs_result["best_q"]

        # Validate
        metrics = walk_forward_validation(
            series, p, d, q,
            train_ratio=arima_cfg["TRAIN_RATIO"],
            verbose=True,
        )

        # Train on full data
        fitted = train_arima(series, p, d, q, verbose=False)

        # Generate forecast
        forecast_df = generate_forecast(fitted, forecast_days=arima_cfg["FORECAST_DAYS"])

        # Persist
        save_forecast_to_db(forecast_df, fitted, metrics)

        logger.info("[SCHEDULER] Forecast run complete. ARIMA(%d,%d,%d)", p, d, q)

    except Exception as exc:
        logger.error("[SCHEDULER] Forecast run FAILED: %s", exc, exc_info=True)


def job_data_freshness_check():
    """Check if exchange rate data was updated today — 08:45 daily."""
    from datetime import date as dt_date
    try:
        from exchange_monitor.models import ExchangeRate
        latest = ExchangeRate.objects.order_by("-date").first()
        if latest is None:
            logger.warning("[SCHEDULER] No exchange rate data in database!")
            return

        today = dt_date.today()
        if latest.date < today:
            logger.warning(
                "[SCHEDULER] Exchange rate data is stale! Latest: %s, Today: %s",
                latest.date, today,
            )
        else:
            logger.info("[SCHEDULER] Data freshness OK. Latest: %s", latest.date)
    except Exception as exc:
        logger.error("[SCHEDULER] Freshness check failed: %s", exc)


def delete_old_job_executions(max_age=604_800):
    """Delete APScheduler job records older than max_age seconds (default 7 days)."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


# ─────────────────────────────────────────────────────────────
# SCHEDULER SETUP
# ─────────────────────────────────────────────────────────────

def start_scheduler():
    """
    Initialise and start the APScheduler instance.

    Call this from alerts/apps.py → AlertsConfig.ready()
    to ensure it starts when Django boots.
    """
    scheduler = BackgroundScheduler(timezone="America/La_Paz")
    scheduler.add_jobstore(DjangoJobStore(), "default")

    # ── Daily alert evaluation (Mon–Fri at 09:00) ──────────
    scheduler.add_job(
        job_evaluate_alerts,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9", minute="0"),
        id="daily_alert_evaluation",
        name="Daily Alert Evaluation",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,  # Allow 1h late run
    )

    # ── Weekly forecast (every Monday at 09:30) ────────────
    scheduler.add_job(
        job_run_forecast,
        trigger=CronTrigger(day_of_week="mon", hour="9", minute="30"),
        id="weekly_arima_forecast",
        name="Weekly ARIMA Forecast",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    # ── Data freshness check (daily at 08:45) ──────────────
    scheduler.add_job(
        job_data_freshness_check,
        trigger=CronTrigger(day_of_week="mon-fri", hour="8", minute="45"),
        id="data_freshness_check",
        name="Data Freshness Check",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )

    # ── Maintenance: clean old job logs (Sunday midnight) ──
    scheduler.add_job(
        delete_old_job_executions,
        trigger=CronTrigger(day_of_week="sun", hour="0", minute="0"),
        id="delete_old_job_executions",
        name="Delete Old Job Executions",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("[SCHEDULER] APScheduler started with %d jobs.", len(scheduler.get_jobs()))
    return scheduler
