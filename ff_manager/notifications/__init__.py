"""Notifications package."""

from ff_manager.notifications.backends import ResendEmailClient
from ff_manager.notifications.notifier import EmailNotifier

__all__ = ["EmailNotifier", "ResendEmailClient"]
