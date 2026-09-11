"""Errori strutturati: {code, message, field_errors, request_id}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

MESSAGES = {
    401: ("unauthenticated", "Accesso richiesto."),
    403: ("forbidden", "Operazione non consentita."),
    404: ("not_found", "Risorsa non trovata."),
    405: ("method_not_allowed", "Metodo non consentito."),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field_errors: dict[str, str] | None = None):
        self.status, self.code, self.message, self.field_errors = status, code, message, field_errors or {}


def error_body(request: Request, code: str, message: str, field_errors: dict[str, str] | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "field_errors": field_errors or {},
        "request_id": getattr(request.state, "request_id", None),
    }


def field_errors_from(exc: ValidationError | RequestValidationError) -> dict[str, str]:
    result: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header")]
        message = str(err.get("msg", "Valore non valido."))
        result[".".join(loc) or "_"] = message.removeprefix("Value error, ")
    return result


def validation_error(exc: ValidationError) -> ApiError:
    errors = field_errors_from(exc)
    return ApiError(422, "validation_error", next(iter(errors.values()), "Dati non validi."), errors)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(error_body(request, exc.code, exc.message, exc.field_errors), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = field_errors_from(exc)
        message = next(iter(errors.values()), "Dati non validi.")
        return JSONResponse(error_body(request, "validation_error", message, errors), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code, message = MESSAGES.get(exc.status_code, ("http_error", str(exc.detail)))
        return JSONResponse(error_body(request, code, message), status_code=exc.status_code, headers=exc.headers)
