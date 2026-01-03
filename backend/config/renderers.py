from __future__ import annotations

from rest_framework.renderers import JSONRenderer

_SUCCESS_ENVELOPE_KEYS = frozenset({"data", "meta"})


class EnvelopeJSONRenderer(JSONRenderer):
    """
    Wrap successful JSON responses in a `{ "data": ... }` envelope.

    Error responses are formatted by `config.exception_handler.custom_exception_handler`
    and are not wrapped here.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get("response") if renderer_context else None
        if response and response.status_code >= 400:
            return super().render(data, accepted_media_type, renderer_context)

        if self._is_already_enveloped(data):
            return super().render(data, accepted_media_type, renderer_context)

        return super().render({"data": data}, accepted_media_type, renderer_context)

    def _is_already_enveloped(self, data) -> bool:
        if not isinstance(data, dict):
            return False
        if "data" not in data:
            return False
        return set(data.keys()).issubset(_SUCCESS_ENVELOPE_KEYS)

