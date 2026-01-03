from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

try:
    from channels.routing import ProtocolTypeRouter
    from channels.auth import AuthMiddlewareStack
    from channels.routing import URLRouter
except ImportError:
    application = django_asgi_app
else:
    from alarm.middleware import QueryStringTokenAuthMiddleware
    from alarm.routing import websocket_urlpatterns

    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(
                QueryStringTokenAuthMiddleware(URLRouter(websocket_urlpatterns))
            ),
        }
    )
