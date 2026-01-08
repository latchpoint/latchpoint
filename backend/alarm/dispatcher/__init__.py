"""
Centralized rule trigger dispatcher for ADR 0057.

This module receives entity state changes from integrations and evaluates
only the rules that reference those entities, using RuleEntityRef as a
reverse index.
"""

from .config import DispatcherConfig, get_dispatcher_config
from .dispatcher import (
    get_dispatcher_status,
    invalidate_entity_rule_cache,
    notify_entities_changed,
)

__all__ = [
    "DispatcherConfig",
    "get_dispatcher_config",
    "get_dispatcher_status",
    "invalidate_entity_rule_cache",
    "notify_entities_changed",
]
