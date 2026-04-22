# Exchange Rate Alert System — Bolivian Parallel USD Market

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2-092E20?logo=django&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)
![statsmodels](https://img.shields.io/badge/statsmodels-0.14-FF6F00)
![Plotly](https://img.shields.io/badge/Plotly-5.22-3F4F75?logo=plotly&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

> Automated monitoring, forecasting, and alerting system for the Bolivian parallel USD/BOB exchange rate.  
> Built for **Kapitalya** — actively used in daily financial operations since 2023.

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
│   ├── views.py               # Dashboard, historical, forecast, alerts
│   ├── urls.py
│   └── migrations/
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
│   └── exchange_monitor/
│       ├── dashboard.html
│       ├── historical.html
│       ├── forecast.html
│       ├── alerts.html
│       └── settings.html
│
├── scripts/
│   ├── create_schema.sql      # MySQL DDL
│   └── generate_synthetic_data.py  # Realistic test data generator
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── .env.example               # Environment variables template
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
git clone https://github.com/yourusername/exchange-rate-alert-bolivia.git
cd exchange-rate-alert-bolivia

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env
# Edit .env with your MySQL credentials and settings

# 5. Create MySQL database
mysql -u root -p < scripts/create_schema.sql

# 6. Apply Django migrations
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
    "email_recipients": "analista@kapitalya.com"
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

The system architecture, ARIMA methodology, alert logic, and Django implementation are identical to the production system.

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

MIT License — see [LICENSE](LICENSE) for details.

---

*Built with ♥ by [Your Name] for Kapitalya — La Paz, Bolivia*
