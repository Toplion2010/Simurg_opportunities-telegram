"""One-time webhook registration, run from a browser.

The Koyeb container could call set_webhook in a startup hook. A serverless
function has no startup -- it only exists while handling a request -- so
registration has to be triggered manually, once, after the first deploy.

Visit, replacing the secret with SIMURG_WEBHOOK_SECRET:

    https://<project>.vercel.app/api/setup?secret=...            -> register
    https://<project>.vercel.app/api/setup?secret=...&action=info    -> inspect
    https://<project>.vercel.app/api/setup?secret=...&action=delete  -> ROLLBACK

``delete`` is the rollback switch. A webhook and getUpdates are mutually
exclusive, so while one is registered drain.yml stops polling (it detects this
via getWebhookInfo and skips). Deleting it hands delivery straight back to
GitHub Actions -- queued taps are preserved either way, since neither
set_webhook nor delete_webhook is called with drop_pending_updates.

Registration deliberately does NOT drop pending updates: taps queued while the
webhook was down are real approvals.
"""
import json
import os
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

_API = "https://api.telegram.org/bot{token}/{method}"
# Must match api/telegram.py, which serves the path Telegram posts to.
_WEBHOOK_PATH = "/api/telegram"


def _call(token: str, method: str, params: dict | None = None) -> dict:
    url = _API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.loads(r.read().decode())


class handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        try:
            token = os.environ["BOT_TOKEN"]
            secret = os.environ["SIMURG_WEBHOOK_SECRET"]
        except KeyError as e:
            self._reply(500, f"missing env var: {e}")
            return

        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("secret", [""])[0] != secret:
            self._reply(403, "forbidden: pass ?secret=<SIMURG_WEBHOOK_SECRET>")
            return

        action = query.get("action", ["set"])[0]

        try:
            if action == "delete":
                result = _call(token, "deleteWebhook", {"drop_pending_updates": "false"})
                info = _call(token, "getWebhookInfo")
                self._reply(
                    200,
                    "WEBHOOK DELETED -- GitHub Actions polling resumes on the next "
                    f"drain run.\n\n{json.dumps(result)}\n\n{json.dumps(info, indent=2)}",
                )
                return

            if action == "info":
                self._reply(200, json.dumps(_call(token, "getWebhookInfo"), indent=2))
                return

            # Vercel gives the deployment's own host in the Host header, so the
            # URL is derived rather than configured -- one less thing to mistype
            # and it stays correct across preview and production deployments.
            host = self.headers.get("Host", "")
            if not host:
                self._reply(500, "no Host header; cannot derive the webhook URL")
                return

            result = _call(
                token,
                "setWebhook",
                {
                    "url": f"https://{host}{_WEBHOOK_PATH}",
                    "secret_token": secret,
                    "allowed_updates": json.dumps(["message", "callback_query"]),
                    "drop_pending_updates": "false",
                },
            )
            info = _call(token, "getWebhookInfo")
            self._reply(
                200,
                f"WEBHOOK SET -> https://{host}{_WEBHOOK_PATH}\n\n"
                f"{json.dumps(result)}\n\n{json.dumps(info, indent=2)}\n\n"
                "Tap Approve in Telegram; it should apply within seconds.\n"
                "Rollback: add &action=delete to this URL.",
            )
        except Exception:
            self._reply(500, traceback.format_exc())
