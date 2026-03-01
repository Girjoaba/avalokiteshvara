"""Factory event processing — HTTP server for receiving failure notifications."""

from .server import create_factory_app

__all__ = ["create_factory_app"]
