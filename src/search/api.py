"""Compatibility entry point for the shared search/recommendation API."""
from src.search.transport import SearchTransport as SearchTransport
from src.serving.main import app as app, create_app as create_app

__all__ = ['SearchTransport', 'app', 'create_app']
