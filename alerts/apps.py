from django.apps import AppConfig

class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alerts"
    verbose_name = "Alert Engine"

    def ready(self):
        """Start APScheduler when Django boots (not in migrations)."""
        import sys
        if "migrate" not in sys.argv and "makemigrations" not in sys.argv:
            try:
                from alerts.scheduler import start_scheduler
                start_scheduler()
            except Exception as e:
                import logging
                logging.getLogger("scheduler").warning("Scheduler start failed: %s", e)
