"""
alerts/notifications.py
────────────────────────
Notification delivery module.

Handles:
  - Email (Django send_mail with HTML template)
  - WhatsApp (Twilio API — optional)
  - Notification logging
"""

import logging
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("alerts")


def send_alert_notifications(triggered_alert, config) -> None:
    """
    Dispatch all configured notification channels for a triggered alert.

    Args:
        triggered_alert: TriggeredAlert instance
        config:          AlertConfiguration instance
    """
    success = False

    if config.notify_email and config.email_recipients:
        recipients = [e.strip() for e in config.email_recipients.split(",") if e.strip()]
        for recipient in recipients:
            ok = send_email_notification(triggered_alert, recipient)
            success = success or ok

    if config.notify_whatsapp and config.whatsapp_recipients:
        numbers = [n.strip() for n in config.whatsapp_recipients.split(",") if n.strip()]
        for number in numbers:
            ok = send_whatsapp_notification(triggered_alert, number)
            success = success or ok

    # Update triggered alert notification status
    if success:
        triggered_alert.notification_sent = True
        triggered_alert.notification_sent_at = timezone.now()
        triggered_alert.save(update_fields=["notification_sent", "notification_sent_at"])


def send_email_notification(triggered_alert, recipient: str) -> bool:
    """
    Send HTML email notification for a triggered alert.

    Args:
        triggered_alert: TriggeredAlert instance
        recipient:       Target email address

    Returns:
        True if sent successfully
    """
    from exchange_monitor.models import NotificationLog

    severity_colors = {
        "green":  "#28a745",
        "yellow": "#ffc107",
        "red":    "#dc3545",
    }
    severity_labels = {
        "green":  "INFORMATIVO",
        "yellow": "PRECAUCIÓN",
        "red":    "CRÍTICO",
    }

    context = {
        "alert": triggered_alert,
        "severity_color": severity_colors.get(triggered_alert.severity, "#6c757d"),
        "severity_label": severity_labels.get(triggered_alert.severity, "ALERTA"),
        "current_rate": triggered_alert.current_rate,
        "triggered_at": triggered_alert.triggered_at,
        "dashboard_url": getattr(settings, "SITE_URL", "http://localhost:8000"),
    }

    subject = (
        f"[Kapitalya] Alerta {severity_labels.get(triggered_alert.severity, 'ALERTA')} — "
        f"Tipo de Cambio BOB/USD | {triggered_alert.triggered_at.strftime('%d/%m/%Y %H:%M')}"
    )

    # Plain text fallback
    text_body = f"""
Kapitalya — Exchange Rate Alert System
=======================================

ALERTA: {triggered_alert.message_es}

Tipo de cambio actual: BOB {triggered_alert.current_rate}
Disparada el: {triggered_alert.triggered_at.strftime('%d/%m/%Y a las %H:%M')}
Severidad: {severity_labels.get(triggered_alert.severity, 'N/A')}

Ver dashboard: {context['dashboard_url']}

---
Este es un mensaje automático generado por el sistema de monitoreo de Kapitalya.
"""

    # HTML email body
    html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin:0; padding:0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4; padding:20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1);">

        <!-- Header -->
        <tr>
          <td style="background:{context['severity_color']}; padding:24px 32px; text-align:center;">
            <h1 style="color:#ffffff; margin:0; font-size:22px; letter-spacing:1px;">
              🔔 ALERTA {context['severity_label']}
            </h1>
            <p style="color:rgba(255,255,255,0.85); margin:8px 0 0; font-size:13px;">
              Exchange Rate Alert System — Kapitalya
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="background:#f8f9fa; border-left:4px solid {context['severity_color']}; padding:16px 20px; border-radius:4px;">
                  <p style="margin:0; font-size:15px; color:#333333; line-height:1.6;">
                    {triggered_alert.message_es}
                  </p>
                </td>
              </tr>
            </table>

            <table width="100%" cellpadding="0" cellspacing="12" style="margin-top:24px;">
              <tr>
                <td width="50%" style="background:#f8f9fa; border-radius:6px; padding:16px; text-align:center;">
                  <p style="margin:0; font-size:11px; color:#666; text-transform:uppercase; letter-spacing:1px;">Tipo de Cambio Actual</p>
                  <p style="margin:6px 0 0; font-size:28px; font-weight:bold; color:#333;">BOB {triggered_alert.current_rate}</p>
                </td>
                <td width="50%" style="background:#f8f9fa; border-radius:6px; padding:16px; text-align:center;">
                  <p style="margin:0; font-size:11px; color:#666; text-transform:uppercase; letter-spacing:1px;">Hora de Alerta</p>
                  <p style="margin:6px 0 0; font-size:16px; font-weight:bold; color:#333;">
                    {triggered_alert.triggered_at.strftime('%d/%m/%Y')}<br>
                    <span style="font-size:20px;">{triggered_alert.triggered_at.strftime('%H:%M')}</span>
                  </p>
                </td>
              </tr>
            </table>

            <div style="text-align:center; margin-top:28px;">
              <a href="{context['dashboard_url']}"
                 style="background:{context['severity_color']}; color:#ffffff; padding:12px 32px;
                        border-radius:6px; text-decoration:none; font-weight:bold; font-size:14px; display:inline-block;">
                Ver Dashboard →
              </a>
            </div>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8f9fa; padding:20px 32px; text-align:center; border-top:1px solid #eee;">
            <p style="margin:0; font-size:11px; color:#999;">
              Este es un mensaje automático del sistema de monitoreo Kapitalya.<br>
              Para desactivar estas notificaciones, ajuste su configuración de alertas.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    log = NotificationLog.objects.create(
        triggered_alert=triggered_alert,
        channel="email",
        recipient=recipient,
        subject=subject,
        status="pending",
    )

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)

        log.status = "sent"
        log.sent_at = timezone.now()
        log.save(update_fields=["status", "sent_at"])
        logger.info("Email sent to %s", recipient)
        return True

    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)
        log.save(update_fields=["status", "error_message"])
        logger.error("Email to %s failed: %s", recipient, exc)
        return False


def send_whatsapp_notification(triggered_alert, phone_number: str) -> bool:
    """
    Send WhatsApp message via Twilio API.

    SETUP INSTRUCTIONS:
      1. Create a free Twilio account at https://www.twilio.com
      2. Activate the WhatsApp Sandbox in Twilio Console
      3. Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM to .env
      4. Install: pip install twilio
      5. Recipients must first join the sandbox by sending "join <word-word>" to the sandbox number

    Args:
        triggered_alert: TriggeredAlert instance
        phone_number:    Recipient number with country code (e.g. +59162345678)

    Returns:
        True if sent successfully
    """
    from exchange_monitor.models import NotificationLog

    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_WHATSAPP_FROM

    if not account_sid or not auth_token:
        logger.warning("Twilio credentials not configured. Skipping WhatsApp notification.")
        return False

    severity_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(triggered_alert.severity, "⚪")

    message_body = (
        f"{severity_emoji} *Kapitalya — Alerta de Tipo de Cambio*\n\n"
        f"{triggered_alert.message_es}\n\n"
        f"💱 Tipo actual: *BOB {triggered_alert.current_rate}*\n"
        f"🕐 {triggered_alert.triggered_at.strftime('%d/%m/%Y %H:%M')}\n\n"
        f"Ver dashboard: {getattr(settings, 'SITE_URL', 'http://localhost:8000')}"
    )

    log = NotificationLog.objects.create(
        triggered_alert=triggered_alert,
        channel="whatsapp",
        recipient=phone_number,
        status="pending",
    )

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message_body,
            from_=from_number,
            to=f"whatsapp:{phone_number}",
        )

        log.status = "sent"
        log.sent_at = timezone.now()
        log.save(update_fields=["status", "sent_at"])
        logger.info("WhatsApp sent to %s (SID: %s)", phone_number, message.sid)
        return True

    except ImportError:
        log.status = "failed"
        log.error_message = "twilio package not installed. Run: pip install twilio"
        log.save(update_fields=["status", "error_message"])
        logger.error("Twilio not installed.")
        return False

    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)
        log.save(update_fields=["status", "error_message"])
        logger.error("WhatsApp to %s failed: %s", phone_number, exc)
        return False
