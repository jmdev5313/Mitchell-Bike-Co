"""The API app. Thin over `shop/`: rules live there, and their refusals become HTTP errors.

Run: make api   (docs at http://127.0.0.1:8000/docs)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agents import config
from api import customer, staff
from shop.errors import NotFound, RuleViolation

config.load_env()

app = FastAPI(
    title="Mitchell Bike Co. API",
    description=(
        "Staff endpoints (the Mechanic's workspace) need the staff passcode as a bearer token. "
        "Customer endpoints are reached through the Customer's private link token. "
        "Money is integer cents. A refusal by a shop rule returns 409 with the rule's reason."
    ),
    version="0.1.0",
)
app.include_router(staff.router)
app.include_router(customer.router)


@app.exception_handler(NotFound)
async def not_found(request: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RuleViolation)
async def rule_violation(request: Request, exc: RuleViolation) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
