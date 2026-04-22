"""exchange_monitor/urls.py"""
from django.urls import path
from exchange_monitor import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("historical/", views.HistoricalView.as_view(), name="historical"),
    path("forecast/", views.ForecastView.as_view(), name="forecast"),
    path("alerts/", views.AlertsView.as_view(), name="alerts"),
    path("settings/", views.AlertSettingsView.as_view(), name="alert-settings"),
    path("metrics/", views.ModelMetricsView.as_view(), name="model-metrics"),
]
