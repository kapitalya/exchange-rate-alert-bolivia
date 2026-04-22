"""api/urls.py"""
from django.urls import path
from api import views

urlpatterns = [
    path("rates/", views.ExchangeRateListView.as_view(), name="api-rates-list"),
    path("rates/<int:pk>/", views.ExchangeRateDetailView.as_view(), name="api-rate-detail"),
    path("forecast/", views.ForecastView.as_view(), name="api-forecast"),
    path("alerts/", views.AlertConfigListCreateView.as_view(), name="api-alerts"),
    path("alerts/triggered/", views.TriggeredAlertListView.as_view(), name="api-triggered"),
    path("status/", views.system_status_view, name="api-status"),
]
