-- ============================================================
-- Exchange Rate Alert System — MySQL Schema
-- Project: Kapitalya / exchange-rate-alert-bolivia
-- 
-- Run this BEFORE Django migrations to ensure the database
-- and character set are properly configured.
-- 
-- Usage:
--   mysql -u root -p < scripts/create_schema.sql
-- ============================================================

-- Create database
CREATE DATABASE IF NOT EXISTS exchange_rate_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE exchange_rate_db;

-- ============================================================
-- TABLE 1: exchange_rates
-- Historical daily BOB/USD parallel market rates
-- ============================================================
CREATE TABLE IF NOT EXISTS exchange_rates (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT 'Surrogate key',
    date            DATE NOT NULL COMMENT 'Trading date (one row per business day)',
    rate_parallel   DECIMAL(8,4) NOT NULL COMMENT 'Parallel market BOB/USD rate',
    rate_official   DECIMAL(8,4) NULL COMMENT 'Official BCB BOB/USD rate (~6.96)',
    spread          DECIMAL(8,4) NULL COMMENT 'Computed: rate_parallel - rate_official',
    volume_indicator TINYINT UNSIGNED NULL COMMENT '1=very low, 5=very high market activity',
    source          VARCHAR(120) NOT NULL DEFAULT 'manual_entry'
                    COMMENT 'Data origin: manual_entry | scraper | api_bcb',
    notes           TEXT COMMENT 'Free-text annotations for this date',
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_er_date (date),
    INDEX idx_er_parallel (rate_parallel),
    INDEX idx_er_created  (created_at)
) ENGINE=InnoDB
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci
  COMMENT 'Historical exchange rate observations';


-- ============================================================
-- TABLE 2: forecasts
-- Metadata for each ARIMA forecast run
-- ============================================================
CREATE TABLE IF NOT EXISTS forecasts (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    forecast_from        DATE NOT NULL COMMENT 'First forecasted business day',
    forecast_to          DATE NOT NULL COMMENT 'Last forecasted business day (D+14)',
    model_order          VARCHAR(20) NOT NULL COMMENT 'e.g. (2,1,2)',
    aic_score            DOUBLE NULL COMMENT 'Akaike Information Criterion',
    bic_score            DOUBLE NULL COMMENT 'Bayesian Information Criterion',
    train_observations   INT NOT NULL COMMENT 'N training data points',
    mae                  DOUBLE NULL COMMENT 'Walk-forward MAE (BOB)',
    rmse                 DOUBLE NULL COMMENT 'Walk-forward RMSE (BOB)',
    mape                 DOUBLE NULL COMMENT 'Walk-forward MAPE (%)',
    coverage_80          DOUBLE NULL COMMENT '% of actuals inside 80% CI',
    coverage_95          DOUBLE NULL COMMENT '% of actuals inside 95% CI',
    status               ENUM('pending','success','failed') NOT NULL DEFAULT 'pending',
    error_message        TEXT COMMENT 'Error detail if status=failed',
    is_active            TINYINT(1) NOT NULL DEFAULT 1
                         COMMENT 'Only the latest active forecast drives alerts',

    INDEX idx_fc_created  (created_at),
    INDEX idx_fc_active   (is_active, status)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'ARIMA forecast run metadata';


-- ============================================================
-- TABLE 3: forecast_points
-- Individual day-level forecast values with CI bands
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_points (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    forecast_id      BIGINT UNSIGNED NOT NULL,
    date             DATE NOT NULL COMMENT 'Forecasted date',
    predicted_value  DECIMAL(8,4) NOT NULL,
    ci_lower_80      DECIMAL(8,4) NOT NULL COMMENT 'IC 80% lower bound',
    ci_upper_80      DECIMAL(8,4) NOT NULL COMMENT 'IC 80% upper bound',
    ci_lower_95      DECIMAL(8,4) NOT NULL COMMENT 'IC 95% lower bound',
    ci_upper_95      DECIMAL(8,4) NOT NULL COMMENT 'IC 95% upper bound',
    actual_value     DECIMAL(8,4) NULL COMMENT 'Actual rate (filled post-hoc)',
    step_ahead       SMALLINT NOT NULL COMMENT '1 = next day, 14 = two weeks',

    UNIQUE KEY uq_fp_forecast_date (forecast_id, date),
    INDEX idx_fp_date (date),
    CONSTRAINT fk_fp_forecast
        FOREIGN KEY (forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'Per-day forecast values and confidence intervals';


-- ============================================================
-- TABLE 4: alert_configurations
-- User-defined alert rules
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_configurations (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id             INT NOT NULL COMMENT 'Django auth_user FK',
    name                VARCHAR(200) NOT NULL,
    alert_type          ENUM(
                            'absolute_threshold',
                            'pct_change',
                            'high_volatility',
                            'unusual_spread'
                        ) NOT NULL,
    threshold_value     DECIMAL(10,4) NULL
                        COMMENT 'BOB amount / % / multiplier depending on type',
    lookback_days       SMALLINT NOT NULL DEFAULT 7,
    severity            ENUM('green','yellow','red') NOT NULL DEFAULT 'yellow',
    is_active           TINYINT(1) NOT NULL DEFAULT 1,
    notify_email        TINYINT(1) NOT NULL DEFAULT 1,
    notify_whatsapp     TINYINT(1) NOT NULL DEFAULT 0,
    email_recipients    TEXT COMMENT 'Comma-separated email addresses',
    whatsapp_recipients TEXT COMMENT 'Comma-separated numbers with country code',
    created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                        ON UPDATE CURRENT_TIMESTAMP(6),

    INDEX idx_ac_user   (user_id),
    INDEX idx_ac_active (is_active),
    CONSTRAINT fk_ac_user
        FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'User-configured alert rules';


-- ============================================================
-- TABLE 5: triggered_alerts
-- Immutable log of every fired alert
-- ============================================================
CREATE TABLE IF NOT EXISTS triggered_alerts (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    configuration_id     BIGINT UNSIGNED NULL COMMENT 'NULL if config was deleted',
    forecast_id          BIGINT UNSIGNED NULL,
    triggered_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    current_rate         DECIMAL(8,4) NOT NULL,
    trigger_value        DECIMAL(10,4) NOT NULL,
    message_es           TEXT NOT NULL,
    message_en           TEXT NOT NULL,
    severity             ENUM('green','yellow','red') NOT NULL,
    notification_sent    TINYINT(1) NOT NULL DEFAULT 0,
    notification_sent_at DATETIME(6) NULL,

    INDEX idx_ta_triggered   (triggered_at),
    INDEX idx_ta_severity    (severity),
    INDEX idx_ta_config      (configuration_id),
    CONSTRAINT fk_ta_config
        FOREIGN KEY (configuration_id) REFERENCES alert_configurations(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_ta_forecast
        FOREIGN KEY (forecast_id) REFERENCES forecasts(id) ON DELETE SET NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'Immutable log of every triggered alert';


-- ============================================================
-- TABLE 6: arima_model_configs
-- Persisted ARIMA (p,d,q) parameters from grid search
-- ============================================================
CREATE TABLE IF NOT EXISTS arima_model_configs (
    id                          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    p                           SMALLINT NOT NULL COMMENT 'AR order',
    d                           SMALLINT NOT NULL COMMENT 'Integration order',
    q                           SMALLINT NOT NULL COMMENT 'MA order',
    aic                         DOUBLE NOT NULL,
    bic                         DOUBLE NULL,
    log_likelihood              DOUBLE NULL,
    is_current                  TINYINT(1) NOT NULL DEFAULT 1,
    selected_at                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    trained_on_observations     INT NOT NULL,
    grid_search_duration_seconds DOUBLE NULL,
    notes                       TEXT,

    INDEX idx_amc_current (is_current),
    INDEX idx_amc_aic     (aic)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'Best ARIMA parameters from each grid search';


-- ============================================================
-- TABLE 7: notification_logs
-- Delivery audit trail for email and WhatsApp
-- ============================================================
CREATE TABLE IF NOT EXISTS notification_logs (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    triggered_alert_id BIGINT UNSIGNED NOT NULL,
    channel           ENUM('email','whatsapp') NOT NULL,
    recipient         VARCHAR(255) NOT NULL,
    subject           VARCHAR(255) NULL,
    status            ENUM('pending','sent','failed') NOT NULL DEFAULT 'pending',
    sent_at           DATETIME(6) NULL,
    error_message     TEXT,
    retry_count       SMALLINT NOT NULL DEFAULT 0,

    INDEX idx_nl_alert   (triggered_alert_id),
    INDEX idx_nl_status  (status),
    CONSTRAINT fk_nl_alert
        FOREIGN KEY (triggered_alert_id) REFERENCES triggered_alerts(id)
        ON DELETE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  COMMENT 'Email and WhatsApp notification delivery log';
