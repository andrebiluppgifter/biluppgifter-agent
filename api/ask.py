"""
Biluppgifter API-assistent – Vercel serverless function
Håller Anthropic API-nyckeln säkert på servern via miljövariabeln ANTHROPIC_API_KEY.
"""

from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import os
import re

DOCS_URL = "https://data.biluppgifter.se/"

# Module-level cache – lever under warm starts på samma instans
_docs_cache: str | None = None


def fetch_docs() -> str:
    """Hämtar och sanerar HTML från Biluppgifters dokumentationssajt."""
    global _docs_cache
    if _docs_cache:
        return _docs_cache

    req = urllib.request.Request(
        DOCS_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; BiluppgifterBot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Ta bort script/style och HTML-taggar
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    _docs_cache = text[:40_000]  # Max ~40 000 tecken för att hålla oss inom tokens
    return _docs_cache


def build_system_prompt(docs: str, tone: str, include_refs: bool) -> str:
    tone_instr = (
        "Svara tekniskt och precist. Använd korrekt terminologi, visa kodexempel i "
        "kodblock (curl, Python, JavaScript), och var detaljerad. Anta att läsaren är en utvecklare."
        if tone == "technical"
        else "Svara pedagogiskt och engagerande. Förklara med analogier och enkla termer "
        "som för någon helt ny till API:et. Undvik onödig jargong."
    )
    ref_instr = (
        "Inkludera alltid källreferenser – ange vilken endpoint, parameter eller sektion "
        "i dokumentationen du hänvisar till."
        if include_refs
        else "Inkludera INGA källreferenser eller hänvisningar till dokumentationssektioner. "
        "Ge bara det direkta svaret."
    )
    return (
        "Du är en hjälpsam AI-assistent specialiserad på Biluppgifters API.\n\n"
        "REGLER (obligatoriska):\n"
        "1. Besvara ENBART frågor baserat på dokumentationen nedan.\n"
        "2. Hittar du inte svaret, säg tydligt: "
        "\"Den informationen finns inte i den tillgängliga dokumentationen.\"\n"
        "3. Hitta inte på endpoints, parametrar eller beteenden som inte framgår av dokumentationen.\n"
        "4. Svara på svenska om inte användaren skriver på ett annat språk.\n"
        f"5. {tone_instr}\n"
        f"6. {ref_instr}\n\n"
        f"API-DOKUMENTATION (källa: {DOCS_URL}):\n"
        + "─" * 60 + "\n"
        + docs + "\n"
        + "─" * 60
    )


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            self._respond(500, {"error": "API-nyckel saknas på servern. Kontakta administratören."})
            return

        # Läs request body
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, {"error": "Ogiltig förfrågan."})
            return

        question = body.get("question", "").strip()
        tone = body.get("tone", "technical")
        include_refs = bool(body.get("includeRefs", True))

        if not question:
            self._respond(400, {"error": "Fråga saknas."})
            return

        # Hämta dokumentation
        try:
            docs = fetch_docs()
        except Exception as exc:
            self._respond(502, {"error": f"Kunde inte hämta API-dokumentationen: {exc}"})
            return

        system = build_system_prompt(docs, tone, include_refs)

        # Anropa Anthropic
        payload = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": question}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            answer = result["content"][0]["text"]
            self._respond(200, {"answer": answer})

        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read())
                msg = err_body.get("error", {}).get("message", f"HTTP {exc.code}")
            except Exception:
                msg = f"HTTP {exc.code}"
            self._respond(500, {"error": f"Anthropic-fel: {msg}"})

        except Exception as exc:
            self._respond(500, {"error": f"Oväntat fel: {exc}"})

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _respond(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # Tystar Vercels standard-logg
