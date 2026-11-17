"""The API app. Thin over `shop/`: rules live there, and their refusals become HTTP errors.

Run: make api   (docs at http://127.0.0.1:8000/docs)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agents import config
from api import conversations, customer, demo, staff
from api.agent_pool import AgentPool, default_factory
from shop.errors import NotFound, RuleViolation

config.load_env()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep open Agent conversations for the life of the app. Tests may set app.state.agent_factory."""
    app.state.agent_pool = AgentPool(getattr(app.state, "agent_factory", default_factory))
    yield
    await app.state.agent_pool.close_all()


app = FastAPI(
    lifespan=lifespan,
    title="Mitchell Bike Co. API",
    description=(
        "Staff endpoints (the Mechanic's workspace) need the staff passcode as a bearer token. "
        "Customer endpoints are reached through the Customer's private link token. "
        "Money is integer cents. A refusal by a shop rule returns 409 with the rule's reason."
    ),
    version="0.1.0",
)
app.include_router(staff.router)
app.include_router(conversations.router)
app.include_router(customer.router)
app.include_router(demo.router)

# The web pages: plain HTML, CSS and JavaScript in web/, no build step.
WEB = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/", include_in_schema=False)
def front_door() -> FileResponse:
    """The visitor front door: what this is, and how to try both sides."""
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/workshop", include_in_schema=False)
def workshop_page() -> FileResponse:
    """The Mechanic's workspace. Its data comes from the staff API, which needs the passcode."""
    return FileResponse(WEB / "workshop.html", headers={"Cache-Control": "no-store"})


@app.get("/c/{token}", include_in_schema=False)
def customer_page(token: str) -> FileResponse:
    """The Customer's page. It reads its data from /api/customer/{token}, so a bad link shows its own message."""
    return FileResponse(WEB / "customer.html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.exception_handler(NotFound)
async def not_found(request: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RuleViolation)
async def rule_violation(request: Request, exc: RuleViolation) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
