from typing import Any, Awaitable, Callable, Mapping, Optional, TypeVar

from aiohttp.web import Application, Request, Response
from aiohttp.web_middlewares import middleware

from jwcrypto.common import JWException

from .log import LOG

from .config import Configuration
from .jwt import JWTValidator

from ..api import \
    AuthorizationLevel

from ..api.common import \
    forbidden_response, \
    unauthorized_response


from .auth_accessors import \
    DABL_JWT_LEDGER_CLAIMS, \
    is_integration_party_ledger_claim, \
    get_configured_integration_ledger_claims


Handler = Callable[[Request], Awaitable[Response]]


DABL_AUTH_LEVEL = "__dabl_auth_level__"



def set_handler_auth(fn: "Handler", auth: "AuthorizationLevel") -> "Handler":
    """
    Mark a request handler as not requiring authentication.
    """
    setattr(fn, DABL_AUTH_LEVEL, auth)

    return fn


def auth_level(auth: "AuthorizationLevel") -> "Callable[[Handler], Handler]":

    def set(fn: "Handler") -> "Handler":
        return set_handler_auth(fn, auth)

    return set


def get_handler_auth_level(request: "Request") -> 'AuthorizationLevel':
    return getattr(request.match_info.handler, DABL_AUTH_LEVEL, AuthorizationLevel.PUBLIC)


def _unvalidated_get_token(request: "Request") -> "Optional[str]":
    header_identity = request.headers.get("Authorization")  # type: Optional[str]
    if header_identity is not None:
        scheme, _, bearer_token = header_identity.partition(" ")
        if scheme != "Bearer" or not bearer_token or len(bearer_token) == 0:
            raise unauthorized_response(
                "invalid_auth_scheme",
                "Invalid authorization scheme. Should be `Bearer <token>`",
            )
        return bearer_token
    else:
        # we also accept token as a query string for GET requests because it's the only way we
        # can get token information via redirects
        access_token = request.query.get("access_token")

        # if the query string parameter is empty, it might as well not be set at all
        return access_token if access_token else None


class AuthHandler:
    def __init__(self, config: 'Configuration', jwt_decoder: 'Optional[JWTValidator]'):
        self.config = config
        self.jwt_decoder = jwt_decoder

    async def setup(self, app: "Application") -> None:
        app.middlewares.append(self.auth_middleware)

    @middleware
    async def auth_middleware(self, request: "Request", handler):
        LOG.debug("in auth middleware for request %s", request)

        auth_level = get_handler_auth_level(request)

        if auth_level != AuthorizationLevel.PUBLIC:

            if self.jwt_decoder is None:
                raise unauthorized_response(
                    "no_authorization_support",
                    "this endpoint requires authorization, which is unavailable without JWKS support.",
                )

            token = _unvalidated_get_token(request)
            if token is None:
                raise unauthorized_response(
                    "missing_token",
                    "this endpoint requires a valid token and none was supplied",
                )

            try:
                claims = await self.jwt_decoder.decode_claims(token)
            except JWException as ex:
                LOG.warning("Rejected a token: %s", ex)
                raise forbidden_response(
                    "invalid_token", "this endpoint was presented with an invalid token"
                )

            ledger_claims = get_configured_integration_ledger_claims(self.config, claims)

            if ledger_claims is None:
                raise unauthorized_response(
                    "missing_ledger_claims",
                    "this endpoint requires a valid token containing DAML ledger API claims"
                    f" for ledger ID \"{self.config.ledger_id}\"" ,
                )

            if auth_level == AuthorizationLevel.INTEGRATION_PARTY and \
               not is_integration_party_ledger_claim(self.config, ledger_claims):

                raise unauthorized_response(
                    "unauthorized",
                    "unauthorized token",
                )

            request[DABL_JWT_LEDGER_CLAIMS] = ledger_claims

        LOG.debug("Passing control to handler...: (%r)", handler)
        return await handler(request)
