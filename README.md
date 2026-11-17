# Alerta de Tasas — Exchange Rate Alert System (USD paralelo Bolivia)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2-092E20?logo=django&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)
![statsmodels](https://img.shields.io/badge/statsmodels-0.14-FF6F00)
![Plotly](https://img.shields.io/badge/Plotly-5.22-3F4F75?logo=plotly&logoColor=white)
![License](https://img.shields.io/badge/License-sin%20LICENSE-lightgrey)
![Status](https://img.shields.io/badge/Status-PARCIAL-orange)

> Automated monitoring, forecasting, and alerting system for the Bolivian parallel USD/BOB exchange rate.  
> Built for **Kapitalya**. Un README anterior declaraba "Production" y "uso diario desde 2023"; el repo no lo respalda (ver Estado).

**Estado (2026-11-17):** PARCIAL — faltan `exchange_monitor/views.py` (que `exchange_monitor/urls.py` importa), migraciones (solo `__init__.py`), templates `historical.html`, `alerts.html` y `settings.html`, tests (solo `__init__.py` vacíos), `.env.example` y CI. Los datos de ejemplo son sintéticos. Sin verificar (requiere observación de producción): si corre en algún host.
**Repo:** kapitalya/exchange-rate-alert-bolivia · **Rama por defecto:** main · **Alias/nombres anteriores:** "Exchange Rate Alert System" (README previo), "Alerta de Tasas" / "exchange-alert" (tromay), `alertas.kapitalya.com.bo` (dominio citado antes por tromay; según el comentario de `LeadController` en tromay está dado de baja y hoy redirige a Paralelo)

---

## The Business Problem

Bolivia operates under a **dual exchange rate system**:

| Market | Rate (approx.) | Operator |
|--------|---------------|----------|
| Official (BCB) | BOB 6.96/USD | Central Bank of Bolivia |
| Parallel (black market) | BOB 7.00–13.50/USD | Informal traders |

The official rate has been pegged since 2011, but a severe **dollar shortage** since late 2022 has caused the parallel rate to diverge dramatically — at times reaching **2× the official rate**.

For businesses like Kapitalya that operate in both markets, **a 0.50 BOB move in a single day can represent hundreds of thousands of bolivianos in exposure**. Manual monitoring is inadequate. This system provides:

- 📊 **Historical database** of parallel rates since April 2023
- 🔮 **ARIMA-based 14-day forecasts** with 80% and 95% confidence intervals
- 🚨 **Automated multi-type alerts** triggered by threshold breaches, volatility spikes, and unusual spreads
- 📱 **Email + WhatsApp notifications** delivered automatically every business day

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    EXCHANGE RATE ALERT SYSTEM                       │
│                         Kapitalya                                   │
└─────────────────────────────────────────────────────────────────────┘

  DATA SOURCES          STORAGE           PROCESSING          OUTPUT
  ┌──────────┐      ┌──────────────┐   ┌────────────────┐  ┌──────────────────┐
  │ Manual   │─────►│ MySQL 8.0    │──►│ ARIMA Module   │─►│ Django Dashboard │
  │ Entry    │      │              │   │                │  │ (Plotly charts)  │
  └──────────┘      │  Tables:     │   │ 1. EDA         │  └──────────────────┘
                    │  ─ exchange  │   │ 2. Grid Search │
  ┌──────────┐      │    _rates    │   │ 3. Train       │  ┌──────────────────┐
  │ API      │─────►│  ─ forecasts │   │ 4. Forecast    │─►│ REST API         │
  │ Scraper  │      │  ─ forecast  │   │ 5. Validate    │  │ (DRF)            │
  └──────────┘      │    _points   │   └───────┬────────┘  └──────────────────┘
                    │  ─ alert     │           │
                    │    _configs  │           ▼
                    │  ─ triggered │   ┌────────────────┐  ┌──────────────────┐
                    │    _alerts   │   │ Alert Engine   │─►│ Email (SMTP)     │
                    │  ─ arima     │   │                │  │ WhatsApp (Twilio)│
                    │    _configs  │   │ Type 1: Thresh │  └──────────────────┘
                    │  ─ notif     │   │ Type 2: % Change│
                    │    _logs     │   │ Type 3: Volatil│  ┌──────────────────┐
                    └──────────────┘   │ Type 4: Spread │─►│ APScheduler      │
                                       └────────────────┘  │ (auto daily run) │
                                                           └──────────────────┘
```

---

Nota: en el diagrama, "API Scraper" figura como fuente pero no hay scraper en el código; hoy los datos entran por carga manual o por `scripts/generate_synthetic_data.py`.

---

## ARIMA Methodology

### Why ARIMA?

| Model | Pros | Cons | Verdict |
|-------|------|------|---------|
| **ARIMA** | Interpretable, fast, statistically rigorous | Assumes linearity | ✅ Best for this use case |
| Prophet | Handles seasonality | Overkill for daily data with no strong seasonality | ❌ |
| LSTM | Captures non-linearity | Requires much more data, black-box | ❌ |

The Bolivian parallel market shows **strong autoregressive behavior** (today's rate is highly correlated with yesterday's) and **mild trend components**, which is the ideal ARIMA use case.

### Why statsmodels over pmdarima?

- `statsmodels` is a mature, auditable library with published statistical tests
- `pmdarima.auto_arima` is a wrapper — we implement our own grid search for full control over the AIC selection process and logging
- More transparent for presenting in technical interviews

### Parameter Selection

```
Grid Search: p ∈ {0,1,2,3} × d ∈ {0,1,2} × q ∈ {0,1,2,3}
= 48 combinations evaluated

Selection Criterion: AIC (Akaike Information Criterion)
  AIC = 2k - 2ln(L)
  where k = number of parameters, L = maximum likelihood

Why AIC over BIC? AIC favours richer models, which improves
forecast accuracy (vs BIC, which is better for inference).

Integration order d: Determined by Augmented Dickey-Fuller test
  H₀: Unit root exists (non-stationary) → d ≥ 1
  H₁: Stationary → d = 0
```

---

## The Four Alert Types

| # | Type | Trigger | Severity | Use Case |
|---|------|---------|----------|----------|
| 1 | **Absolute Threshold** | Forecast > X BOB/USD | 🟡🔴 | "Alert me if rate exceeds 12.00" |
| 2 | **% Change** | Forecast change > X% in 7 days | 🟡🔴 | "Alert me if rate moves >5% this week" |
| 3 | **High Volatility** | Recent σ > 2× historical 90d σ | 🔴 | Detect market stress before it peaks |
| 4 | **Unusual Spread** | Spread > historical 90th percentile | 🔴 | Early warning of dollar shortage intensification |

---

## Model Performance (Synthetic Data Baseline)

Estas métricas se midieron sobre datos sintéticos, no sobre datos de producción.

Validated using **walk-forward cross-validation** on 80/20 train/test split:

| Metric | Value | Interpretation |
|--------|-------|---------------|
| MAE | ~0.04 BOB | Mean error < 4 centavos |
| RMSE | ~0.06 BOB | Low variance in errors |
| MAPE | ~0.45% | < 1% error is excellent |
| IC 80% Coverage | ~80.2% | Well-calibrated |
| IC 95% Coverage | ~95.1% | Well-calibrated |

---

## Project Structure

```
exchange-rate-alert-bolivia/
│
├── config/                    # Django project settings
│   ├── settings.py            # All configuration (env-based)
│   ├── urls.py                # Root URL routing
│   └── wsgi.py
│
├── exchange_monitor/          # Core Django app
│   ├── models.py              # 7 database models
│   ├── views.py               # NO EXISTE en el repo (urls.py hace `from exchange_monitor import views`)
│   ├── urls.py
│   └── migrations/            # solo __init__.py (sin migraciones)
│
├── arima/                     # Time-series analysis module
│   ├── analysis.py            # EDA: ADF test, ACF/PACF, stationarity
│   └── forecaster.py         # Grid search, training, forecast, validation
│
├── alerts/                    # Alert engine
│   ├── engine.py              # 4 alert evaluators + main runner
│   ├── notifications.py       # Email (HTML) + WhatsApp (Twilio)
│   └── scheduler.py          # APScheduler jobs (daily/weekly)
│
├── api/                       # REST API
│   ├── serializers.py
│   ├── views.py               # 6 endpoints
│   └── urls.py
│
├── templates/                 # Bootstrap 5 templates
│   ├── base.html              # Sidebar layout
│   ├── registration/login.html
│   └── exchange_monitor/
│       ├── dashboard.html
│       └── forecast.html      # (historical.html, alerts.html y settings.html NO existen)
│
├── scripts/
│   ├── create_schema.sql      # MySQL DDL
│   └── generate_synthetic_data.py  # Realistic test data generator
│
├── tests/
│   ├── unit/                  # solo __init__.py (0 tests)
│   └── integration/           # solo __init__.py (0 tests)
│
├── docs/BUILD_PLAN.md         # plan de construcción de 8 días
├── requirements.txt           # Pinned dependencies
└── README.md
```

---

## Installation (Windows)

### Prerequisites
- Python 3.10+
- MySQL 8.0+
- Git

### Step-by-Step

```bash
# 1. Clone the repository
git clone https://github.com/kapitalya/exchange-rate-alert-bolivia.git
cd exchange-rate-alert-bolivia

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
# No existe .env.example en el repo: crea .env con las variables listadas en "Variables de entorno (solo nombres)"

# 5. Create MySQL database
mysql -u root -p < scripts/create_schema.sql

# 6. Migraciones: el repo no trae migraciones (solo __init__.py); generar con makemigrations antes de migrate
python manage.py makemigrations exchange_monitor
python manage.py migrate

# 7. Create superuser
python manage.py createsuperuser

# 8. Load synthetic historical data
python scripts/generate_synthetic_data.py

# 9. Start development server
python manage.py runserver

# 10. Visit http://localhost:8000
```

---

## Running Your First Forecast

```bash
# Open Django shell
python manage.py shell

# Run grid search + forecast
from arima.analysis import load_rates
from arima.forecaster import grid_search_arima, train_arima, generate_forecast, save_forecast_to_db, walk_forward_validation

series = load_rates()
gs = grid_search_arima(series, max_p=3, max_d=2, max_q=3)
p, d, q = gs['best_p'], gs['best_d'], gs['best_q']
metrics = walk_forward_validation(series, p, d, q)
fitted = train_arima(series, p, d, q)
forecast_df = generate_forecast(fitted, forecast_days=14)
save_forecast_to_db(forecast_df, fitted, metrics)
print("Forecast saved. Visit /forecast/ in the dashboard.")
```

---

## Configuring Alerts

### Via Web Interface
1. Navigate to **Configuración** in the sidebar
2. Click **Nueva Alerta**
3. Choose alert type, set threshold, add email recipients

### Via REST API
```bash
curl -X POST http://localhost:8000/api/alerts/ \
  -H "Content-Type: application/json" \
  -u admin:password \
  -d '{
    "name": "Umbral crítico 12 BOB",
    "alert_type": "absolute_threshold",
    "threshold_value": "12.0000",
    "severity": "red",
    "notify_email": true,
    "email_recipients": "analista@example.com"
  }'
```

---

## API Documentation

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rates/` | Last 30 days of exchange rates (`?days=N`) |
| GET | `/api/rates/<id>/` | Single rate detail |
| GET | `/api/forecast/` | Active forecast with 14-day points and CI bands |
| GET | `/api/alerts/` | User's alert configurations |
| POST | `/api/alerts/` | Create new alert |
| GET | `/api/alerts/triggered/` | Recent triggered alerts |
| GET | `/api/status/` | System health check |

All endpoints require authentication. Browse the API at `/api/` (Django REST Framework UI).

---

## Bolivian Economic Context

This project is unique because:

1. **The BOB has been officially pegged at 6.96 since 2011** — the parallel market is the *real* price signal
2. **Bolivia's dollar shortage** (2022–present) has caused the largest spread since the 1980s hyperinflation
3. **No public API exists** for the parallel rate — data collection is manual and proprietary
4. **Financial decisions** (imports, pricing, treasury management) depend on accurate parallel rate forecasting

This makes the problem technically interesting: a relatively short, non-seasonal daily series with structural breaks (policy announcements, elections, fuel crisis) — exactly the regime where ARIMA with careful parameter selection outperforms automated tools like Prophet.

---

## Privacy Note

The historical exchange rate data in this repository is **synthetically generated** to preserve the confidentiality of Kapitalya's proprietary market data. The synthetic series was calibrated to match the real statistical properties (volatility regimes, trend structure, spread behaviour) observed in production.

La afirmación previa de que la implementación es idéntica al sistema de producción no se puede comprobar desde este repo: no contiene configuración ni despliegue de producción (sin verificar, requiere observación de producción).

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend | Django | 4.2.11 |
| REST API | Django REST Framework | 3.15.1 |
| Database | MySQL | 8.0 |
| Time Series | statsmodels (ARIMA) | 0.14.2 |
| Data Processing | pandas, numpy | 2.2.2, 1.26.4 |
| Charts | Plotly | 5.22.0 |
| Scheduling | APScheduler | 3.10.4 |
| Notifications | Django Mail + Twilio | — |
| Frontend | Bootstrap 5 + Bootstrap Icons | 5.3.2 |

---

## License

El README anterior declaraba licencia MIT, pero el repo no contiene archivo LICENSE. Hasta que el dueño defina la licencia, el código es de uso interno de Kapitalya, sin licencia de reutilización para terceros.

---

*Kapitalya — La Paz, Bolivia*

---

## Qué hace
App Django (MySQL) para monitorear el USD paralelo/BOB: modelos de tasas, pronósticos y alertas; pronóstico ARIMA con grid search (statsmodels); motor de 4 tipos de alerta; notificaciones por email y WhatsApp (Twilio); scheduler APScheduler; API REST (DRF) y dashboard Plotly. Lo anterior describe el código existente; la capa de vistas web está incompleta (ver Estado).

## Variables de entorno (solo nombres)
No hay `.env.example`; los nombres salen de `config/settings.py`: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `ARIMA_FORECAST_DAYS`, `ARIMA_MAX_P`, `ARIMA_MAX_D`, `ARIMA_MAX_Q`, `ARIMA_MIN_OBS`, `ARIMA_TRAIN_RATIO`.

## Pruebas y CI
`requirements.txt` fija `pytest` 8.2.0 y `pytest-django` 4.8.0, pero `tests/unit` y `tests/integration` solo contienen `__init__.py`: 0 tests. No hay workflows de CI.

## Despliegue
No hay Dockerfile ni workflow de deploy en el repo (árbol). Sin verificar (requiere observación de producción): si hay una instancia desplegada. Dev: `python manage.py runserver` en `http://localhost:8000`, MySQL 3306.

## Estado y relaciones
- **tromay:** `tromay/README.md` afirma que este repo consume su `/api/rates` y lo presenta como "Alerta de Tasas" (`alertas.kapitalya.com.bo`). Verificado en el código: ningún archivo de texto del repo (`.py`, `.html`, `.sql`, `.md`, `requirements.txt`) referencia tromay ni forex-erp; solo sirve su propio `/api/rates/`. El consumo declarado por tromay no existe en este repo.
- **forex-erp (KapiFX):** sin dependencia de código. KapiFX tiene sus propios módulos `alerts`, `predictions` y `macro`: solape funcional con el ARIMA y las alertas de este repo.
- `exchange_monitor/urls.py` importa `views.DashboardView`, `HistoricalView`, `ForecastView`, `AlertsView`, `AlertSettingsView` y `ModelMetricsView`; ninguna existe porque falta `exchange_monitor/views.py`.
- `exchange_monitor/urls.py` importa `views.DashboardView`, `HistoricalView`, `ForecastView`, `AlertsView`, `AlertSettingsView` y `ModelMetricsView`; ninguna existe porque falta `exchange_monitor/views.py`.
- Plan de construcción de referencia: `docs/BUILD_PLAN.md`.

## Precios y planes
Precios y planes: fuente única `Vault/EMPRESA/portafolio/PRECIOS-APROBADOS-20261108.md`.

## Seguridad, privacidad y derechos
- Sin secretos en el repo; credenciales solo por entorno. Las notificaciones usan Twilio y SMTP: no versionar sus claves.
- Datos sintéticos; los datos reales de mercado de Kapitalya no están en el repo.
- Sin LICENSE (ver sección License).

## Convenciones de trabajo
Ramas `codex/*`, PR contra `main` (no existe `develop`), CI verde antes de integrar (hoy no hay CI: pendiente).
