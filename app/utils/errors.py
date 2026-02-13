from __future__ import annotations

from fastapi.responses import JSONResponse


def error_response(
    status_code: int, message: str, received_body: dict | None = None
) -> JSONResponse:
    content: dict = {"error": message}
    if received_body is not None:
        content["received_body"] = received_body
    return JSONResponse(status_code=status_code, content=content)
