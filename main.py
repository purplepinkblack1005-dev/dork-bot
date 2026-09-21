import os
import uuid
import logging
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
INURL_FILE = BASE_DIR / "shop.txt"
KEYWORDS_FILE = BASE_DIR / "keywords.txt"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Templates live in the project root, no subfolder
templates = Jinja2Templates(directory=str(BASE_DIR))

# In-memory session store
SESSIONS: dict[str, dict] = {}


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def load_wordlist(path: Path) -> list[str]:
    if not path.exists():
        logger.warning(f"Wordlist missing: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def build_site_filter(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in ("", "none", "no", "-", "null", "skip"):
        return ""
    parts = [p.strip().lstrip(".") for p in raw.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"site:.{parts[0]}"
    return "(" + " OR ".join(f"site:.{p}" for p in parts) + ")"


def generate_dorks(keywords, inurl_words, keyword_words, site_filter=""):
    suffix = f" {site_filter}" if site_filter else ""
    dorks = []
    for kw in keywords:
        for iu in inurl_words:
            for kww in keyword_words:
                dorks.append(f"inurl:{iu} intext:({kw}) {kww}{suffix}")
    return dorks


# ------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    keywords: str = Form(...),
    targets: str = Form(""),
):
    kw_list = [k.strip().upper() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        raise HTTPException(400, "No valid keywords provided.")

    inurl_words = load_wordlist(INURL_FILE)
    keyword_words = load_wordlist(KEYWORDS_FILE)

    if not inurl_words:
        raise HTTPException(500, "shop.txt is missing or empty.")
    if not keyword_words:
        raise HTTPException(500, "keywords.txt is missing or empty.")

    site_filter = build_site_filter(targets)
    dorks = generate_dorks(kw_list, inurl_words, keyword_words, site_filter)

    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {
        "keywords": kw_list,
        "targets": targets or "none",
        "site_filter": site_filter,
        "dorks": dorks,
        "count": len(dorks),
    }

    raw_url = str(request.url_for("raw_dorks", session_id=session_id))
    download_url = str(request.url_for("download_dorks", session_id=session_id))

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "session_id": session_id,
            "keywords": ", ".join(kw_list),
            "targets": targets or "none",
            "count": len(dorks),
            "raw_url": raw_url,
            "download_url": download_url,
            "preview": dorks[:15],
        },
    )


@app.get("/raw/{session_id}", response_class=PlainTextResponse, name="raw_dorks")
async def raw_dorks(session_id: str):
    data = SESSIONS.get(session_id)
    if not data:
        raise HTTPException(404, "Session not found or expired.")
    return PlainTextResponse("\n".join(data["dorks"]) + "\n")


@app.get("/download/{session_id}", name="download_dorks")
async def download_dorks(session_id: str):
    data = SESSIONS.get(session_id)
    if not data:
        raise HTTPException(404, "Session not found or expired.")
    body = "\n".join(data["dorks"]) + "\n"
    headers = {
        "Content-Disposition": f'attachment; filename="dorks_{session_id}.txt"'
    }
    return Response(content=body, media_type="text/plain", headers=headers)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "OK"


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
