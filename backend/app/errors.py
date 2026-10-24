"""Application exceptions mapped to consistent HTTP error responses."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class NotFoundError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(404, "NOT_FOUND", message)


class ConflictError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "CONFLICT", message)


class CaptureValidationError(ApiError):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(422, code, message)


class PayloadTooLargeError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(413, "TOO_LARGE", message)


class RecoveryError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(500, "RECOVERY_ERROR", message)
