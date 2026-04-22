"""
api/views.py  +  api/urls.py
──────────────────────────────
REST API endpoints for the Exchange Rate Alert System.

Endpoints:
  GET  /api/rates/           — Last 30 days of exchange rates
  GET  /api/rates/<id>/      — Single rate detail
  GET  /api/forecast/        — Current active forecast with points
  GET  /api/alerts/          — User's active alert configurations
  POST /api/alerts/          — Create new alert configuration
  GET  /api/alerts/triggered/— Recent triggered alerts
  GET  /api/status/          — System health status
"""

from datetime import date, timedelta

from django.db.models import Avg, Max, Min, StdDev
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.serializers import (
    ExchangeRateSerializer, ForecastSerializer,
    AlertConfigurationSerializer, TriggeredAlertSerializer,
)
from exchange_monitor.models import (
    ExchangeRate, Forecast, AlertConfiguration, TriggeredAlert, ARIMAModelConfig,
)


# ─────────────────────────────────────────────────────────────
# GET /api/rates/
# ─────────────────────────────────────────────────────────────

class ExchangeRateListView(generics.ListAPIView):
    """
    Returns the most recent N days of exchange rate data.
    Query params: ?days=30 (default), ?days=90, etc.
    """
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        days = int(self.request.query_params.get("days", 30))
        days = min(days, 730)  # Cap at 2 years
        cutoff = date.today() - timedelta(days=days)
        return ExchangeRate.objects.filter(date__gte=cutoff).order_by("-date")


class ExchangeRateDetailView(generics.RetrieveAPIView):
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]
    queryset = ExchangeRate.objects.all()


# ─────────────────────────────────────────────────────────────
# GET /api/forecast/
# ─────────────────────────────────────────────────────────────

class ForecastView(generics.RetrieveAPIView):
    """Returns the current active ARIMA forecast with all data points."""
    serializer_class = ForecastSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        forecast = Forecast.objects.filter(is_active=True, status="success").first()
        if not forecast:
            from rest_framework.exceptions import NotFound
            raise NotFound("No active forecast available.")
        return forecast


# ─────────────────────────────────────────────────────────────
# GET + POST /api/alerts/
# ─────────────────────────────────────────────────────────────

class AlertConfigListCreateView(generics.ListCreateAPIView):
    """
    GET  — List user's alert configurations
    POST — Create new alert configuration

    POST body example:
    {
        "name": "Umbral crítico 10 BOB",
        "alert_type": "absolute_threshold",
        "threshold_value": "10.0000",
        "lookback_days": 7,
        "severity": "red",
        "notify_email": true,
        "email_recipients": "usuario@empresa.com"
    }
    """
    serializer_class = AlertConfigurationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AlertConfiguration.objects.filter(user=self.request.user).order_by("-created_at")


# ─────────────────────────────────────────────────────────────
# GET /api/alerts/triggered/
# ─────────────────────────────────────────────────────────────

class TriggeredAlertListView(generics.ListAPIView):
    """Returns the user's most recent triggered alerts."""
    serializer_class = TriggeredAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        days = int(self.request.query_params.get("days", 30))
        cutoff = date.today() - timedelta(days=days)
        return TriggeredAlert.objects.filter(
            configuration__user=self.request.user,
            triggered_at__date__gte=cutoff,
        ).order_by("-triggered_at")


# ─────────────────────────────────────────────────────────────
# GET /api/status/
# ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_status_view(request):
    """
    System health endpoint. Returns current data freshness,
    model status, and alert counts.
    """
    latest_rate = ExchangeRate.objects.order_by("-date").first()
    latest_forecast = Forecast.objects.filter(is_active=True, status="success").first()
    arima_config = ARIMAModelConfig.objects.filter(is_current=True).first()

    today = date.today()
    data_fresh = latest_rate and latest_rate.date >= today - timedelta(days=1)

    return Response({
        "status": "healthy" if data_fresh else "stale_data",
        "data": {
            "latest_rate_date": str(latest_rate.date) if latest_rate else None,
            "latest_rate_value": float(latest_rate.rate_parallel) if latest_rate else None,
            "data_is_fresh": data_fresh,
        },
        "model": {
            "arima_order": str(arima_config) if arima_config else "Not configured",
            "forecast_available": latest_forecast is not None,
            "forecast_to": str(latest_forecast.forecast_to) if latest_forecast else None,
            "last_mae": latest_forecast.mae if latest_forecast else None,
        },
        "alerts": {
            "active_configurations": AlertConfiguration.objects.filter(
                user=request.user, is_active=True
            ).count(),
            "triggered_last_7_days": TriggeredAlert.objects.filter(
                configuration__user=request.user,
                triggered_at__date__gte=today - timedelta(days=7),
            ).count(),
        },
        "timestamp": today.isoformat(),
    })
