from django.db import migrations


def repair_stale_status(apps, schema_editor):
    """Reset runtime status left stuck at 'error_suspended' on rules that are no longer suspended.

    The circuit breaker historically set both ``error_suspended=True`` and
    ``status='error_suspended'``, but the recovery path only cleared the boolean — leaving
    the ``status`` label stale on active rules (display-only; firing is gated by the boolean).
    The code fix prevents this going forward; this repairs rows whose recovery already ran.
    """
    RuleRuntimeState = apps.get_model("alarm", "RuleRuntimeState")
    RuleRuntimeState.objects.filter(status="error_suspended", error_suspended=False).update(status="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0019_pendingaction"),
    ]

    operations = [
        migrations.RunPython(repair_stale_status, migrations.RunPython.noop),
    ]
