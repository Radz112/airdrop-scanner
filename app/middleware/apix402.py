import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("apix402")


class APIX402BodyUnwrapper(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            body = await request.body()
            try:
                parsed = json.loads(body)
                logger.debug(f"Raw request body: {parsed}")
                logger.debug(
                    f"Headers: content-type={request.headers.get('content-type')}"
                )

                # Unwrap nested body if present
                if "body" in parsed and isinstance(parsed["body"], dict):
                    parsed = {**parsed, **parsed["body"]}
                    del parsed["body"]

                request.state.parsed_body = parsed
            except Exception as e:
                logger.error(f"Body parse error: {e}, raw: {body[:500]}")
                request.state.parsed_body = {}
        else:
            request.state.parsed_body = {}

        return await call_next(request)
