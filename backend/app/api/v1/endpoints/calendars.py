"""Read-only calendar connections, owned by an opaque HttpOnly browser session."""

from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import get_calendar_service
from app.models.calendar import CalendarBrowserSession
from app.schemas.calendar import (
    AppleConnectRequest,
    CalendarListResponse,
    CalendarParseRequest,
    CalendarProvider,
    CalendarSessionResponse,
    CalendarUrlImportRequest,
    GoogleAuthorizationResponse,
    ParsedCalendarResponse,
)
from app.services.calendar import SESSION_SECONDS, CalendarService
from app.services.calendar_errors import CalendarError

Service = Annotated[CalendarService, Depends(get_calendar_service)]


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(dependencies=[Depends(private_response)])


async def browser_session(request: Request, service: Service) -> CalendarBrowserSession:
    session, _ = await service.session(request.cookies.get(service.cookie_name))
    return session


Browser = Annotated[CalendarBrowserSession, Depends(browser_session)]


def csrf_session(request: Request, service: Service, session: Browser) -> CalendarBrowserSession:
    service.validate_csrf(session, request.headers.get("X-CSRF-Token"))
    origin = request.headers.get("Origin")
    frontend = urlsplit(service.frontend_url)
    allowed = {f"{frontend.scheme}://{frontend.netloc}", str(request.base_url).rstrip("/")}
    if origin and origin not in allowed:
        raise CalendarError("forbidden", "Calendar requests must come from this application.")
    return session


VerifiedBrowser = Annotated[CalendarBrowserSession, Depends(csrf_session)]


@router.get("/session", response_model=CalendarSessionResponse)
async def session_status(
    request: Request, response: Response, service: Service
) -> CalendarSessionResponse:
    session, token = await service.session(request.cookies.get(service.cookie_name), create=True)
    if token is not None:
        response.set_cookie(
            service.cookie_name,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=service.secure_cookie,
            samesite="lax",
            path="/",
        )
    return await service.status(session)


@router.post("/google/authorize", response_model=GoogleAuthorizationResponse)
async def authorize_google(
    service: Service, session: VerifiedBrowser
) -> GoogleAuthorizationResponse:
    return GoogleAuthorizationResponse(authorization_url=await service.start_google(session))


@router.get("/google/callback")
async def google_callback(
    service: Service,
    session: Browser,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    connected = await service.finish_google(
        session, state=state, code=code, denied=error is not None
    )
    query = urlencode({"calendar": "google", "status": "connected" if connected else "cancelled"})
    destination = "/calendars" if connected else "/"
    return RedirectResponse(
        f"{service.frontend_url}{destination}?{query}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/apple/connect", response_model=CalendarSessionResponse)
async def connect_apple(
    body: AppleConnectRequest, service: Service, session: VerifiedBrowser
) -> CalendarSessionResponse:
    await service.connect_apple(session, body)
    return await service.status(session)


@router.post("/import", response_model=ParsedCalendarResponse)
async def import_calendar_url(
    body: CalendarUrlImportRequest, service: Service, session: VerifiedBrowser
) -> ParsedCalendarResponse:
    return await service.import_url(session, body)


@router.get("/{provider}/calendars", response_model=CalendarListResponse)
async def list_calendars(
    provider: CalendarProvider, service: Service, session: Browser
) -> CalendarListResponse:
    return CalendarListResponse(
        provider=provider, calendars=await service.calendars(session, provider)
    )


@router.post("/{provider}/parse", response_model=ParsedCalendarResponse)
async def parse_calendar(
    provider: CalendarProvider,
    body: CalendarParseRequest,
    service: Service,
    session: VerifiedBrowser,
) -> ParsedCalendarResponse:
    return await service.parse(session, provider, body)


@router.delete("/{provider}", status_code=204)
async def disconnect(
    provider: CalendarProvider, service: Service, session: VerifiedBrowser
) -> Response:
    await service.disconnect(session, provider)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
