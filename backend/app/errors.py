"""Application exceptions mapped to consistent HTTP error responses."""
from __future__ import annotations


class NotFoundError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
