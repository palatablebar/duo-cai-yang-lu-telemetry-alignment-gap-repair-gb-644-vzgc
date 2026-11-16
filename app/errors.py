"""领域异常与 HTTP 映射。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class GridlabError(Exception):
    code = "GRIDLAB_ERROR"
    status = 400

    def __init__(self, message: str, *, code: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class InputError(GridlabError):
    status = 400
    code = "INPUT_INVALID"


class NotFoundError(GridlabError):
    status = 404
    code = "NOT_FOUND"


class StateError(GridlabError):
    status = 409
    code = "STATE_CONFLICT"


async def handle_gridlab_error(request: Request, exc: GridlabError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.as_dict())
