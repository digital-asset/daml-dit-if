import re
from typing import Any, Dict, Optional

from asyncio import ensure_future, gather
from dataclasses import asdict, dataclass

from aiohttp import web
from aiohttp.web import Application, AccessLogger, AppRunner, BaseRequest, TCPSite, RouteTableDef, \
    Request, Response, StreamResponse


from .log import \
    is_debug_enabled, LOG, get_log_level, get_log_level_options, set_log_level

from .config import Configuration
from .integration_context import IntegrationContext
from .jwt import JWTValidator
from .auth_handler import AuthHandler, auth_level, AuthorizationLevel

from ..api import json_response

# cap aiohttp to allow a maximum of 100 MB for the size of a body.
CLIENT_MAX_SIZE = 100 * (1024 ** 2)

LOG_SUPPRESSED_ROUTE_REGEX = re.compile('^(/integration/[\w]+)?/((healthz)|(status))$')


def _build_control_routes(
        integration_context: 'IntegrationContext') -> 'RouteTableDef':
    routes = RouteTableDef()

    def _get_status(request: 'Request'):
        return {
            **asdict(integration_context.get_status()),
            'log_level': get_log_level(),
            'log_level_options': get_log_level_options(),
            '_self': str(request.url)
        }

    @routes.get('/integration/{integration_id}/healthz')
    @auth_level(AuthorizationLevel.ANY_PARTY)
    async def get_container_health(request: 'Request') -> 'Response':
        response_dict = {
            **_get_status(request),
            '_self': str(request.url)
        }
        return json_response(response_dict)

    @routes.get('/integration/{integration_id}/status')
    @auth_level(AuthorizationLevel.ANY_PARTY)
    async def get_container_status(request: 'Request') -> 'Response':
        return json_response(_get_status(request))

    @routes.post('/integration/{integration_id}/log-level')
    @auth_level(AuthorizationLevel.ANY_PARTY)
    async def set_level(request: 'Request') -> 'Response':
        body = await request.json()

        set_log_level(int(body['log_level']))

        return json_response(body)

    # The control routes are duplicated at paths that are not
    # qualified by an '/integration/{integration_id}' prefix. Due to
    # the lack of the prefix, these are private URLs that are only
    # addressible within the cluster. They have historically been used
    # to allow the console access to integration controls via a
    # secured proxy. As integrations migrate to model where security
    # is implemented internally, these will be deprecated and replaced
    # entirely with the secured external endpoints above.
    @routes.get('/healthz')
    async def internal_get_container_health(request):
        return await get_container_health(request)

    @routes.get('/status')
    async def internal_get_container_status(request):
        return await get_container_status(request)

    @routes.post('/log-level')
    async def internal_set_level(request):
        return await set_level(request)

    return routes

def _log_suppressed_route(path: str) -> bool:
    return LOG_SUPPRESSED_ROUTE_REGEX.match(path) is not None

class IntegrationAccessLogger(AccessLogger):
    def log(self, request: 'BaseRequest', response: 'StreamResponse', time: float):

        path = request.rel_url.path

        # Suppress polled routes to avoid cluttering the logs.
        if _log_suppressed_route(path) and not is_debug_enabled():
            return

        return super().log(request, response, time)


async def start_web_endpoint(
        config: 'Configuration',
        integration_context: 'IntegrationContext'):

    LOG.info('Starting web endpoint...')

    web_coros = []

    # prepare the web application
    app = Application(client_max_size=CLIENT_MAX_SIZE)

    jwt = None  # type: Optional[JWTValidator]
    if config.jwks_url:
        LOG.info('JWKS URL: %r', config.jwks_url)
        jwt = JWTValidator(jwks_urls=[config.jwks_url])

        web_coros.append(ensure_future(jwt.poll()))
    else:
        LOG.warn('No JWKS URL Available, all requests requiring authorization will be rejected.')

    auth_handler = AuthHandler(config, jwt)
    await auth_handler.setup(app)

    app.add_routes(_build_control_routes(integration_context))

    if integration_context.webhook_context:
        app.add_routes(integration_context.webhook_context.route_table)

    LOG.info('Starting web server on %s...', config.health_port)
    runner = AppRunner(
        app,
        access_log_class=IntegrationAccessLogger,
        access_log_format='%a %t "%r" %s %b')
    await runner.setup()
    site = TCPSite(runner, '0.0.0.0', config.health_port)

    web_coros.append(ensure_future(site.start()))

    LOG.info('...Web server started')

    return gather(*web_coros)
