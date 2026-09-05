"""Structured security logging helpers."""

from __future__ import annotations

import logging
from typing import Any


class StructuredAdapter(logging.LoggerAdapter):
    """Adapter that routes arbitrary keyword arguments into logging extra."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        extra = kwargs.get('extra', {})
        if not isinstance(extra, dict):
            extra = {'extra_value': extra}
        for k in list(kwargs.keys()):
            if k not in ('exc_info', 'stack_info', 'stacklevel', 'extra'):
                extra[k] = kwargs.pop(k)
        kwargs['extra'] = extra
        return msg, kwargs

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.warning(msg, *args, **kwargs)


def get_logger(name: str = 'security') -> StructuredAdapter:
    base = logging.getLogger(name)
    return StructuredAdapter(base, {})
