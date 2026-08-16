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

from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    Depends,
    HTTPException,
)

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
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    ValidationError,
)

from duckduckgo_search import DDGS
from pypdf import PdfReader

import db
from pdf_report import generate_pdf


# ============================================================
# 1. FASTAPI APP
# ============================================================

app = FastAPI(
    title="Placement-Ready AI Career Agent API"
)


# ============================================================
# 2. SESSION
# ============================================================

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-only-insecure-secret-change-me"
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
)


# ============================================================
# 3. RATE LIMITING
# ============================================================

limiter = Limiter(
    key_func=get_remote_address
)

app.state.limiter = limiter

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler
)


# ============================================================
# 4. GOOGLE SIGN-IN
# ============================================================

GOOGLE_OAUTH_CLIENT_ID = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_ID"
)

GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_SECRET"
)

oauth = OAuth()


if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:

    oauth.register(
        name="google",

        client_id=GOOGLE_OAUTH_CLIENT_ID,

        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,

        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),

        client_kwargs={
            "scope": "openid email profile"
        },
    )

    print(
        "[startup] Google Sign-In enabled",
        flush=True
    )

else:

    print(
        "[startup] Google Sign-In NOT configured",
        flush=True
    )


# ============================================================
# 5. PATHS / TEMPLATES / STATIC
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(
        directory=str(BASE_DIR / "static")
    ),
    name="static",
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# ============================================================
# 6. OPTIONAL SENTRY
# ============================================================

SENTRY_DSN = os.environ.get("SENTRY_DSN")

if SENTRY_DSN:

    try:

        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.2,
        )

        print(
            "[startup] Sentry enabled",
            flush=True
        )

    except Exception as e:

        print(
            f"[startup] Sentry init failed: {e}",
            flush=True
        )


# ============================================================
# 7. DATABASE STARTUP
# ============================================================

@app.on_event("startup")
async def on_startup():

    db.init_db()

    print(
        "[startup] Database initialized",
        flush=True
    )


# ============================================================
# 8. AUTH HELPERS
# ============================================================

def get_current_user_id(request: Request):

    return request.session.get("user_id")


def require_login_page(request: Request):

    user_id = get_current_user_id(request)

    if user_id is None:
        return None

    return user_id


# ============================================================
# 9. NORMAL LOGIN
# ============================================================

@app.get(
    "/login",
    response_class=HTMLResponse
)
async def login_page(request: Request):

    if get_current_user_id(request):

        return RedirectResponse(
            "/",
            status_code=303
        )

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None
        }
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):

    user_id = db.verify_login(
        username.strip(),
        password
    )

    if user_id is None:

        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error":
                    "Incorrect username or password."
            },
            status_code=401,
        )

    request.session["user_id"] = user_id

    request.session["username"] = (
        username.strip()
    )

    return RedirectResponse(
        "/",
        status_code=303
    )


# ============================================================
# 10. SIGNUP
# ============================================================

@app.get(
    "/signup",
    response_class=HTMLResponse
)
async def signup_page(request: Request):

    if get_current_user_id(request):

        return RedirectResponse(
            "/",
            status_code=303
        )

    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "error": None
        }
    )


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):

    username = username.strip()

    error = None

    if len(username) < 3:

        error = (
            "Username must be at least "
            "3 characters."
        )

    elif len(password) < 6:

        error = (
            "Password must be at least "
            "6 characters."
        )

    elif password != confirm_password:

        error = "Passwords don't match."

    else:

        user_id = db.create_user(
            username,
            password
        )

        if user_id is None:

            error = (
                "That username is already taken."
            )

        else:

            request.session["user_id"] = user_id

            request.session["username"] = (
                username
            )

            return RedirectResponse(
                "/",
                status_code=303
            )

    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "error": error
        },
        status_code=400,
    )


# ============================================================
# 11. LOGOUT
# ============================================================

@app.get("/logout")
async def logout(request: Request):

    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303
    )


# ============================================================
# 12. GOOGLE LOGIN
# ============================================================

@app.get("/auth/google")
async def auth_google(request: Request):

    if "google" not in oauth._clients:

        return HTMLResponse(
            """
            <h2>Google Sign-In is not configured.</h2>
            <p>Please check GOOGLE_OAUTH_CLIENT_ID and
            GOOGLE_OAUTH_CLIENT_SECRET in Render.</p>
            """,
            status_code=503,
        )

    redirect_uri = request.url_for(
        "auth_google_callback"
    )

    return await oauth.google.authorize_redirect(
        request,
        redirect_uri
    )


@app.get(
    "/auth/google/callback",
    name="auth_google_callback"
)
async def auth_google_callback(
    request: Request
):

    try:

        token = await (
            oauth.google
            .authorize_access_token(request)
        )

        user_info = token.get("userinfo")

        if not user_info:

            raise RuntimeError(
                "Google did not return user information."
            )

        email = user_info.get("email")

        google_id = user_info.get("sub")

        if not email or not google_id:

            raise RuntimeError(
                "Google account information is incomplete."
            )

        print(
            f"[google-auth] Google login for {email}",
            flush=True
        )

    except Exception as e:

        print(
            f"[google-auth] failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return HTMLResponse(
            f"""
            <h2>Google Sign-In failed</h2>
            <p>{str(e)}</p>
            <p>
                <a href="/login">
                    Return to login
                </a>
            </p>
            """,
            status_code=500,
        )

    try:

        user_id = await asyncio.to_thread(
            db.get_or_create_google_user,
            email,
            google_id,
        )

        username = await asyncio.to_thread(
            db.get_username,
            user_id,
        )

        request.session["user_id"] = user_id

        request.session["username"] = (
            username or email
        )

        return RedirectResponse(
            "/",
            status_code=303
        )

    except Exception as e:

        print(
            f"[google-auth] database error: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return HTMLResponse(
            """
            <h2>Google login could not be completed.</h2>
            <p>There was a database error.</p>
            <p>
                Please check the Render logs.
            </p>
            <a href="/login">
                Return to login
            </a>
            """,
            status_code=500,
        )


# ============================================================
# 13. HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def home(request: Request):

    user_id = require_login_page(request)

    if user_id is None:

        return RedirectResponse(
            "/login",
            status_code=303
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "username":
                request.session.get("username")
        }
    )


# ============================================================
# 14. ENVIRONMENT VARIABLES
# ============================================================

GOOGLE_API_KEY = os.environ.get(
    "GOOGLE_API_KEY"
)

ADZUNA_APP_ID = os.environ.get(
    "ADZUNA_APP_ID"
)

ADZUNA_APP_KEY = os.environ.get(
    "ADZUNA_APP_KEY"
)

ADZUNA_COUNTRY = os.environ.get(
    "ADZUNA_COUNTRY",
    "in"
)

GITHUB_TOKEN = os.environ.get(
    "GITHUB_TOKEN"
)


# ============================================================
# 15. GITHUB HEADERS
# ============================================================

GITHUB_API_HEADERS = {
    "Accept":
        "application/vnd.github+json"
}

if GITHUB_TOKEN:

    GITHUB_API_HEADERS[
        "Authorization"
    ] = f"Bearer {GITHUB_TOKEN}"


# ============================================================
# 16. GEMINI
# ============================================================

llm = None
embeddings_model = None

if GOOGLE_API_KEY:

    try:

        # IMPORTANT:
        # gemini-2.0-flash was shut down.
        # Use a current stable Gemini model.

        llm = ChatGoogleGenerativeAI(
            model="gemini-3.5-flash",
            google_api_key=GOOGLE_API_KEY,
        )

        print(
            "[startup] Gemini 3.5 Flash enabled",
            flush=True
        )

    except Exception as e:

        print(
            f"[startup] Gemini initialization failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        llm = None

    try:

        embeddings_model = (
            GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=GOOGLE_API_KEY,
            )
        )

        print(
            "[startup] Gemini embeddings enabled",
            flush=True
        )

    except Exception as e:

        print(
            f"[startup] Embeddings initialization failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        embeddings_model = None

else:

    print(
        "[startup] GOOGLE_API_KEY is missing",
        flush=True
    )


# ============================================================
# 17. CACHE
# ============================================================

_cache = {}

CACHE_TTL_SECONDS = 600


def cache_get(key):

    entry = _cache.get(key)

    if entry:

        if (
            time.time() - entry[0]
        ) < CACHE_TTL_SECONDS:

            return entry[1]

    return None


def cache_set(key, value):

    _cache[key] = (
        time.time(),
        value
    )


# ============================================================
# 18. RULE BASED FALLBACKS
# ============================================================

ROLE_SKILLS = {

    "java developer": [
        "Java",
        "Spring Boot",
        "REST API",
        "MySQL",
        "Git",
    ],

    "full stack developer": [
        "React",
        "Node.js",
        "MongoDB",
        "Express",
        "Docker",
    ],

    "ai engineer": [
        "Python",
        "Machine Learning",
        "TensorFlow",
        "SQL",
        "LangChain",
    ],
}


ROLE_PROJECTS = {

    "java developer": [
        "Banking Management System (Spring Boot)",
        "Employee Portal API",
        "Library Management System",
    ],

    "full stack developer": [
        "Job Portal MERN App",
        "AI Resume Analyzer",
        "Placement Tracker Dashboard",
    ],

    "ai engineer": [
        "Career Agent using LangChain",
        "Document Q&A System",
        "AI Interview Assistant",
    ],
}


def _rule_based_ats(
    resume_text: str,
    role: str
):

    skills = [
        s.lower()
        for s in ROLE_SKILLS.get(
            role.lower(),
            []
        )
    ]

    lower_resume = resume_text.lower()

    score = 60

    found = []

    for skill in skills:

        if skill in lower_resume:

            score += 8

            found.append(skill)

    return {
        "ats_score":
            min(score, 100),

        "ats_feedback":
            "Keyword-matching estimate.",

        "extracted_skills":
            found,
    }


def _rule_based_gap(
    resume_text: str,
    role: str
):

    required = ROLE_SKILLS.get(
        role.lower(),
        []
    )

    lower_resume = resume_text.lower()

    return [
        s
        for s in required
        if s.lower() not in lower_resume
    ]


def _rule_based_projects(role: str):

    return ROLE_PROJECTS.get(
        role.lower(),
        []
    )


def _fallback_roadmap(
    role: str,
    missing_skills: list
):

    focus_skill = (
        missing_skills[0]
        if missing_skills
        else role
    )

    return [

        {
            "week": "Week 1",
            "focus": "Foundations",
            "tasks":
                f"Strengthen fundamentals "
                f"relevant to {role} and clean "
                f"up your GitHub profile.",
        },

        {
            "week": "Week 2",
            "focus": "Build",
            "tasks":
                f"Build and deploy a project "
                f"that demonstrates "
                f"{focus_skill}.",
        },

        {
            "week": "Week 3",
            "focus": "Practice",
            "tasks":
                "Practice data structures, "
                "algorithms, and system design "
                "basics daily.",
        },

        {
            "week": "Week 4",
            "focus": "Apply",
            "tasks":
                "Run mock interviews, refine "
                "your resume, and start "
                "applying.",
        },
    ]


# ============================================================
# 19. GITHUB
# ============================================================

def _github_check_sync(
    username: str
):

    empty = {

        "username": username,

        "found": False,

        "github_score": 0,

        "public_repositories": 0,

        "followers": 0,

        "top_languages": [],

        "active_recently": False,

        "notable_repos": [],

        "recommendations": [
            f"GitHub user '{username}' not found."
        ],
    }

    try:

        profile_response = requests.get(
            f"https://api.github.com/users/{username}",
            headers=GITHUB_API_HEADERS,
            timeout=5,
        )

        profile = profile_response.json()

        if "login" not in profile:

            return empty

        repos_response = requests.get(
            f"https://api.github.com/users/{username}/repos",
            params={
                "sort": "updated",
                "per_page": 30,
            },
            headers=GITHUB_API_HEADERS,
            timeout=5,
        )

        raw_repos = (
            repos_response.json()
            if repos_response.status_code == 200
            else []
        )

        if not isinstance(
            raw_repos,
            list
        ):

            raw_repos = []

        original_repos = [
            r
            for r in raw_repos
            if not r.get("fork")
        ]

        top_repos = original_repos[:10]

        lang_counts = {}

        notable_repos = []

        most_recent_push = None

        for repo in top_repos:

            language = repo.get(
                "language"
            )

            if language:

                lang_counts[
                    language
                ] = (
                    lang_counts.get(
                        language,
                        0
                    ) + 1
                )

            pushed_at = repo.get(
                "pushed_at"
            )

            if pushed_at:

                pushed_dt = (
                    datetime.strptime(
                        pushed_at,
                        "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(
                        tzinfo=timezone.utc
                    )
                )

                if (
                    most_recent_push
                    is None
                    or pushed_dt
                    > most_recent_push
                ):

                    most_recent_push = (
                        pushed_dt
                    )

            if (
                repo.get(
                    "stargazers_count",
                    0
                ) > 0
                or repo.get("description")
            ):

                notable_repos.append({

                    "name":
                        repo.get("name"),

                    "language":
                        language,

                    "stars":
                        repo.get(
                            "stargazers_count",
                            0
                        ),

                    "description":
                        (
                            repo.get(
                                "description"
                            )
                            or ""
                        )[:120],
                })

        notable_repos = sorted(
            notable_repos,
            key=lambda x: x["stars"],
            reverse=True,
        )[:5]

        top_languages = sorted(
            lang_counts,
            key=lang_counts.get,
            reverse=True,
        )[:5]

        active_recently = bool(
            most_recent_push
            and (
                datetime.now(timezone.utc)
                - most_recent_push
            ).days <= 180
        )

        repos_count = profile.get(
            "public_repos",
            0
        )

        followers = profile.get(
            "followers",
            0
        )

        score = (
            min(
                40,
                repos_count * 3
            )
            + min(
                20,
                len(top_languages) * 5
            )
            + (
                20
                if active_recently
                else 0
            )
            + min(
                20,
                followers
            )
        )

        score = min(
            100,
            score
        )

        recommendations = []

        if repos_count < 5:

            recommendations.append(
                "Push more public repositories "
                "- aim for at least 5-6 solid projects."
            )

        if not active_recently:

            recommendations.append(
                "No commits in the last 6 months "
                "- recent activity signals active "
                "development to recruiters."
            )

        if not any(
            r.get("description")
            for r in notable_repos
        ):

            recommendations.append(
                "Add clear README descriptions "
                "to your top repositories."
            )

        if len(top_languages) <= 1:

            recommendations.append(
                "Diversify the tech stack shown "
                "across your repos to match the "
                "role you're targeting."
            )

        if not recommendations:

            recommendations.append(
                "Solid GitHub activity - keep "
                "pinning your best 3-4 projects."
            )

        return {

            "username":
                username,

            "found":
                True,

            "github_score":
                score,

            "public_repositories":
                repos_count,

            "followers":
                followers,

            "top_languages":
                top_languages,

            "active_recently":
                active_recently,

            "notable_repos":
                notable_repos,

            "recommendations":
                recommendations,
        }

    except Exception as e:

        print(
            f"[github] error: {e}",
            flush=True
        )

        return empty


# ============================================================
# 20. JOB SEARCH
# ============================================================

def _search_jobs_adzuna(
    role: str
):

    if not (
        ADZUNA_APP_ID
        and ADZUNA_APP_KEY
    ):

        raise RuntimeError(
            "Adzuna not configured"
        )

    url = (
        f"https://api.adzuna.com/"
        f"v1/api/jobs/"
        f"{ADZUNA_COUNTRY}/search/1"
    )

    params = {

        "app_id":
            ADZUNA_APP_ID,

        "app_key":
            ADZUNA_APP_KEY,

        "what":
            role,

        "results_per_page":
            6,

        "content-type":
            "application/json",
    }

    response = requests.get(
        url,
        params=params,
        timeout=6,
    )

    response.raise_for_status()

    data = response.json()

    jobs = []

    for result in data.get(
        "results",
        []
    ):

        company = (
            result.get("company")
            or {}
        ).get(
            "display_name",
            ""
        )

        location = (
            result.get("location")
            or {}
        ).get(
            "display_name",
            ""
        )

        jobs.append({

            "title":
                result.get(
                    "title",
                    "N/A"
                ),

            "company":
                company,

            "location":
                location,

            "url":
                result.get(
                    "redirect_url",
                    ""
                ),

            "description":
                result.get(
                    "description",
                    ""
                ),
        })

    if not jobs:

        raise RuntimeError(
            "No Adzuna results"
        )

    return jobs


def _search_jobs_ddg(
    role: str
):

    with DDGS(timeout=5) as ddgs:

        results = list(
            ddgs.text(
                f"{role} jobs India",
                max_results=6
            )
        )

    return [

        {
            "title":
                result.get(
                    "title",
                    "N/A"
                ),

            "company":
                "",

            "location":
                "",

            "url":
                result.get(
                    "href",
                    ""
                ),

            "description":
                "",
        }

        for result in results
    ]


def _search_jobs_sync(
    role: str
):

    fallback = [

        {
            "title":
                "TCS Java Developer",

            "company":
                "TCS",

            "location":
                "India",

            "url":
                "",

            "description":
                "",
        },

        {
            "title":
                "Infosys Software Engineer",

            "company":
                "Infosys",

            "location":
                "India",

            "url":
                "",

            "description":
                "",
        },
    ]

    try:

        return _search_jobs_adzuna(
            role
        )

    except Exception:

        pass

    try:

        jobs = _search_jobs_ddg(
            role
        )

        return jobs if jobs else fallback

    except Exception:

        return fallback


# ============================================================
# 21. LANGCHAIN TOOLS
# ============================================================

@tool
def analyze_resume(
    resume_text: str,
    role: str
) -> str:

    """Analyze a resume."""

    return json.dumps(
        _rule_based_ats(
            resume_text,
            role
        ),
        indent=2
    )


@tool
def skill_gap(
    role: str,
    resume_text: str
) -> str:

    """Identify missing skills."""

    return json.dumps(
        {
            "target_role":
                role,

            "missing_skills":
                _rule_based_gap(
                    resume_text,
                    role
                ),
        },
        indent=2
    )


@tool
def recommend_projects(
    role: str
) -> str:

    """Recommend projects."""

    return json.dumps(
        {
            "role":
                role,

            "recommended_projects":
                _rule_based_projects(
                    role
                ),
        },
        indent=2
    )


@tool
def github_check(
    username: str
) -> str:

    """Analyze GitHub."""

    return json.dumps(
        _github_check_sync(
            username
        ),
        indent=2
    )


@tool
def search_jobs(
    role: str
) -> str:

    """Search jobs."""

    return json.dumps(
        _search_jobs_sync(
            role
        ),
        indent=2
    )


tools = [
    analyze_resume,
    skill_gap,
    search_jobs,
    github_check,
    recommend_projects,
]


# ============================================================
# 22. EMBEDDING ATS
# ============================================================

def _cosine_similarity(
    a,
    b
):

    a = np.array(a)

    b = np.array(b)

    return float(
        np.dot(a, b)
        /
        (
            np.linalg.norm(a)
            *
            np.linalg.norm(b)
            + 1e-8
        )
    )


def _embedding_ats_score_sync(
    resume_text: str,
    job_descriptions: list
):

    if embeddings_model is None:

        raise RuntimeError(
            "Embeddings not configured"
        )

    descriptions = [
        d
        for d in job_descriptions
        if d
        and len(d.strip()) > 30
    ][:5]

    if not descriptions:

        raise RuntimeError(
            "No real job descriptions "
            "available to match against"
        )

    resume_vec = (
        embeddings_model
        .embed_query(
            resume_text[:8000]
        )
    )

    similarities = [

        _cosine_similarity(
            resume_vec,
            embeddings_model.embed_query(
                description[:4000]
            )
        )

        for description in descriptions
    ]

    average_similarity = (
        sum(similarities)
        /
        len(similarities)
    )

    score = max(
        0,
        min(
            100,
            round(
                (
                    average_similarity
                    - 0.30
                )
                /
                (
                    0.85
                    - 0.30
                )
                * 100
            )
        )
    )

    return {

        "ats_score":
            score,

        "raw_similarity":
            round(
                average_similarity,
                3
            ),

        "matched_postings":
            len(descriptions),
    }


# ============================================================
# 23. GEMINI STRUCTURED OUTPUT
# ============================================================

class RoadmapWeek(BaseModel):

    week: str = Field(
        description="Example: Week 1"
    )

    focus: str = Field(
        description="Short title"
    )

    tasks: str = Field(
        description="Concrete plan"
    )


class ResumeAnalysis(BaseModel):

    ats_feedback: str = Field(
        description=
        "1-2 sentences about resume quality"
    )

    missing_skills: list[str] = Field(
        description=
        "3 to 6 missing skills"
    )

    strengths: list[str] = Field(
        description=
        "2 to 3 actual strengths"
    )

    recommended_projects: list[str] = Field(
        description=
        "3 tailored projects"
    )

    github_recommendations: list[str] = Field(
        description=
        "3 to 4 GitHub recommendations"
    )

    roadmap: list[RoadmapWeek] = Field(
        description=
        "Exactly 4 roadmap weeks"
    )


structured_llm = (
    llm.with_structured_output(
        ResumeAnalysis
    )
    if llm is not None
    else None
)


def _llm_analyze_sync(
    resume_text: str,
    role: str,
    github_stats: dict
):

    if structured_llm is None:

        raise RuntimeError(
            "LLM not configured"
        )

    truncated_resume = (
        resume_text[:6000]
    )

    github_context = {

        "found":
            github_stats.get(
                "found",
                False
            ),

        "public_repos":
            github_stats.get(
                "public_repositories",
                0
            ),

        "followers":
            github_stats.get(
                "followers",
                0
            ),

        "top_languages":
            github_stats.get(
                "top_languages",
                []
            ),

        "active_recently":
            github_stats.get(
                "active_recently",
                False
            ),

        "notable_repos":
            github_stats.get(
                "notable_repos",
                []
            ),
    }

    prompt = f"""
You are an expert technical placement coach.

Target role:
{role}

Resume:
\"\"\"
{truncated_resume}
\"\"\"

Candidate's REAL GitHub data:
{json.dumps(github_context)}

Analyze this specific resume against the target role.

Cross-reference the actual GitHub data.

Be specific and practical.

Avoid generic filler.

Do not recommend projects that duplicate
projects already visible on GitHub.

Return exactly four roadmap weeks.
"""

    result = structured_llm.invoke(
        prompt
    )

    return result.model_dump()


# ============================================================
# 24. SAFE WRAPPERS
# ============================================================

async def _safe_github(
    username: str
):

    cache_key = (
        f"gh:{username.lower()}"
    )

    cached = cache_get(
        cache_key
    )

    if cached:

        return cached

    try:

        result = await asyncio.wait_for(
            asyncio.to_thread(
                _github_check_sync,
                username
            ),
            timeout=6
        )

        cache_set(
            cache_key,
            result
        )

        return result

    except Exception as e:

        print(
            f"[github] failed: {e}",
            flush=True
        )

        return {

            "username":
                username,

            "found":
                False,

            "github_score":
                0,

            "public_repositories":
                0,

            "followers":
                0,

            "top_languages":
                [],

            "active_recently":
                False,

            "notable_repos":
                [],

            "recommendations":
                ["GitHub check failed."],
        }


async def _safe_jobs(
    role: str
):

    cache_key = (
        f"jobs:{role.lower()}"
    )

    cached = cache_get(
        cache_key
    )

    if cached:

        return cached

    try:

        result = await asyncio.wait_for(
            asyncio.to_thread(
                _search_jobs_sync,
                role
            ),
            timeout=8
        )

        cache_set(
            cache_key,
            result
        )

        return result

    except Exception as e:

        print(
            f"[jobs] failed: {e}",
            flush=True
        )

        return []


async def _safe_llm(
    resume_text: str,
    role: str,
    github_stats: dict
):

    try:

        return await asyncio.wait_for(

            asyncio.to_thread(
                _llm_analyze_sync,
                resume_text,
                role,
                github_stats
            ),

            timeout=20
        )

    except Exception as e:

        print(
            f"[llm] failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return None


async def _safe_embedding_ats(
    resume_text: str,
    job_descriptions: list
):

    try:

        return await asyncio.wait_for(

            asyncio.to_thread(
                _embedding_ats_score_sync,
                resume_text,
                job_descriptions
            ),

            timeout=12
        )

    except Exception as e:

        print(
            f"[embeddings] failed: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return None


# ============================================================
# 25. ANALYZE FORM
# ============================================================

class AnalyzeForm(BaseModel):

    role: str

    github: str

    @classmethod
    def as_form(
        cls,
        role: str = Form(...),
        github: str = Form(...)
    ):

        try:

            return cls(
                role=role.strip(),
                github=github.strip()
            )

        except ValidationError as e:

            raise HTTPException(
                status_code=422,
                detail=e.errors()
            )

    @field_validator("role")
    @classmethod
    def role_is_reasonable_text(
        cls,
        value
    ):

        if not (
            2 <= len(value) <= 60
        ):

            raise ValueError(
                "role must be between "
                "2 and 60 characters"
            )

        if not re.fullmatch(
            r"[A-Za-z0-9 /+\-.,&()]+",
            value
        ):

            raise ValueError(
                "role contains invalid characters"
            )

        return value

    @field_validator("github")
    @classmethod
    def github_username_format(
        cls,
        value
    ):

        if not re.fullmatch(
            r"[A-Za-z0-9]"
            r"(?:[A-Za-z0-9-]{0,37}"
            r"[A-Za-z0-9])?",
            value
        ):

            raise ValueError(
                "not a valid GitHub username"
            )

        return value


# ============================================================
# 26. ANALYZE ENDPOINT
# ============================================================

@app.post("/analyze")
@limiter.limit("5/minute")
async def analyze(
    request: Request,

    form: AnalyzeForm = Depends(
        AnalyzeForm.as_form
    ),

    resume: UploadFile = File(...)
):

    user_id = get_current_user_id(
        request
    )

    if user_id is None:

        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error":
                    "Please log in first."
            },
        )

    role = form.role

    github = form.github

    try:

        print(
            f"[analyze] START "
            f"role={role} "
            f"github={github}",
            flush=True
        )

        pdf_bytes = await resume.read()

        reader = PdfReader(
            BytesIO(pdf_bytes)
        )

        resume_text = "".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not resume_text.strip():

            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error":
                        "Couldn't extract text "
                        "from that PDF."
                },
            )

        rule_ats = _rule_based_ats(
            resume_text,
            role
        )

        rule_gap = _rule_based_gap(
            resume_text,
            role
        )

        rule_projects = (
            _rule_based_projects(
                role
            )
        )

        github_result = await _safe_github(
            github
        )

        llm_result, jobs_result = (
            await asyncio.gather(

                _safe_llm(
                    resume_text,
                    role,
                    github_result
                ),

                _safe_jobs(
                    role
                ),
            )
        )

        job_descriptions = [
            job.get(
                "description",
                ""
            )
            for job in jobs_result
        ]

        embedding_result = (
            await _safe_embedding_ats(
                resume_text,
                job_descriptions
            )
        )

        # ----------------------------
        # ATS SCORE
        # ----------------------------

        if embedding_result:

            ats_score = (
                embedding_result[
                    "ats_score"
                ]
            )

            ats_score_method = (
                "Embedding similarity vs "
                f"{embedding_result['matched_postings']} "
                "live job postings"
            )

        else:

            ats_score = (
                rule_ats["ats_score"]
            )

            ats_score_method = (
                "Keyword-based estimate "
                "(embeddings unavailable)"
            )

        # ----------------------------
        # AI CONTENT
        # ----------------------------

        if llm_result:

            ats_feedback = (
                llm_result.get(
                    "ats_feedback",
                    ""
                )
            )

            missing_skills = (
                llm_result.get(
                    "missing_skills"
                )
                or rule_gap
            )

            recommended_projects = (
                llm_result.get(
                    "recommended_projects"
                )
                or rule_projects
            )

            roadmap = (
                llm_result.get(
                    "roadmap"
                )
                or _fallback_roadmap(
                    role,
                    missing_skills
                )
            )

            github_recommendations = (
                llm_result.get(
                    "github_recommendations"
                )
                or github_result.get(
                    "recommendations",
                    []
                )
            )

        else:

            ats_feedback = (
                rule_ats[
                    "ats_feedback"
                ]
            )

            missing_skills = rule_gap

            recommended_projects = (
                rule_projects
            )

            roadmap = (
                _fallback_roadmap(
                    role,
                    missing_skills
                )
            )

            github_recommendations = (
                github_result.get(
                    "recommendations",
                    []
                )
            )

        github_score = (
            github_result.get(
                "github_score",
                0
            )
        )

        placement_readiness = round(
            ats_score * 0.6
            +
            github_score * 0.4
        )

        # ----------------------------
        # FINAL PAYLOAD
        # ----------------------------

        payload = {

            "success":
                True,

            "ats_score":
                ats_score,

            "ats_score_method":
                ats_score_method,

            "ats_feedback":
                ats_feedback,

            "placement_readiness":
                placement_readiness,

            "github_score":
                github_score,

            "github_public_repos":
                github_result.get(
                    "public_repositories",
                    0
                ),

            "github_followers":
                github_result.get(
                    "followers",
                    0
                ),

            "github_top_languages":
                github_result.get(
                    "top_languages",
                    []
                ),

            "missing_skills":
                missing_skills,

            "github_recommendations":
                github_recommendations,

            "projects":
                recommended_projects,

            "roadmap":
                roadmap,

            "jobs":
                [
                    {
                        key: value
                        for key, value
                        in job.items()
                        if key != "description"
                    }

                    for job in jobs_result
                ],

            "role":
                role,

            "github_username":
                github,
        }

        # ----------------------------
        # SAVE
        # ----------------------------

        try:

            result_id = await asyncio.to_thread(

                db.save_analysis,

                user_id,

                role,

                github,

                ats_score,

                ats_score_method,

                github_score,

                placement_readiness,

                json.dumps(payload),
            )

        except Exception as e:

            print(
                f"[db] save failed: {e}",
                flush=True
            )

            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error":
                        "Analysis succeeded "
                        "but couldn't be saved."
                },
            )

        print(
            f"[analyze] COMPLETE "
            f"result_id={result_id}",
            flush=True
        )

        return {

            "success":
                True,

            "redirect":
                f"/result/{result_id}",
        }

    except Exception as e:

        print(
            f"[analyze] ERROR: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            },
        )


# ============================================================
# 27. RESULT PAGE
# ============================================================
#
# THIS WAS MISSING FROM THE VERSION THAT RETURNED 404.
# ============================================================

@app.get(
    "/result/{result_id}",
    response_class=HTMLResponse
)
async def result_page(
    request: Request,
    result_id: int
):

    user_id = get_current_user_id(
        request
    )

    if user_id is None:

        return RedirectResponse(
            "/login",
            status_code=303
        )

    row = await asyncio.to_thread(
        db.get_analysis,
        result_id
    )

    if row is None:

        return HTMLResponse(
            "Result not found.",
            status_code=404
        )

    if row["user_id"] != user_id:

        return HTMLResponse(
            "You are not allowed to view this result.",
            status_code=403
        )

    return templates.TemplateResponse(

        request,

        "result.html",

        {
            "username":
                request.session.get(
                    "username"
                ),

            "result_id":
                result_id,

            "result_json":
                row["result_json"],

            "created_at":
                row["created_at"],
        }
    )


# ============================================================
# 28. DOWNLOAD PDF
# ============================================================

@app.get(
    "/result/{result_id}/pdf"
)
async def download_result_pdf(
    request: Request,
    result_id: int
):

    user_id = get_current_user_id(
        request
    )

    if user_id is None:

        return RedirectResponse(
            "/login",
            status_code=303
        )

    row = await asyncio.to_thread(
        db.get_analysis,
        result_id
    )

    if row is None:

        return HTMLResponse(
            "Result not found.",
            status_code=404
        )

    if row["user_id"] != user_id:

        return HTMLResponse(
            "You are not allowed to download this result.",
            status_code=403
        )

    try:

        result = json.loads(
            row["result_json"]
        )

        pdf_bytes = await asyncio.to_thread(

            generate_pdf,

            result,

            request.session.get(
                "username",
                ""
            ),

            row["created_at"],
        )

        role = result.get(
            "role",
            "career-report"
        )

        safe_role = re.sub(
            r"[^A-Za-z0-9]+",
            "-",
            str(role)
        ).strip("-").lower()

        filename = (
            "placement-report-"
            f"{safe_role or 'career'}-"
            f"{result_id}.pdf"
        )

        return Response(

            content=pdf_bytes,

            media_type="application/pdf",

            headers={

                "Content-Disposition":
                    f'attachment; filename="{filename}"',

                "Cache-Control":
                    "no-store",
            },
        )

    except Exception as e:

        print(
            f"[pdf] ERROR: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error":
                    "Could not generate the PDF."
            },
        )


# ============================================================
# 29. HISTORY
# ============================================================

@app.get("/history")
async def history(
    request: Request,
    limit: int = 10
):

    user_id = get_current_user_id(
        request
    )

    if user_id is None:

        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error":
                    "Please log in first."
            },
        )

    try:

        rows = await asyncio.to_thread(
            db.get_history,
            user_id,
            limit
        )

        return {
            "success":
                True,

            "history":
                rows,
        }

    except Exception as e:

        print(
            f"[history] ERROR: {e}",
            flush=True
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            },
        )


# ============================================================
# 30. OPTIONAL LANGSERVE AGENT
# ============================================================

agent = None

formatted_agent_chain = None


if llm is not None:

    try:

        agent = create_agent(

            model=llm,

            tools=tools,

            system_prompt=(
                "You are a Placement-Ready AI "
                "Career Agent. Help students "
                "prepare for placements by "
                "analyzing resumes, identifying "
                "skill gaps, evaluating GitHub "
                "profiles, recommending projects, "
                "and suggesting job opportunities."
            ),
        )

        class AgentInput(BaseModel):

            input: str = Field(
                description=
                "Career-related query"
            )

        def format_for_agent(x):

            user_input = (
                x["input"]
                if isinstance(x, dict)
                else x.input
            )

            return {
                "messages":
                    [
                        (
                            "user",
                            user_input
                        )
                    ]
            }

        def extract_text_response(
            agent_output
        ):

            if not isinstance(
                agent_output,
                dict
            ):

                return str(
                    agent_output
                )

            messages = (
                agent_output.get(
                    "messages"
                )
            )

            if messages is None:

                for value in (
                    agent_output.values()
                ):

                    if (
                        isinstance(
                            value,
                            dict
                        )
                        and
                        "messages"
                        in value
                    ):

                        messages = (
                            value["messages"]
                        )

                        break

            if messages:

                last = messages[-1]

                return getattr(
                    last,
                    "content",
                    str(last)
                )

            return str(
                agent_output
            )

        formatted_agent_chain = (

            RunnableLambda(
                format_for_agent
            )

            | agent

            | RunnableLambda(
                extract_text_response
            )

        ).with_types(
            input_type=AgentInput,
            output_type=str
        )

        add_routes(
            app,
            formatted_agent_chain,
            path="/career-agent",
            playground_type="default",
        )

    except Exception as e:

        print(
            f"[startup] LangServe agent "
            f"disabled: {e}",
            flush=True
        )


# ============================================================
# 31. MAIN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            8000
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
