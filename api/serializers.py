"""
api/serializers.py
───────────────────
Django REST Framework serializers for the Exchange Rate API.
"""

from rest_framework import serializers
from exchange_monitor.models import (
    ExchangeRate, Forecast, ForecastPoint,
    AlertConfiguration, TriggeredAlert,
)


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ["id", "date", "rate_parallel", "rate_official", "spread",
                  "volume_indicator", "source", "notes", "created_at"]
        read_only_fields = ["id", "spread", "created_at"]


class ForecastPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = ForecastPoint
        fields = ["date", "predicted_value", "ci_lower_80", "ci_upper_80",
                  "ci_lower_95", "ci_upper_95", "step_ahead", "actual_value"]


class ForecastSerializer(serializers.ModelSerializer):
    points = ForecastPointSerializer(many=True, read_only=True)

    class Meta:
        model = Forecast
        fields = ["id", "created_at", "forecast_from", "forecast_to",
                  "model_order", "aic_score", "mae", "rmse", "mape",
                  "coverage_80", "coverage_95", "status", "is_active", "points"]


class AlertConfigurationSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = AlertConfiguration
        fields = ["id", "user", "name", "alert_type", "threshold_value",
                  "lookback_days", "severity", "is_active", "notify_email",
                  "notify_whatsapp", "email_recipients", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class TriggeredAlertSerializer(serializers.ModelSerializer):
    alert_type = serializers.CharField(
        source="configuration.alert_type", read_only=True, default=""
    )

    class Meta:
        model = TriggeredAlert
        fields = ["id", "triggered_at", "alert_type", "severity",
                  "current_rate", "trigger_value", "message_es", "message_en",
                  "notification_sent"]
