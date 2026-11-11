"""Optional local, mandatory container demo gate. Not a multi-user auth system."""
import base64
import binascii
import hmac
import os
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def credentials():
    username = os.getenv("ZAMP_DEMO_USERNAME", "")
    password = os.getenv("ZAMP_DEMO_PASSWORD", "")
    required = os.getenv("ZAMP_REQUIRE_DEMO_AUTH", "0") == "1"
    if required or username or password:
        if not username or ":" in username or len(password) < 24:
            raise RuntimeError("Demo access requires ZAMP_DEMO_USERNAME (without colon) and ZAMP_DEMO_PASSWORD (at least 24 characters)")
        return username.encode("utf-8"), password.encode("utf-8")
    return None


class DemoAccess:
    def __init__(self, app, expected):
        self.app, self.expected = app, expected

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Only this minimal liveness/readiness response is public.
        if scope["path"] == "/health" and scope["method"] in {"GET", "HEAD"}:
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope["headers"]}
        valid = False
        try:
            scheme, value = headers.get(b"authorization", b"").split(b" ", 1)
            if scheme.lower() == b"basic":
                user, password = base64.b64decode(value, validate=True).split(b":", 1)
                valid = hmac.compare_digest(user, self.expected[0]) & hmac.compare_digest(password, self.expected[1])
        except (ValueError, binascii.Error):
            pass
        if not valid:
            response = JSONResponse({"detail": "Demo authentication required"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="Zamp demo", charset="UTF-8"',
                                             "Cache-Control": "no-store"})
            return await response(scope, receive, send)
        # Browsers cache Basic credentials: reject cross-origin mutations (CSRF).
        origin = headers.get(b"origin")
        if origin and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            try:
                parsed = urlsplit(origin.decode("ascii"))
                same = parsed.scheme in {"http", "https"} and parsed.netloc.lower() == headers.get(b"host", b"").decode("ascii").lower()
            except (ValueError, UnicodeError):
                same = False
            if not same:
                return await JSONResponse({"detail": "Cross-origin request forbidden"}, status_code=403)(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message["headers"].append((b"cache-control", b"no-store"))
            await send(message)
        await self.app(scope, receive, private_send)
