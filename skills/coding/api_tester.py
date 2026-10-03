"""HTTP API endpoint tester (local; public-web fetch via urllib).

Takes a JSON list of checks — ``{name, method, url, expect_status,
json_path, timeout}`` — and runs them with ``urllib``: GET checks get up to
2 attempts, non-idempotent methods (POST/PUT/PATCH/DELETE) get exactly 1.
Each check reports status, latency, and pass/fail, including an optional
dotted ``json_path`` assertion into a JSON response body.

Only http/https URLs are accepted. ``local_only`` is True because the only
network use is plain public-web fetching with no paid keys.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import cast

from skills.base import Skill, SkillContext

_DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ApiCheck:
    """One endpoint check."""

    name: str
    method: str
    url: str
    expect_status: int = 200
    json_path: str | None = None
    timeout: float = _DEFAULT_TIMEOUT


def _coerce_check(raw: object) -> ApiCheck:
    if not isinstance(raw, dict):
        raise ValueError("each check must be a JSON object")
    name = raw.get("name", "unnamed")
    method = raw.get("method", "GET")
    url = raw.get("url", "")
    if not isinstance(name, str) or not name:
        raise ValueError("check needs a string 'name'")
    if not isinstance(method, str) or not method:
        raise ValueError("check needs a string 'method'")
    if not isinstance(url, str) or not url:
        raise ValueError("check needs a string 'url'")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"only http/https URLs allowed: {url!r}")
    expect_status = raw.get("expect_status", 200)
    if not isinstance(expect_status, int):
        raise ValueError("'expect_status' must be an integer")
    json_path = raw.get("json_path")
    if json_path is not None and not isinstance(json_path, str):
        raise ValueError("'json_path' must be a string")
    timeout = raw.get("timeout", _DEFAULT_TIMEOUT)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("'timeout' must be a positive number")
    return ApiCheck(
        name=name,
        method=method.upper(),
        url=url,
        expect_status=expect_status,
        json_path=json_path,
        timeout=float(timeout),
    )


def _resolve_json_path(body: bytes, path: str) -> tuple[object, str | None]:
    """Navigate a dotted path (dict keys / list indices); return (value, error)."""
    try:
        current: object = cast("object", json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"response is not valid JSON: {exc}"
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None, f"missing key {part!r}"
            current = cast("object", current[part])
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return None, f"{part!r} is not a list index"
            if not 0 <= index < len(current):
                return None, f"list index {index} out of range"
            current = cast("object", current[index])
        else:
            return None, f"cannot descend into {type(current).__name__} at {part!r}"
    return current, None


def run_check(check: ApiCheck) -> dict[str, str]:
    """Run one check; return a string-valued result dict."""
    attempts = 2 if check.method == "GET" else 1
    last_error = ""
    for _ in range(attempts):
        start = time.monotonic()
        try:
            request = urllib.request.Request(check.url, method=check.method)  # noqa: S310
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=check.timeout
            ) as response:
                status = int(response.status)
                body = response.read()
        except OSError as exc:
            last_error = str(exc)
            continue
        latency_ms = int((time.monotonic() - start) * 1000)
        passed = status == check.expect_status
        detail = f"status={status}"
        if passed and check.json_path:
            value, error = _resolve_json_path(body, check.json_path)
            if error is not None:
                passed = False
                detail += f" json_path error: {error}"
            else:
                detail += f" json_path '{check.json_path}' = {value!r}"
        return {
            "name": check.name,
            "passed": "PASS" if passed else "FAIL",
            "status": str(status),
            "latency_ms": str(latency_ms),
            "detail": detail,
        }
    return {
        "name": check.name,
        "passed": "FAIL",
        "status": "error",
        "latency_ms": "0",
        "detail": f"request failed after {attempts} attempt(s): {last_error}",
    }


def _extract_json_array(text: str) -> str:
    stripped = text.strip()
    start = stripped.find("[")
    if start == -1:
        raise ValueError("expected a JSON array of checks in the message")
    return stripped[start:]


class ApiTesterSkill(Skill):
    """Runs HTTP endpoint checks from a JSON spec (urllib, no deps)."""

    name = "api_tester"
    description = (
        "Tests HTTP API endpoints from a JSON list of checks (method, url, "
        "expected status, JSON path); reports status/latency/pass-fail."
    )
    intents = ("api.test",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        try:
            payload = _extract_json_array(context.message)
            raw_checks = cast("list[object]", json.loads(payload))
            if not isinstance(raw_checks, list) or not raw_checks:
                raise ValueError("need a non-empty JSON array of checks")
            checks = [_coerce_check(item) for item in raw_checks]
        except (ValueError, json.JSONDecodeError) as exc:
            return (
                f"api test spec error: {exc}\n"
                'usage: api.test [{"name": "...", "method": "GET", "url": "https://...", '
                '"expect_status": 200, "json_path": "data.id", "timeout": 10}]'
            )
        results = [run_check(check) for check in checks]
        lines = ["api test results:"]
        for result in results:
            lines.append(
                f"[{result['passed']}] {result['name']}: "
                f"{result['detail']} ({result['latency_ms']}ms)"
            )
        passed = sum(1 for r in results if r["passed"] == "PASS")
        lines.append(f"{passed}/{len(results)} checks passed")
        return "\n".join(lines)


SKILLS: list[Skill] = [ApiTesterSkill()]
