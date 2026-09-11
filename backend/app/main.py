import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import errors
from .config import settings
from .errors import ApiError
from .routers import auth, imports, resources
from .security import csrf_rejection

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

app = FastAPI(title="Insieme API", version="0.2.0", docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")
errors.install(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    rejection = csrf_rejection(request)
    response = rejection or await call_next(request)
    path = request.url.path
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        # L'interfaccia si rivalida sempre (ETag): niente versioni vecchie dopo un aggiornamento.
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Security-Policy"] = CSP
    return response


api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
for router in resources.routers:
    api.include_router(router)
api.include_router(imports.router)


@api.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@api.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
def api_not_found(path: str):
    raise ApiError(404, "not_found", "Risorsa non trovata.")


app.include_router(api)
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
