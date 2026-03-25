"""
Biluppgifter API-assistent – Vercel serverless function
Håller Anthropic API-nyckeln säkert på servern via miljövariabeln ANTHROPIC_API_KEY.
"""

from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import os

DOCS_URL = "http://data.biluppgifter.se/openapi/v1.json"

# Module-level cache – lever under warm starts på samma instans
_docs_cache: str | None = None


def fetch_docs() -> str:
    """Hämtar och konverterar OpenAPI JSON-spec från Biluppgifter till läsbar text."""
    global _docs_cache
    if _docs_cache:
        return _docs_cache

    req = urllib.request.Request(
        DOCS_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; BiluppgifterBot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read())

    lines = []

    # Grundinfo
    info = data.get("info", {})
    lines.append(f"# {info.get('title', 'Biluppgifter API')}")
    if info.get("description"):
        lines.append(info["description"])
    lines.append(f"Version: {info.get('version', '')}\n")

    # Bas-URLer
    servers = data.get("servers", [])
    if servers:
        lines.append("## Base URLs")
        for s in servers:
            lines.append(f"- {s.get('url', '')}  {s.get('description', '')}")
        lines.append("")

    # Autentisering
    components = data.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    if security_schemes:
        lines.append("## Autentisering")
        for name, scheme in security_schemes.items():
            lines.append(f"**{name}:** typ={scheme.get('type','')}  "
                         f"in={scheme.get('in','')}  namn={scheme.get('name','')}")
            if scheme.get("description"):
                lines.append(scheme["description"])
        lines.append("")

    # Endpoints
    paths = data.get("paths", {})
    if paths:
        lines.append("## Endpoints")
        for path, methods in paths.items():
            for method, details in methods.items():
                if method not in ("get", "post", "put", "delete", "patch"):
                    continue
                lines.append(f"\n### {method.upper()} {path}")
                if details.get("summary"):
                    lines.append(f"**Sammanfattning:** {details['summary']}")
                if details.get("description"):
                    lines.append(f"**Beskrivning:** {details['description']}")

                # Parametrar
                params = details.get("parameters", [])
                if params:
                    lines.append("**Parametrar:**")
                    for p in params:
                        req_flag = " *(obligatorisk)*" if p.get("required") else ""
                        ptype = p.get("schema", {}).get("type", "")
                        desc = p.get("description", "")
                        lines.append(f"- `{p.get('name')}` ({p.get('in')}, {ptype}{req_flag}): {desc}")

                # Svar
                responses = details.get("responses", {})
                if responses:
                    lines.append("**Svar:**")
                    for code, resp in responses.items():
                        lines.append(f"- {code}: {resp.get('description', '')}")

    # Datamodeller
    schemas = components.get("schemas", {})
    if schemas:
        lines.append("\n## Datamodeller")
        for name, schema in schemas.items():
            lines.append(f"\n### {name}")
            if schema.get("description"):
                lines.append(schema["description"])
            props = schema.get("properties", {})
            if props:
                lines.append("**Fält:**")
                for prop_name, prop in props.items():
                    ptype = prop.get("type", "")
                    pdesc = prop.get("description", "")
                    lines.append(f"- `{prop_name}` ({ptype}): {pdesc}")

    result = "\n".join(lines)
    _docs_cache = result[:40_000]
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
