from __future__ import annotations


def extract_param(
    request_body: dict, param_name: str, aliases: list[str] | None = None
) -> str | None:
    aliases = aliases or []
    all_names = [param_name] + aliases

    for name in all_names:
        if name in request_body:
            return request_body[name]
        if "body" in request_body and isinstance(request_body["body"], dict):
            if name in request_body["body"]:
                return request_body["body"][name]

    return None
