import json
import logging
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("apix402")


class APIX402BodyUnwrapper(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            content_type = request.headers.get("content-type", "")
            forwarded_for = request.headers.get("x-forwarded-for", "")
            user_agent = request.headers.get("user-agent", "")
            logger.info(
                f"POST headers: content-type={content_type}, "
                f"x-forwarded-for={forwarded_for}, user-agent={user_agent}"
            )

            body = await request.body()
            logger.info(f"Raw body ({len(body)} bytes): {body[:500]}")

            try:
                parsed = json.loads(body)

                # Unwrap nested body if present
                nested = "body" in parsed and isinstance(parsed["body"], dict)
                if nested:
                    parsed = {**parsed, **parsed["body"]}
                    del parsed["body"]

                # Parse APIX query-string format: {"query": "key=val&key2=val2"}
                if "query" in parsed and isinstance(parsed["query"], str):
                    qs_params = parse_qs(parsed["query"], keep_blank_values=True)
                    # parse_qs returns lists; flatten single values
                    flat = {k: v[0] if len(v) == 1 else v for k, v in qs_params.items()}
                    parsed = {**parsed, **flat}
                    del parsed["query"]
                    logger.info(f"Query-string unwrap: extracted keys={list(flat.keys())}")

                logger.info(
                    f"Body unwrap: nested={nested}, "
                    f"parsed keys={list(parsed.keys())}"
                )

                request.state.parsed_body = parsed
            except Exception as e:
                logger.error(
                    f"Body parse error: {e}, content-type={content_type}, "
                    f"raw: {body[:500]}"
                )
                request.state.parsed_body = {}
        else:
            request.state.parsed_body = {}

        return await call_next(request)
