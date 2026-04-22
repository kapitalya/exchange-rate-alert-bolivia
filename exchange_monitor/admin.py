from django.contrib import admin
from exchange_monitor.models import (
    ExchangeRate, Forecast, ForecastPoint,
    AlertConfiguration, TriggeredAlert, ARIMAModelConfig, NotificationLog,
)

@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "rate_parallel", "rate_official", "spread", "source"]
    list_filter = ["source"]
    search_fields = ["date"]
    ordering = ["-date"]
    date_hierarchy = "date"

@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = ["created_at", "forecast_from", "forecast_to", "model_order", "aic_score", "status", "is_active"]
    list_filter = ["status", "is_active"]

@admin.register(ForecastPoint)
class ForecastPointAdmin(admin.ModelAdmin):
    list_display = ["forecast", "date", "predicted_value", "step_ahead"]
    list_filter = ["forecast"]

@admin.register(AlertConfiguration)
class AlertConfigAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "alert_type", "threshold_value", "severity", "is_active"]
    list_filter = ["alert_type", "severity", "is_active"]

@admin.register(TriggeredAlert)
class TriggeredAlertAdmin(admin.ModelAdmin):
    list_display = ["triggered_at", "severity", "current_rate", "notification_sent"]
    list_filter = ["severity", "notification_sent"]
    ordering = ["-triggered_at"]

@admin.register(ARIMAModelConfig)
class ARIMAModelConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "selected_at", "is_current"]
    list_filter = ["is_current"]

@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ["channel", "recipient", "status", "sent_at"]
    list_filter = ["channel", "status"]
