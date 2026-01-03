"""
Notification dispatcher.

Central hub for sending notifications through configured providers.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .encryption import decrypt_config
from .handlers import get_handler
from .handlers.base import NotificationResult
from .models import NotificationDelivery, NotificationLog, NotificationProvider

logger = logging.getLogger(__name__)

# Special ID for the Home Assistant system provider
# This provider is auto-created when HA is configured and uses the HA integration directly
HA_SYSTEM_PROVIDER_ID = "ha-system-provider"


class NotificationDispatcher:
    """
    Central dispatcher for sending notifications.

    Resolves provider by ID, decrypts config, and routes to appropriate handler.
    Also handles logging of notification attempts.
    """

    def _send_now(
        self,
        provider_id: str,
        message: str,
        title: str | None = None,
        data: dict | None = None,
        rule_name: str = "",
    ) -> NotificationResult:
        """
        Send notification to a configured provider by ID.

        Args:
            provider_id: UUID of the notification provider, or HA_SYSTEM_PROVIDER_ID
            message: Notification message body
            title: Optional notification title
            data: Optional provider-specific data (for HA: must include 'service')
            rule_name: Optional name of rule that triggered this (for logging)

        Returns:
            NotificationResult indicating success or failure
        """
        # Handle the special HA system provider
        if provider_id == HA_SYSTEM_PROVIDER_ID:
            return self._send_via_ha_system_provider(
                message=message,
                title=title,
                data=data,
                rule_name=rule_name,
            )

        try:
            provider = NotificationProvider.objects.get(id=provider_id)
        except NotificationProvider.DoesNotExist:
            logger.error(f"Notification provider not found: {provider_id}")
            return NotificationResult.error(
                f"Provider not found: {provider_id}",
                code="PROVIDER_NOT_FOUND",
            )

        return self.send_to_provider(
            provider=provider,
            message=message,
            title=title,
            data=data,
            rule_name=rule_name,
        )

    def send(self, *args, **kwargs) -> NotificationResult:  # pragma: no cover
        """
        Deprecated: synchronous send path.

        Use `enqueue()` for normal operation; `_send_now()` is reserved for the outbox
        worker and synchronous test endpoints.
        """
        raise RuntimeError("Do not call NotificationDispatcher.send(); use enqueue()/_send_now().")

    def enqueue(
        self,
        *,
        profile,
        provider_id: str,
        message: str,
        title: str | None = None,
        data: dict | None = None,
        rule_name: str = "",
        idempotency_key: str | None = None,
    ) -> tuple[NotificationDelivery | None, NotificationResult]:
        """
        Enqueue a durable NotificationDelivery for async sending.

        Returns (delivery, result). On failure, delivery is None.
        """
        if provider_id == HA_SYSTEM_PROVIDER_ID:
            data = data or {}
            service = data.get("service")
            if not isinstance(service, str) or not service:
                return None, NotificationResult.error(
                    "No Home Assistant service specified",
                    code="MISSING_SERVICE",
                )
            provider: NotificationProvider | None = None
        else:
            try:
                provider = NotificationProvider.objects.get(id=provider_id, profile=profile)
            except NotificationProvider.DoesNotExist:
                return None, NotificationResult.error(
                    f"Provider not found: {provider_id}",
                    code="PROVIDER_NOT_FOUND",
                )
            if not provider.is_enabled:
                return None, NotificationResult.error(
                    f"Provider is disabled: {provider.name}",
                    code="PROVIDER_DISABLED",
                )

        defaults = {
            "profile": profile,
            "provider": provider,
            "provider_key": provider_id,
            "message": message,
            "title": title or "",
            "data": data or {},
            "rule_name": rule_name,
            "status": NotificationDelivery.Status.PENDING,
            "next_attempt_at": timezone.now(),
        }

        try:
            with transaction.atomic():
                if idempotency_key:
                    delivery, _created = NotificationDelivery.objects.get_or_create(
                        idempotency_key=idempotency_key,
                        defaults=defaults,
                    )
                else:
                    delivery = NotificationDelivery.objects.create(**defaults)
        except IntegrityError:
            if idempotency_key:
                delivery = NotificationDelivery.objects.filter(idempotency_key=idempotency_key).first()
                if delivery:
                    return delivery, NotificationResult.ok("Enqueued (deduplicated)")
            return None, NotificationResult.error("Failed to enqueue notification", code="ENQUEUE_FAILED")

        return delivery, NotificationResult.ok("Enqueued")

    def send_to_provider(
        self,
        provider: NotificationProvider,
        message: str,
        title: str | None = None,
        data: dict | None = None,
        rule_name: str = "",
    ) -> NotificationResult:
        """
        Send notification using a provider instance.

        Args:
            provider: NotificationProvider instance
            message: Notification message body
            title: Optional notification title
            data: Optional provider-specific data
            rule_name: Optional name of rule that triggered this (for logging)

        Returns:
            NotificationResult indicating success or failure
        """
        if not provider.is_enabled:
            logger.info(f"Provider is disabled: {provider.name}")
            return NotificationResult.error(
                f"Provider is disabled: {provider.name}",
                code="PROVIDER_DISABLED",
            )

        try:
            handler = get_handler(provider.provider_type)
        except ValueError as e:
            logger.error(f"Unknown provider type: {provider.provider_type}")
            return NotificationResult.error(str(e), code="UNKNOWN_PROVIDER_TYPE")

        # Decrypt sensitive config fields
        config = decrypt_config(provider.config, handler.encrypted_fields)

        # Send notification
        result = handler.send(config, message, title, data)

        # Log the attempt
        self._log_notification(provider, message, result, rule_name)

        return result

    def _send_via_ha_system_provider(
        self,
        message: str,
        title: str | None = None,
        data: dict | None = None,
        rule_name: str = "",
    ) -> NotificationResult:
        """
        Send notification via the Home Assistant system provider.

        The HA service to use must be specified in data['service'].
        """
        data = data or {}
        service = data.get("service")

        if not service:
            return NotificationResult.error(
                "No Home Assistant service specified",
                code="MISSING_SERVICE",
            )

        try:
            handler = get_handler("home_assistant")
        except ValueError as e:
            return NotificationResult.error(str(e), code="UNKNOWN_PROVIDER_TYPE")

        # Build config with service from data
        config = {"service": service}

        # Remove service from data before passing to handler (it's now in config)
        notification_data = {k: v for k, v in data.items() if k != "service"}

        result = handler.send(config, message, title, notification_data or None)

        # Log the attempt (without a provider record)
        self._log_ha_system_notification(service, message, result, rule_name)

        return result

    def _log_ha_system_notification(
        self,
        service: str,
        message: str,
        result: NotificationResult,
        rule_name: str,
    ) -> None:
        """Log notification attempt for HA system provider."""
        try:
            NotificationLog.objects.create(
                provider=None,  # No provider record for system provider
                provider_name=f"Home Assistant ({service})",
                provider_type="home_assistant",
                status=(
                    NotificationLog.Status.SUCCESS
                    if result.success
                    else NotificationLog.Status.FAILED
                ),
                message_preview=message[:200] if message else "",
                error_message=result.message if not result.success else "",
                error_code=result.error_code or "",
                rule_name=rule_name,
            )
        except Exception:
            logger.exception("Failed to log HA system notification")

    def test_provider(self, provider: NotificationProvider) -> NotificationResult:
        """
        Send a test notification to a provider.

        Args:
            provider: NotificationProvider instance to test

        Returns:
            NotificationResult indicating success or failure
        """
        try:
            handler = get_handler(provider.provider_type)
        except ValueError as e:
            return NotificationResult.error(str(e), code="UNKNOWN_PROVIDER_TYPE")

        config = decrypt_config(provider.config, handler.encrypted_fields)
        result = handler.test(config)

        # Log test attempt
        self._log_notification(
            provider,
            "Test notification",
            result,
            rule_name="[Test]",
        )

        return result

    def _log_notification(
        self,
        provider: NotificationProvider,
        message: str,
        result: NotificationResult,
        rule_name: str,
    ) -> None:
        """Log notification attempt to database."""
        try:
            NotificationLog.objects.create(
                provider=provider,
                provider_name=provider.name,
                provider_type=provider.provider_type,
                status=(
                    NotificationLog.Status.SUCCESS
                    if result.success
                    else NotificationLog.Status.FAILED
                ),
                message_preview=message[:200] if message else "",
                error_message=result.message if not result.success else "",
                error_code=result.error_code or "",
                rule_name=rule_name,
            )
        except Exception:
            # Don't let logging failures break notification sending
            logger.exception("Failed to log notification")


# Singleton instance for convenience
_dispatcher: NotificationDispatcher | None = None


def get_dispatcher() -> NotificationDispatcher:
    """Get the singleton dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NotificationDispatcher()
    return _dispatcher
