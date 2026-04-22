"""
Models for Exchange Rate Alert System.

Tables:
  - ExchangeRate          : Historical daily BOB/USD parallel market rates
  - Forecast              : ARIMA-generated 14-day forecasts
  - ForecastPoint         : Individual forecast data points with confidence bands
  - AlertConfiguration    : User-defined alert rules
  - TriggeredAlert        : Log of every fired alert
  - ARIMAModelConfig      : Stored best ARIMA(p,d,q) parameters
  - NotificationLog       : Delivery log for email / WhatsApp notifications
"""

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# ─────────────────────────────────────────────────────────────
# 1. EXCHANGE RATE (historical raw data)
# ─────────────────────────────────────────────────────────────
class ExchangeRate(models.Model):
    """
    One row per trading day.  The 'parallel' market is the informal
    USD/BOB exchange rate widely used in Bolivia alongside the official rate.
    """

    date = models.DateField(unique=True, db_index=True, verbose_name="Fecha")
    rate_parallel = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="Tipo paralelo (BOB/USD)",
        help_text="Precio de compra/venta del dólar en el mercado paralelo (Bolivianos por USD).",
    )
    rate_official = models.DecimalField(
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        verbose_name="Tipo oficial (BOB/USD)",
        help_text="Tipo de cambio oficial BCB.",
    )
    spread = models.DecimalField(
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        verbose_name="Spread paralelo-oficial",
    )
    volume_indicator = models.SmallIntegerField(
        null=True, blank=True,
        verbose_name="Indicador de volumen (1-5)",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    source = models.CharField(
        max_length=120, default="manual_entry",
        verbose_name="Fuente",
        help_text="manual_entry | scraper | api_bcb",
    )
    notes = models.TextField(blank=True, verbose_name="Notas")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "exchange_rates"
        ordering = ["-date"]
        verbose_name = "Tipo de cambio"
        verbose_name_plural = "Tipos de cambio"
        indexes = [
            models.Index(fields=["date"], name="idx_er_date"),
            models.Index(fields=["rate_parallel"], name="idx_er_parallel"),
        ]

    def __str__(self):
        return f"{self.date} | BOB {self.rate_parallel}"

    def save(self, *args, **kwargs):
        """Auto-calculate spread when both rates are available."""
        if self.rate_parallel and self.rate_official:
            self.spread = self.rate_parallel - self.rate_official
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────
# 2. FORECAST RUN (metadata for each ARIMA execution)
# ─────────────────────────────────────────────────────────────
class Forecast(models.Model):
    """Header record for each forecast run."""

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("success", "Exitoso"),
        ("failed", "Fallido"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    forecast_from = models.DateField(verbose_name="Pronóstico desde")
    forecast_to = models.DateField(verbose_name="Pronóstico hasta")
    model_order = models.CharField(
        max_length=20,
        verbose_name="Orden ARIMA (p,d,q)",
        help_text="Ej: (2,1,2)",
    )
    aic_score = models.FloatField(null=True, blank=True, verbose_name="AIC")
    bic_score = models.FloatField(null=True, blank=True, verbose_name="BIC")
    train_observations = models.IntegerField(verbose_name="Observaciones de entrenamiento")
    mae = models.FloatField(null=True, blank=True, verbose_name="MAE (validación)")
    rmse = models.FloatField(null=True, blank=True, verbose_name="RMSE (validación)")
    mape = models.FloatField(null=True, blank=True, verbose_name="MAPE % (validación)")
    coverage_80 = models.FloatField(null=True, blank=True, verbose_name="Cobertura IC 80%")
    coverage_95 = models.FloatField(null=True, blank=True, verbose_name="Cobertura IC 95%")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Only the latest active forecast is used for alerts.",
    )

    class Meta:
        db_table = "forecasts"
        ordering = ["-created_at"]
        verbose_name = "Pronóstico"
        verbose_name_plural = "Pronósticos"

    def __str__(self):
        return f"Forecast {self.forecast_from} → {self.forecast_to} | ARIMA{self.model_order}"


# ─────────────────────────────────────────────────────────────
# 3. FORECAST POINT (one row per forecasted day)
# ─────────────────────────────────────────────────────────────
class ForecastPoint(models.Model):
    """Individual day-level forecast value with confidence intervals."""

    forecast = models.ForeignKey(
        Forecast, on_delete=models.CASCADE,
        related_name="points",
        db_index=True,
    )
    date = models.DateField(verbose_name="Fecha pronosticada", db_index=True)
    predicted_value = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="Valor pronosticado",
    )
    ci_lower_80 = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="IC 80% inferior",
    )
    ci_upper_80 = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="IC 80% superior",
    )
    ci_lower_95 = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="IC 95% inferior",
    )
    ci_upper_95 = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="IC 95% superior",
    )
    actual_value = models.DecimalField(
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        verbose_name="Valor real (post-hoc)",
        help_text="Filled in once the actual rate is known.",
    )
    step_ahead = models.SmallIntegerField(
        verbose_name="Días adelante",
        validators=[MinValueValidator(1), MaxValueValidator(30)],
    )

    class Meta:
        db_table = "forecast_points"
        ordering = ["forecast", "date"]
        unique_together = [("forecast", "date")]
        verbose_name = "Punto de pronóstico"
        verbose_name_plural = "Puntos de pronóstico"
        indexes = [
            models.Index(fields=["forecast", "date"], name="idx_fp_forecast_date"),
        ]

    def __str__(self):
        return f"{self.date} | Pred: {self.predicted_value} [{self.ci_lower_95}–{self.ci_upper_95}]"


# ─────────────────────────────────────────────────────────────
# 4. ALERT CONFIGURATION
# ─────────────────────────────────────────────────────────────
class AlertConfiguration(models.Model):
    """User-defined alert rules."""

    ALERT_TYPE_CHOICES = [
        ("absolute_threshold", "Umbral absoluto"),
        ("pct_change", "Variación porcentual"),
        ("high_volatility", "Volatilidad alta"),
        ("unusual_spread", "Spread inusual"),
    ]
    SEVERITY_CHOICES = [
        ("green", "Verde — Informativo"),
        ("yellow", "Amarillo — Precaución"),
        ("red", "Rojo — Crítico"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="alert_configurations",
    )
    name = models.CharField(max_length=200, verbose_name="Nombre de la alerta")
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    threshold_value = models.DecimalField(
        max_digits=10, decimal_places=4,
        null=True, blank=True,
        verbose_name="Valor umbral",
        help_text="BOB amount for absolute; percentage for pct_change; multiplier for volatility.",
    )
    lookback_days = models.SmallIntegerField(
        default=7, verbose_name="Ventana lookback (días)",
    )
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default="yellow",
    )
    is_active = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)
    email_recipients = models.TextField(
        blank=True,
        help_text="Comma-separated email addresses.",
    )
    whatsapp_recipients = models.TextField(
        blank=True,
        help_text="Comma-separated WhatsApp numbers with country code (e.g. +59162345678).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "alert_configurations"
        verbose_name = "Configuración de alerta"
        verbose_name_plural = "Configuraciones de alerta"

    def __str__(self):
        return f"[{self.get_alert_type_display()}] {self.name} ({self.user.username})"


# ─────────────────────────────────────────────────────────────
# 5. TRIGGERED ALERT (log of fired alerts)
# ─────────────────────────────────────────────────────────────
class TriggeredAlert(models.Model):
    """Immutable log entry created each time an alert fires."""

    configuration = models.ForeignKey(
        AlertConfiguration, on_delete=models.SET_NULL,
        null=True, related_name="triggered_alerts",
    )
    forecast = models.ForeignKey(
        Forecast, on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    triggered_at = models.DateTimeField(auto_now_add=True, db_index=True)
    current_rate = models.DecimalField(
        max_digits=8, decimal_places=4,
        verbose_name="Tipo de cambio al dispararse",
    )
    trigger_value = models.DecimalField(
        max_digits=10, decimal_places=4,
        verbose_name="Valor que disparó la alerta",
    )
    message_es = models.TextField(verbose_name="Mensaje (ES)")
    message_en = models.TextField(verbose_name="Mensaje (EN)")
    severity = models.CharField(max_length=10)
    notification_sent = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "triggered_alerts"
        ordering = ["-triggered_at"]
        verbose_name = "Alerta disparada"
        verbose_name_plural = "Alertas disparadas"
        indexes = [
            models.Index(fields=["triggered_at"], name="idx_ta_triggered_at"),
            models.Index(fields=["severity"], name="idx_ta_severity"),
        ]

    def __str__(self):
        return f"{self.triggered_at:%Y-%m-%d %H:%M} | {self.severity.upper()} | {self.message_es[:60]}"


# ─────────────────────────────────────────────────────────────
# 6. ARIMA MODEL CONFIGURATION (persisted best params)
# ─────────────────────────────────────────────────────────────
class ARIMAModelConfig(models.Model):
    """Stores the best ARIMA parameters found by grid search."""

    p = models.SmallIntegerField(verbose_name="AR order (p)")
    d = models.SmallIntegerField(verbose_name="Integration order (d)")
    q = models.SmallIntegerField(verbose_name="MA order (q)")
    aic = models.FloatField(verbose_name="AIC score")
    bic = models.FloatField(null=True, blank=True, verbose_name="BIC score")
    log_likelihood = models.FloatField(null=True, blank=True)
    is_current = models.BooleanField(
        default=True,
        help_text="Only one record should have is_current=True.",
    )
    selected_at = models.DateTimeField(auto_now_add=True)
    trained_on_observations = models.IntegerField()
    grid_search_duration_seconds = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "arima_model_configs"
        ordering = ["-selected_at"]
        verbose_name = "Configuración ARIMA"
        verbose_name_plural = "Configuraciones ARIMA"

    def __str__(self):
        return f"ARIMA({self.p},{self.d},{self.q}) | AIC={self.aic:.2f} | {'ACTIVO' if self.is_current else 'histórico'}"

    def save(self, *args, **kwargs):
        """Ensure only one config is marked current."""
        if self.is_current:
            ARIMAModelConfig.objects.filter(is_current=True).update(is_current=False)
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────
# 7. NOTIFICATION LOG
# ─────────────────────────────────────────────────────────────
class NotificationLog(models.Model):
    """Records every notification attempt (email or WhatsApp)."""

    CHANNEL_CHOICES = [("email", "Email"), ("whatsapp", "WhatsApp")]
    STATUS_CHOICES = [("sent", "Enviado"), ("failed", "Fallido"), ("pending", "Pendiente")]

    triggered_alert = models.ForeignKey(
        TriggeredAlert, on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    recipient = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "notification_logs"
        ordering = ["-sent_at"]
        verbose_name = "Log de notificación"
        verbose_name_plural = "Logs de notificación"

    def __str__(self):
        return f"{self.channel.upper()} → {self.recipient} | {self.status} | {self.sent_at}"
