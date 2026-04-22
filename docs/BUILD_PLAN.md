# PLAN DE CONSTRUCCIÓN — 8 DÍAS
## Exchange Rate Alert System — exchange-rate-alert-bolivia

---

## DÍA 1 — Setup y Base de Datos (2 horas)

**Objetivo:** Proyecto Django corriendo con MySQL conectado.

```
Orden de archivos a crear:
1.  exchange-rate-alert-bolivia/           ← mkdir raíz
2.  venv/ (entorno virtual)                ← python -m venv venv
3.  requirements.txt                       ← ya existe en repo
4.  .env (copiar de .env.example)          ← editar credenciales
5.  config/__init__.py
6.  config/settings.py                     ← ya existe en repo
7.  config/urls.py                         ← ya existe en repo
8.  config/wsgi.py
9.  manage.py                              ← ya existe en repo
10. scripts/create_schema.sql              ← ejecutar en MySQL
```

**Comandos del día:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
mysql -u root -p -e "CREATE DATABASE exchange_rate_db CHARACTER SET utf8mb4;"
python manage.py check    # debe mostrar System check identified no issues
```

**Verificación:** `python manage.py check` sin errores.

---

## DÍA 2 — Datos Históricos y Modelos Django (2 horas)

**Objetivo:** Tablas en MySQL, ORM funcionando, datos sintéticos cargados.

```
Orden de archivos a crear:
1.  exchange_monitor/__init__.py
2.  exchange_monitor/apps.py
3.  exchange_monitor/models.py             ← ya existe en repo
4.  exchange_monitor/admin.py              ← registrar todos los modelos
5.  alerts/__init__.py
6.  alerts/apps.py
7.  api/__init__.py
8.  api/apps.py
9.  arima/__init__.py
```

**Comandos del día:**
```bash
python manage.py makemigrations exchange_monitor
python manage.py makemigrations alerts
python manage.py migrate
python manage.py createsuperuser
python scripts/generate_synthetic_data.py
python manage.py runserver
# Visitar http://localhost:8000/admin y verificar datos
```

**Verificación:** 750+ registros en tabla `exchange_rates` visibles en /admin.

---

## DÍA 3 — Módulo ARIMA: Análisis Exploratorio (2 horas)

**Objetivo:** EDA completo con tests estadísticos funcionando.

```
Orden de archivos a crear:
1.  arima/analysis.py                      ← ya existe en repo
```

**Comandos del día (en Django shell):**
```python
from arima.analysis import load_rates, run_adf_test, infer_d, plot_acf_pacf

series = load_rates()
print(f"Datos cargados: {len(series)} observaciones")

# Test ADF
result = run_adf_test(series)
# Esperado: NO estacionaria (p > 0.05)

# Inferir d
d = infer_d(series, max_d=2)
# Esperado: d=1 (primera diferencia)

# Graficar ACF/PACF de la serie diferenciada
from arima.analysis import difference_series
diff = difference_series(series, order=1)
run_adf_test(diff)  # Esperado: estacionaria ahora
plot_acf_pacf(diff, save_path="docs/acf_pacf.png")
```

**Verificación:** Test ADF rechaza H₀ después de d=1. Gráficos guardados.

---

## DÍA 4 — Entrenamiento y Pronóstico ARIMA (2 horas)

**Objetivo:** Grid search completo, modelo entrenado, pronóstico en base de datos.

```
Orden de archivos a crear:
1.  arima/forecaster.py                    ← ya existe en repo
```

**Comandos del día (en Django shell):**
```python
from arima.analysis import load_rates
from arima.forecaster import (
    grid_search_arima, train_arima,
    generate_forecast, save_forecast_to_db,
    walk_forward_validation, generate_metrics_report
)

series = load_rates()

# Grid search (puede tomar 3-5 minutos)
gs = grid_search_arima(series, max_p=3, max_d=2, max_q=3, verbose=True)
p, d, q = gs['best_p'], gs['best_d'], gs['best_q']

# Validación
metrics = walk_forward_validation(series, p, d, q)
print(generate_metrics_report(metrics, (p, d, q)))

# Entrenar y pronosticar
fitted = train_arima(series, p, d, q)
forecast_df = generate_forecast(fitted, forecast_days=14)
print(forecast_df)

# Guardar
save_forecast_to_db(forecast_df, fitted, metrics)
print("✅ Pronóstico guardado en base de datos")
```

**Verificación:** Tabla `forecasts` tiene 1 registro. Tabla `forecast_points` tiene 14 registros.

---

## DÍA 5 — Sistema de Alertas (2 horas)

**Objetivo:** Los 4 tipos de alerta funcionando con notificaciones.

```
Orden de archivos a crear:
1.  alerts/engine.py                       ← ya existe en repo
2.  alerts/notifications.py               ← ya existe en repo
3.  alerts/scheduler.py                   ← ya existe en repo
4.  alerts/apps.py                        ← registrar scheduler en ready()
```

**Comandos del día (en Django shell):**
```python
# Crear alerta de prueba en admin o shell
from django.contrib.auth.models import User
from exchange_monitor.models import AlertConfiguration

user = User.objects.first()
AlertConfiguration.objects.create(
    user=user,
    name="Test umbral 8 BOB",
    alert_type="absolute_threshold",
    threshold_value=8.0,
    severity="yellow",
    notify_email=False,  # False para no enviar email en test
)

# Probar el engine
from alerts.engine import run_alert_engine
results = run_alert_engine(verbose=True)
print(f"Alertas disparadas: {len(results)}")

# Probar evaluadores individualmente
from alerts.engine import evaluate_high_volatility
import pandas as pd
from exchange_monitor.models import ExchangeRate
qs = ExchangeRate.objects.order_by('date').values_list('date', 'rate_parallel')
df = pd.DataFrame(list(qs), columns=['date','rate']).set_index('date')
result = evaluate_high_volatility(df['rate'].astype(float), float(df['rate'].iloc[-1]))
print(result)
```

**Verificación:** Al menos 1 alert type se dispara (umbral 8 con datos que van hasta 13+).

---

## DÍA 6 — Interfaz Django Básica (2 horas)

**Objetivo:** Dashboard funcionando con datos reales.

```
Orden de archivos a crear:
1.  exchange_monitor/views.py              ← ya existe en repo
2.  exchange_monitor/urls.py               ← ya existe en repo
3.  api/serializers.py                     ← ya existe en repo
4.  api/views.py                           ← ya existe en repo
5.  api/urls.py                            ← ya existe en repo
6.  templates/base.html                   ← ya existe en repo
7.  templates/registration/login.html     ← crear
8.  templates/exchange_monitor/dashboard.html  ← ya existe en repo
9.  templates/exchange_monitor/alerts.html     ← crear
10. templates/exchange_monitor/settings.html   ← crear
11. templates/exchange_monitor/model_metrics.html  ← crear
```

**Comandos del día:**
```bash
python manage.py runserver
# Visitar:
# http://localhost:8000/         → Dashboard (requiere login)
# http://localhost:8000/login/   → Página de login
# http://localhost:8000/api/     → API browser
# http://localhost:8000/api/rates/    → JSON rates
# http://localhost:8000/api/status/   → System status
```

**Verificación:** Dashboard muestra tipo de cambio actual y mini chart.

---

## DÍA 7 — Gráficos y Dashboard Completo (2 horas)

**Objetivo:** Todas las páginas con Plotly charts interactivos.

```
Orden de archivos a crear:
1.  templates/exchange_monitor/historical.html   ← ya existe en repo (view también)
2.  templates/exchange_monitor/forecast.html     ← ya existe en repo
3.  static/css/custom.css                        ← estilos adicionales
4.  static/js/app.js                             ← JS utilities
```

**Comandos del día:**
```bash
python manage.py collectstatic
python manage.py runserver

# Verificar todas las páginas:
# /           → Dashboard con KPIs y mini chart
# /historical/ → Serie completa con zoom
# /forecast/   → Pronóstico + IC bands
# /alerts/     → Lista de alertas disparadas
# /settings/   → Formulario para crear alertas
# /metrics/    → Tabla ARIMA configs + forecasts
# /api/forecast/ → JSON con forecast completo
```

**Verificación:** Todas las páginas renderizan sin errores 500. Plotly charts visibles.

---

## DÍA 8 — README, Tests y GitHub (1 hora)

**Objetivo:** Repositorio limpio, documentado y publicado.

```
Orden de archivos a crear/completar:
1.  README.md                              ← ya existe en repo, personalizar
2.  .gitignore
3.  LICENSE
4.  tests/unit/test_alert_engine.py        ← tests básicos
5.  tests/unit/test_arima_analysis.py
6.  docs/architecture.md
```

**Comandos del día:**
```bash
# Crear .gitignore
echo "venv/
*.pyc
__pycache__/
.env
*.log
media/
staticfiles/
*.sqlite3" > .gitignore

# Inicializar git
git init
git add .
git commit -m "feat: initial implementation — Exchange Rate Alert System

- ARIMA(p,d,q) forecasting with grid search and AIC selection
- 4 alert types: absolute threshold, % change, volatility, spread
- Django dashboard with Plotly interactive charts
- REST API with DRF
- APScheduler for daily automated runs
- Email + WhatsApp notifications via Twilio
- Synthetic historical data April 2023-March 2026"

# Push a GitHub
git remote add origin https://github.com/yourusername/exchange-rate-alert-bolivia.git
git branch -M main
git push -u origin main
```

---

## RESUMEN DE ARCHIVOS POR MÓDULO

| Módulo | Archivos clave | Líneas aprox. |
|--------|----------------|---------------|
| config/ | settings.py, urls.py | 180 |
| exchange_monitor/ | models.py, views.py, urls.py | 420 |
| arima/ | analysis.py, forecaster.py | 580 |
| alerts/ | engine.py, notifications.py, scheduler.py | 460 |
| api/ | serializers.py, views.py, urls.py | 200 |
| templates/ | base.html + 5 page templates | 600 |
| scripts/ | generate_synthetic_data.py, create_schema.sql | 200 |
| **Total** | | **~2,640 líneas** |

---

## COMANDOS DE MANAGEMENT ÚTILES

```bash
# Ver todos los forecasts guardados
python manage.py shell -c "from exchange_monitor.models import Forecast; print(Forecast.objects.all())"

# Re-correr alertas manualmente
python manage.py shell -c "from alerts.engine import run_alert_engine; run_alert_engine()"

# Resetear forecasts (test)
python manage.py shell -c "from exchange_monitor.models import Forecast; Forecast.objects.all().delete()"

# Ver logs del scheduler
tail -f logs/scheduler.log

# Ver logs del módulo ARIMA
tail -f logs/arima.log
```
