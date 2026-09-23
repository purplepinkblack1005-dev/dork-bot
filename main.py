import os
import uuid
import random
import logging
from collections import OrderedDict
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
INURL_FILE = BASE_DIR / "shop.txt"
KEYWORDS_FILE = BASE_DIR / "keywords.txt"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR))

# ------------------------------------------------------------------
# LIMITS
# ------------------------------------------------------------------
MAX_FILE_BYTES = 30 * 1024 * 1024          # 30 MB cap
AVG_BYTES_PER_DORK = 80                    # estimate per line
MAX_DORKS = MAX_FILE_BYTES // AVG_BYTES_PER_DORK   # ~390k
MAX_SESSIONS = 20                          # keep only N recent sessions

SESSIONS: OrderedDict[str, dict] = OrderedDict()


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def load_wordlist(path: Path) -> list[str]:
    if not path.exists():
        logger.warning(f"Wordlist missing: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def parse_targets(raw: str) -> list[str]:
    raw = (raw or "").strip().lower()
    if raw in ("", "none", "no", "-", "null", "skip"):
        return [""]
    parts = [p.strip().lstrip(".") for p in raw.split(",") if p.strip()]
    return parts if parts else [""]


def generate_full(keywords, inurl_words, keyword_words, targets):
    dorks = []
    for kw in keywords:
        for iu in inurl_words:
            for kww in keyword_words:
                for t in targets:
                    suffix = f" site:.{t}" if t else ""
                    dorks.append(f"inurl:{iu} intext:{kw} {kww}{suffix}")
    return dorks


def generate_sampled(keywords, inurl_words, keyword_words, targets, sample_size):
    seen = set()
    dorks = []
    attempts = 0
    max_attempts = sample_size * 5

    while len(dorks) < sample_size and attempts < max_attempts:
        attempts += 1
        kw = random.choice(keywords)
        iu = random.choice(inurl_words)
        kww = random.choice(keyword_words)
        t = random.choice(targets)
        suffix = f" site:.{t}" if t else ""
        line = f"inurl:{iu} intext:{kw} {kww}{suffix}"
        if line in seen:
            continue
        seen.add(line)
        dorks.append(line)

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
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        raise HTTPException(400, "No valid keywords provided.")

    inurl_words = load_wordlist(INURL_FILE)
    keyword_words = load_wordlist(KEYWORDS_FILE)

    if not inurl_words:
        raise HTTPException(500, "shop.txt is missing or empty.")
    if not keyword_words:
        raise HTTPException(500, "keywords.txt is missing or empty.")

    target_list = parse_targets(targets)

    total_possible = (
        len(kw_list) * len(inurl_words) * len(keyword_words) * len(target_list)
    )

    sampled = total_possible > MAX_DORKS

    if sampled:
        dorks = generate_sampled(
            kw_list, inurl_words, keyword_words, target_list, MAX_DORKS
        )
    else:
        dorks = generate_full(kw_list, inurl_words, keyword_words, target_list)

    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {
        "keywords": kw_list,
        "targets": targets or "none",
        "target_list": target_list,
        "dorks": dorks,
        "count": len(dorks),
        "total_possible": total_possible,
        "sampled": sampled,
    }
    SESSIONS.move_to_end(session_id)
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)

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
            "total_possible": total_possible,
            "sampled": sampled,
            "raw_url": raw_url,
            "download_url": download_url,
            "preview": dorks[:15],
        },
    )


@app.api_route(
    "/raw/{session_id}",
    methods=["GET", "HEAD"],
    name="raw_dorks",
)
async def raw_dorks(session_id: str):
    data = SESSIONS.get(session_id)
    if not data:
        raise HTTPException(404, "Session not found or expired.")

    def iter_lines():
        for d in data["dorks"]:
            yield d + "\n"

    return StreamingResponse(iter_lines(), media_type="text/plain")


@app.get("/download/{session_id}", name="download_dorks")
async def download_dorks(session_id: str):
    data = SESSIONS.get(session_id)
    if not data:
        raise HTTPException(404, "Session not found or expired.")

    def iter_lines():
        for d in data["dorks"]:
            yield d + "\n"

    headers = {
        "Content-Disposition": f'attachment; filename="dorks_{session_id}.txt"'
    }
    return StreamingResponse(iter_lines(), media_type="text/plain", headers=headers)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "OK"


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
