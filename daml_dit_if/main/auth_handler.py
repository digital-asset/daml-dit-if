from typing import Any, Awaitable, Callable, Mapping, Optional, TypeVar

from aiohttp.web import Application, Request, Response
from aiohttp.web_middlewares import middleware

from jwcrypto.common import JWException

from .log import LOG

from .config import Configuration
from .jwt import JWTValidator
from ..api import forbidden_response, unauthorized_response, AuthorizationLevel


Handler = Callable[[Request], Awaitable[Response]]


DABL_AUTH_LEVEL = "__dabl_auth_level__"
DABL_JWT_CLAIMS = "DABL_JWT_CLAIMS"


def get_token(request: "Request") -> "Optional[str]":
    header_identity = request.headers.get("Authorization")  # type: Optional[str]
    if header_identity is not None:
        scheme, _, bearer_token = header_identity.partition(" ")
        if scheme != "Bearer":
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


def set_handler_auth(fn: "Handler", auth_level: "AuthorizationLevel") -> "Handler":
    """
    Mark a request handler as not requiring authentication.
    """
    setattr(fn, DABL_AUTH_LEVEL, auth_level)

    return fn


def get_handler_auth_level(request: "Request") -> 'AuthorizationLevel':
    return getattr(request.match_info.handler, DABL_AUTH_LEVEL, AuthorizationLevel.PUBLIC)


def is_integration_party_claim(config: "Configuration", claims: "Mapping[str, Any]") -> bool:

    party = config.run_as_party

    if party is None:
        return False

    ledger_claims = claims.get('https://daml.com/ledger-api')

    if ledger_claims is None:
        LOG.info('No ledger claims found!')
        return False

    act_as_parties = ledger_claims.get('actAs', [])
    read_as_parties = ledger_claims.get('readAs', [])

    return party in act_as_parties and party in read_as_parties


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

            token = get_token(request)
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

            # TODO: Verify ledger ID here too?

            if auth_level == AuthorizationLevel.INTEGRATION_PARTY and \
               not is_integration_party_claim(self.config, claims):

                raise unauthorized_response(
                    "unauthorized",
                    "unauthorized token",
                )

            request[DABL_JWT_CLAIMS] = claims

        LOG.debug("Passing control to handler...")
        return await handler(request)
