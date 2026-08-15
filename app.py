import os
import re
import json
import time
import asyncio
import requests
import numpy as np
import uvicorn
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from langserve import add_routes
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, field_validator, ValidationError
from duckduckgo_search import DDGS
from pypdf import PdfReader

import db
from pdf_report import generate_pdf
# -----------------------------
# 1. FASTAPI APP + RATE LIMITING + SESSIONS
# -----------------------------

app = FastAPI(title="Placement-Ready AI Career Agent API")

# SECRET_KEY signs the login session cookie - set a real random value in Render's
# env vars for production (e.g. `openssl rand -hex 32`). The fallback below is
# only safe for local testing.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---- Google Sign-In (separate from the GOOGLE_API_KEY used for Gemini) ----
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

oauth = OAuth()
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    print("[startup] Google Sign-In enabled", flush=True)
else:
    print("[startup] Google Sign-In NOT configured (GOOGLE_OAUTH_CLIENT_ID/SECRET missing)", flush=True)

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.2)
        print("[startup] Sentry error tracking enabled", flush=True)
    except Exception as e:
        print(f"[startup] Sentry init failed: {e}", flush=True)


@app.on_event("startup")
async def on_startup():
    db.init_db()
    print("[startup] Database initialized", flush=True)


# -----------------------------
# AUTH HELPERS + ROUTES
# -----------------------------

def get_current_user_id(request: Request):
    """Returns the logged-in user's id from the session cookie, or None."""
    return request.session.get("user_id")


def require_login_page(request: Request):
    """For page routes: bounce to /login if not authenticated."""
    user_id = get_current_user_id(request)
    if user_id is None:
        return None
    return user_id


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user_id(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user_id = db.verify_login(username.strip(), password)
    if user_id is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Incorrect username or password."}, status_code=401
        )
    request.session["user_id"] = user_id
    request.session["username"] = username.strip()
    return RedirectResponse("/", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    if get_current_user_id(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    username = username.strip()
    if len(username) < 3:
        error = "Username must be at least 3 characters."
    elif len(password) < 6:
        error = "Password must be at least 6 characters."
    elif password != confirm_password:
        error = "Passwords don't match."
    else:
        user_id = db.create_user(username, password)
        if user_id is None:
            error = "That username is already taken."
        else:
            request.session["user_id"] = user_id
            request.session["username"] = username
            return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(request, "signup.html", {"error": error}, status_code=400)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/auth/google")
async def auth_google(request: Request):
    if "google" not in oauth._clients:
        return HTMLResponse(
            "Google Sign-In isn't configured on this server yet. Use username/password instead.",
            status_code=503
        )
    redirect_uri = request.url_for("auth_google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        email = user_info["email"]
        google_id = user_info["sub"]
    except Exception as e:
        print(f"[google-auth] failed: {e}", flush=True)
        return RedirectResponse("/login", status_code=303)

    user_id = await asyncio.to_thread(db.get_or_create_google_user, email, google_id)
    request.session["user_id"] = user_id
    request.session["username"] = await asyncio.to_thread(db.get_username, user_id)
    return RedirectResponse("/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user_id = require_login_page(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "index.html", {"username": request.session.get("username")})


# -----------------------------
# 2. GEMINI MODELS (chat + embeddings)
# -----------------------------

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY")
ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # read-only fine-grained PAT, public repo access only

GITHUB_API_HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    GITHUB_API_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

llm = None
embeddings_model = None
if GOOGLE_API_KEY:
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY, temperature=0.4)
    except Exception:
        llm = None
    try:
        embeddings_model = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=GOOGLE_API_KEY)
    except Exception:
        embeddings_model = None


# -----------------------------
# 3. SIMPLE IN-MEMORY TTL CACHE (protects GitHub/Adzuna rate limits)
# -----------------------------

_cache = {}
CACHE_TTL_SECONDS = 600  # 10 minutes


def cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def cache_set(key, value):
    _cache[key] = (time.time(), value)


# -----------------------------
# 4. RULE-BASED FALLBACKS (used only if Gemini is unavailable/times out)
# -----------------------------

ROLE_SKILLS = {
    "java developer": ["Java", "Spring Boot", "REST API", "MySQL", "Git"],
    "full stack developer": ["React", "Node.js", "MongoDB", "Express", "Docker"],
    "ai engineer": ["Python", "Machine Learning", "TensorFlow", "SQL", "LangChain"]
}

ROLE_PROJECTS = {
    "java developer": ["Banking Management System (Spring Boot)", "Employee Portal API", "Library Management System"],
    "full stack developer": ["Job Portal MERN App", "AI Resume Analyzer", "Placement Tracker Dashboard"],
    "ai engineer": ["Career Agent using LangChain", "Document Q&A System", "AI Interview Assistant"]
}


def _rule_based_ats(resume_text: str, role: str) -> dict:
    skills = [s.lower() for s in ROLE_SKILLS.get(role.lower(), [])]
    lower_resume = resume_text.lower()
    score, found = 60, []
    for skill in skills:
        if skill in lower_resume:
            score += 8
            found.append(skill)
    return {"ats_score": min(score, 100), "ats_feedback": "Keyword-matching estimate.", "extracted_skills": found}


def _rule_based_gap(resume_text: str, role: str) -> list:
    required = ROLE_SKILLS.get(role.lower(), [])
    lower_resume = resume_text.lower()
    return [s for s in required if s.lower() not in lower_resume]


def _rule_based_projects(role: str) -> list:
    return ROLE_PROJECTS.get(role.lower(), [])


def _fallback_roadmap(role: str, missing_skills: list) -> list:
    focus_skill = missing_skills[0] if missing_skills else role
    return [
        {"week": "Week 1", "focus": "Foundations", "tasks": f"Strengthen fundamentals relevant to {role} and clean up your GitHub profile."},
        {"week": "Week 2", "focus": "Build", "tasks": f"Build and deploy a project that demonstrates {focus_skill}."},
        {"week": "Week 3", "focus": "Practice", "tasks": "Practice data structures, algorithms, and system design basics daily."},
        {"week": "Week 4", "focus": "Apply", "tasks": "Run mock interviews, refine your resume, and start applying."}
    ]


# -----------------------------
# 5. GITHUB EVALUATION - real repo/language/activity data
# -----------------------------

def _github_check_sync(username: str) -> dict:
    empty = {
        "username": username, "found": False, "github_score": 0,
        "public_repositories": 0, "followers": 0, "top_languages": [],
        "active_recently": False, "notable_repos": [],
        "recommendations": [f"GitHub user '{username}' not found."]
    }
    try:
        profile = requests.get(
            f"https://api.github.com/users/{username}", headers=GITHUB_API_HEADERS, timeout=5
        ).json()
        if "login" not in profile:
            return empty

        repos_resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            params={"sort": "updated", "per_page": 30},
            headers=GITHUB_API_HEADERS, timeout=5
        )
        raw_repos = repos_resp.json() if repos_resp.status_code == 200 else []
        if not isinstance(raw_repos, list):
            raw_repos = []

        # Strip forks entirely before any analysis - forked repos aren't the
        # candidate's own work and would inflate language/activity signals.
        original_repos = [r for r in raw_repos if not r.get("fork")]
        # API already returns repos sorted by most-recently-updated; slicing to the
        # top 10 keeps latency and prompt size predictable for large profiles.
        top_repos = original_repos[:10]

        lang_counts, notable_repos, most_recent_push = {}, [], None
        for r in top_repos:
            lang = r.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
            pushed_at = r.get("pushed_at")
            if pushed_at:
                pushed_dt = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if most_recent_push is None or pushed_dt > most_recent_push:
                    most_recent_push = pushed_dt
            if r.get("stargazers_count", 0) > 0 or r.get("description"):
                notable_repos.append({
                    "name": r.get("name"), "language": lang,
                    "stars": r.get("stargazers_count", 0),
                    "description": (r.get("description") or "")[:120]
                })

        notable_repos = sorted(notable_repos, key=lambda x: x["stars"], reverse=True)[:5]
        top_languages = sorted(lang_counts, key=lang_counts.get, reverse=True)[:5]
        active_recently = bool(most_recent_push and (datetime.now(timezone.utc) - most_recent_push).days <= 180)

        repos_count = profile.get("public_repos", 0)
        followers = profile.get("followers", 0)

        score = min(40, repos_count * 3) + min(20, len(top_languages) * 5) + (20 if active_recently else 0) + min(20, followers)
        score = min(100, score)

        recs = []
        if repos_count < 5:
            recs.append("Push more public repositories - aim for at least 5-6 solid projects.")
        if not active_recently:
            recs.append("No commits in the last 6 months - recent activity signals active development to recruiters.")
        if not any(r.get("description") for r in notable_repos):
            recs.append("Add clear README descriptions to your top repositories.")
        if len(top_languages) <= 1:
            recs.append("Diversify the tech stack shown across your repos to match the role you're targeting.")
        if not recs:
            recs.append("Solid GitHub activity - keep pinning your best 3-4 projects on your profile.")

        return {
            "username": username, "found": True, "github_score": score,
            "public_repositories": repos_count, "followers": followers,
            "top_languages": top_languages, "active_recently": active_recently,
            "notable_repos": notable_repos, "recommendations": recs
        }
    except Exception:
        return empty


# -----------------------------
# 6. JOB SEARCH - Adzuna (real, structured, includes descriptions for ATS matching)
# -----------------------------

def _search_jobs_adzuna(role: str) -> list:
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        raise RuntimeError("Adzuna not configured")

    url = f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/1"
    params = {
        "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
        "what": role, "results_per_page": 6, "content-type": "application/json"
    }
    resp = requests.get(url, params=params, timeout=6)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for r in data.get("results", []):
        company = (r.get("company") or {}).get("display_name", "")
        location = (r.get("location") or {}).get("display_name", "")
        jobs.append({
            "title": r.get("title", "N/A"), "company": company, "location": location,
            "url": r.get("redirect_url", ""), "description": r.get("description", "")
        })
    if not jobs:
        raise RuntimeError("No Adzuna results")
    return jobs


def _search_jobs_ddg(role: str) -> list:
    with DDGS(timeout=5) as ddgs:
        results = list(ddgs.text(f"{role} jobs India", max_results=6))
    return [{"title": r.get("title", "N/A"), "company": "", "location": "", "url": r.get("href", ""), "description": ""}
            for r in results]


def _search_jobs_sync(role: str) -> list:
    fallback = [
        {"title": "TCS Java Developer", "company": "TCS", "location": "India", "url": "", "description": ""},
        {"title": "Infosys Software Engineer", "company": "Infosys", "location": "India", "url": "", "description": ""},
    ]
    try:
        return _search_jobs_adzuna(role)
    except Exception:
        pass
    try:
        jobs = _search_jobs_ddg(role)
        return jobs if jobs else fallback
    except Exception:
        return fallback


# -----------------------------
# 7. LANGCHAIN TOOLS (agent-facing wrappers)
# -----------------------------

@tool
def analyze_resume(resume_text: str, role: str) -> str:
    """Analyze a resume and provide ATS score and extracted skills."""
    return json.dumps(_rule_based_ats(resume_text, role), indent=2)


@tool
def skill_gap(role: str, resume_text: str) -> str:
    """Identify missing skills for the target role."""
    return json.dumps({"target_role": role, "missing_skills": _rule_based_gap(resume_text, role)}, indent=2)


@tool
def recommend_projects(role: str) -> str:
    """Recommend placement-ready projects for the target role."""
    return json.dumps({"role": role, "recommended_projects": _rule_based_projects(role)}, indent=2)


@tool
def github_check(username: str) -> str:
    """Analyze a GitHub profile using the GitHub public API - real repo/language/activity data."""
    return json.dumps(_github_check_sync(username), indent=2)


@tool
def search_jobs(role: str) -> str:
    """Search current, real job openings for a target role via Adzuna (falls back to web search)."""
    return json.dumps(_search_jobs_sync(role), indent=2)


tools = [analyze_resume, skill_gap, search_jobs, github_check, recommend_projects]


# -----------------------------
# 8. REAL ATS SCORING VIA EMBEDDINGS
# -----------------------------

def _cosine_similarity(a, b) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def _embedding_ats_score_sync(resume_text: str, job_descriptions: list) -> dict:
    if embeddings_model is None:
        raise RuntimeError("Embeddings not configured")
    descriptions = [d for d in job_descriptions if d and len(d.strip()) > 30][:5]
    if not descriptions:
        raise RuntimeError("No real job descriptions available to match against")

    resume_vec = embeddings_model.embed_query(resume_text[:8000])
    sims = [_cosine_similarity(resume_vec, embeddings_model.embed_query(d[:4000])) for d in descriptions]
    avg_sim = sum(sims) / len(sims)

    # Cosine similarity for related professional text typically falls ~0.3-0.85;
    # rescale that practical range to a readable 0-100 score.
    score = max(0, min(100, round((avg_sim - 0.30) / (0.85 - 0.30) * 100)))
    return {"ats_score": score, "raw_similarity": round(avg_sim, 3), "matched_postings": len(descriptions)}


# -----------------------------
# 9. GEMINI-POWERED QUALITATIVE ANALYSIS (feedback, gaps, projects, roadmap)
# -----------------------------

class RoadmapWeek(BaseModel):
    week: str = Field(description="e.g. 'Week 1'")
    focus: str = Field(description="short title for the week's theme")
    tasks: str = Field(description="1-2 sentence concrete plan for that week")


class ResumeAnalysis(BaseModel):
    """Structured, schema-validated contract for the LLM's resume analysis.
    Using this instead of free-text + regex means a malformed model response
    fails validation cleanly (caught by _safe_llm) instead of causing a
    downstream KeyError when a field is missing or misnamed."""
    ats_feedback: str = Field(description="1-2 sentences on resume quality/fit for this role")
    missing_skills: list[str] = Field(description="3 to 6 specific skills missing from this resume for this role")
    strengths: list[str] = Field(description="2 to 3 specific strengths actually present in this resume")
    recommended_projects: list[str] = Field(description="3 project ideas tailored to the gaps identified")
    github_recommendations: list[str] = Field(description="3 to 4 recommendations referencing the candidate's real GitHub stats")
    roadmap: list[RoadmapWeek] = Field(description="Exactly 4 weeks, one per list item")


structured_llm = llm.with_structured_output(ResumeAnalysis) if llm is not None else None


def _llm_analyze_sync(resume_text: str, role: str, github_stats: dict) -> dict:
    if structured_llm is None:
        raise RuntimeError("LLM not configured")

    truncated_resume = resume_text[:6000]
    github_context = {
        "found": github_stats.get("found", False),
        "public_repos": github_stats.get("public_repositories", 0),
        "followers": github_stats.get("followers", 0),
        "top_languages": github_stats.get("top_languages", []),
        "active_recently": github_stats.get("active_recently", False),
        "notable_repos": github_stats.get("notable_repos", [])
    }

    prompt = f"""You are an expert technical placement coach.

Target role: {role}

Resume text:
\"\"\"{truncated_resume}\"\"\"

Candidate's REAL GitHub data (top 10 non-fork repos): {json.dumps(github_context)}

Analyze this specific resume against the role, cross-referencing the candidate's actual
GitHub activity. Be specific to this resume, role, and GitHub data - avoid generic filler
advice, and do not recommend projects that duplicate what's already on their GitHub."""

    # with_structured_output makes Gemini return data conforming to the ResumeAnalysis
    # schema directly - no manual JSON-fence stripping, no risk of a stray KeyError from
    # a missing key downstream.
    result: ResumeAnalysis = structured_llm.invoke(prompt)
    return result.model_dump()


# -----------------------------
# 10. SAFE ASYNC WRAPPERS (timeouts + caching)
# -----------------------------

async def _safe_github(username: str) -> dict:
    cache_key = f"gh:{username.lower()}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_github_check_sync, username), timeout=6)
        cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"[github] failed/timed out: {e}", flush=True)
        return {"username": username, "found": False, "github_score": 0, "public_repositories": 0,
                "followers": 0, "top_languages": [], "active_recently": False, "notable_repos": [],
                "recommendations": ["GitHub check timed out."]}


async def _safe_jobs(role: str) -> list:
    cache_key = f"jobs:{role.lower()}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_search_jobs_sync, role), timeout=8)
        cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"[jobs] failed/timed out: {e}", flush=True)
        return [{"title": "Job search timed out - try again", "company": "", "location": "", "url": "", "description": ""}]


async def _safe_llm(resume_text: str, role: str, github_stats: dict):
    try:
        return await asyncio.wait_for(asyncio.to_thread(_llm_analyze_sync, resume_text, role, github_stats), timeout=15)
    except Exception as e:
        print(f"[llm] failed/timed out: {type(e).__name__}: {e}", flush=True)
        return None


async def _safe_embedding_ats(resume_text: str, job_descriptions: list):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_embedding_ats_score_sync, resume_text, job_descriptions), timeout=12
        )
    except Exception as e:
        print(f"[embeddings] failed/unavailable: {type(e).__name__}: {e}", flush=True)
        return None


# -----------------------------
# 11. /analyze ENDPOINT
# -----------------------------

class AnalyzeForm(BaseModel):
    """Class-based Pydantic schema for the multipart form fields. Validating here
    means bad input is rejected with a clean 422 before it reaches any external API."""
    role: str
    github: str

    @classmethod
    def as_form(cls, role: str = Form(...), github: str = Form(...)):
        try:
            return cls(role=role.strip(), github=github.strip())
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors())

    @field_validator("role")
    @classmethod
    def role_is_reasonable_text(cls, v):
        if not (2 <= len(v) <= 60):
            raise ValueError("role must be between 2 and 60 characters")
        if not re.fullmatch(r"[A-Za-z0-9 /+\-.,&()]+", v):
            raise ValueError("role contains characters that aren't allowed")
        return v

    @field_validator("github")
    @classmethod
    def github_username_format(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", v):
            raise ValueError("not a valid GitHub username")
        return v


@app.post("/analyze")
@limiter.limit("5/minute")
async def analyze(
    request: Request,
    form: AnalyzeForm = Depends(AnalyzeForm.as_form),
    resume: UploadFile = File(...)
):
    user_id = get_current_user_id(request)
    if user_id is None:
        return JSONResponse(status_code=401, content={"success": False, "error": "Please log in first."})

    role, github = form.role, form.github
    try:
        print(f"[analyze] START role={role} github={github}", flush=True)

        pdf_bytes = await resume.read()
        reader = PdfReader(BytesIO(pdf_bytes))
        resume_text = "".join(page.extract_text() or "" for page in reader.pages)

        if not resume_text.strip():
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "Couldn't extract text from that PDF - it may be a scanned image."
            })

        rule_ats = _rule_based_ats(resume_text, role)
        rule_gap = _rule_based_gap(resume_text, role)
        rule_projects = _rule_based_projects(role)

        github_result = await _safe_github(github)
        llm_result, jobs_result = await asyncio.gather(
            _safe_llm(resume_text, role, github_result),
            _safe_jobs(role)
        )

        job_descriptions = [j.get("description", "") for j in jobs_result]
        embedding_result = await _safe_embedding_ats(resume_text, job_descriptions)

        # Score: prefer the mathematically computed embedding score, then LLM estimate, then keyword rule
        if embedding_result:
            ats_score = embedding_result["ats_score"]
            ats_score_method = f"Embedding similarity vs {embedding_result['matched_postings']} live job postings"
        elif llm_result:
            ats_score = rule_ats["ats_score"]  # LLM no longer scores directly; keep keyword score as numeric fallback
            ats_score_method = "Keyword-based estimate (embeddings unavailable)"
        else:
            ats_score = rule_ats["ats_score"]
            ats_score_method = "Keyword-based estimate (AI unavailable)"

        if llm_result:
            ats_feedback = llm_result.get("ats_feedback", "")
            missing_skills = llm_result.get("missing_skills") or rule_gap
            recommended_projects = llm_result.get("recommended_projects") or rule_projects
            roadmap = llm_result.get("roadmap") or _fallback_roadmap(role, missing_skills)
            github_recommendations = llm_result.get("github_recommendations") or github_result.get("recommendations", [])
        else:
            ats_feedback = rule_ats["ats_feedback"]
            missing_skills = rule_gap
            recommended_projects = rule_projects
            roadmap = _fallback_roadmap(role, missing_skills)
            github_recommendations = github_result.get("recommendations", [])

        github_score = github_result.get("github_score", 0)
        placement_readiness = round(ats_score * 0.6 + github_score * 0.4)

        payload = {
            "success": True,
            "ats_score": ats_score,
            "ats_score_method": ats_score_method,
            "ats_feedback": ats_feedback,
            "placement_readiness": placement_readiness,
            "github_score": github_score,
            "github_public_repos": github_result.get("public_repositories", 0),
            "github_followers": github_result.get("followers", 0),
            "github_top_languages": github_result.get("top_languages", []),
            "missing_skills": missing_skills,
            "github_recommendations": github_recommendations,
            "projects": recommended_projects,
            "roadmap": roadmap,
            "jobs": [{k: v for k, v in j.items() if k != "description"} for j in jobs_result],
            "role": role,
            "github_username": github
        }

        try:
            result_id = await asyncio.to_thread(
                db.save_analysis, user_id, role, github, ats_score, ats_score_method,
                github_score, placement_readiness, json.dumps(payload)
            )
        except Exception as e:
            print(f"[db] save failed: {e}", flush=True)
            return JSONResponse(status_code=500, content={
                "success": False, "error": "Analysis succeeded but couldn't be saved. Please try again."
            })

        # The frontend redirects to this URL to show the dedicated results page.
        return {"success": True, "redirect": f"/result/{result_id}"}

    except Exception as e:
        print(f"[analyze] ERROR: {type(e).__name__}: {e}", flush=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/result/{result_id}/pdf")
async def download_result_pdf(request: Request, result_id: int):
    user_id = get_current_user_id(request)

    if user_id is None:
        return RedirectResponse("/login", status_code=303)

    row = await asyncio.to_thread(
        db.get_analysis,
        result_id
    )

    if row is None or row["user_id"] != user_id:
        return HTMLResponse(
            "Result not found.",
            status_code=404
        )

    try:
        result = json.loads(row["result_json"])

        pdf_bytes = await asyncio.to_thread(
            generate_pdf,
            result,
            request.session.get("username", ""),
            row["created_at"],
        )

        role = result.get(
            "role",
            "career-report"
        )

        # Make a safe filename
        safe_role = re.sub(
            r"[^A-Za-z0-9]+",
            "-",
            str(role)
        ).strip("-").lower()

        filename = (
            f"placement-report-{safe_role or 'career'}-{result_id}.pdf"
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except Exception as e:
        print(
            f"[pdf] ERROR: {type(e).__name__}: {e}",
            flush=True,
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Could not generate the PDF."
            },
        )


@app.get("/history")
async def history(request: Request, limit: int = 10):
    user_id = get_current_user_id(request)
    if user_id is None:
        return JSONResponse(status_code=401, content={"success": False, "error": "Please log in first."})
    try:
        rows = await asyncio.to_thread(db.get_history, user_id, limit)
        return {"success": True, "history": rows}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# -----------------------------
# 12. AGENT / LANGSERVE (optional playground, not used by the frontend)
# -----------------------------

agent = None
formatted_agent_chain = None

if llm is not None:
    try:
        agent = create_agent(
            model=llm, tools=tools,
            system_prompt=(
                "You are a Placement-Ready AI Career Agent. Help students prepare for placements "
                "by analyzing resumes, identifying skill gaps, evaluating GitHub profiles, "
                "recommending projects, and suggesting job opportunities."
            )
        )

        class AgentInput(BaseModel):
            input: str = Field(description="Career-related query for the agent")

        def format_for_agent(x):
            user_input = x["input"] if isinstance(x, dict) else x.input
            return {"messages": [("user", user_input)]}

        def extract_text_response(agent_output: dict) -> str:
            if not isinstance(agent_output, dict):
                return str(agent_output)
            messages = agent_output.get("messages")
            if messages is None:
                for value in agent_output.values():
                    if isinstance(value, dict) and "messages" in value:
                        messages = value["messages"]
                        break
            if messages:
                last = messages[-1]
                return getattr(last, "content", str(last))
            return str(agent_output)

        formatted_agent_chain = (
            RunnableLambda(format_for_agent) | agent | RunnableLambda(extract_text_response)
        ).with_types(input_type=AgentInput, output_type=str)

        add_routes(app, formatted_agent_chain, path="/career-agent", playground_type="default")
    except Exception:
        pass

# -----------------------------
# 13. MAIN
# -----------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
