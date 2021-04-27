from typing import Any, Dict, Optional

from asyncio import ensure_future
from dataclasses import asdict, dataclass

from aiohttp import web
from aiohttp.web import Application, AccessLogger, AppRunner, BaseRequest, TCPSite, RouteTableDef, \
    Request, Response, StreamResponse
from aiohttp.helpers import sentinel
from aiohttp.typedefs import LooseHeaders
from dazl.protocols.v0.json_ser_command import LedgerJSONEncoder


from .log import \
    is_debug_enabled, LOG, get_log_level, get_log_level_options, set_log_level

from .config import Configuration
from .integration_context import IntegrationContext

# cap aiohttp to allow a maximum of 100 MB for the size of a body.
CLIENT_MAX_SIZE = 100 * (1024 ** 2)

DEFAULT_ENCODER = LedgerJSONEncoder()


def json_response(
        data: Any = sentinel, *,
        text: str = None,
        body: bytes = None,
        status: int = 200,
        reason: 'Optional[str]' = None,
        headers: 'LooseHeaders' = None) -> 'web.Response':
    return web.json_response(
        data=data, text=text, body=body, status=status, reason=reason, headers=headers,
        dumps=lambda obj: DEFAULT_ENCODER.encode(obj) + '\n')


def unauthorized_response(code: str, description: str) -> 'web.HTTPUnauthorized':
    body = DEFAULT_ENCODER.encode({'code': code, 'description': description}) + '\n'
    return web.HTTPUnauthorized(text=body, content_type='application/json')


def forbidden_response(code: str, description: str) -> 'web.HTTPForbidden':
    body = DEFAULT_ENCODER.encode({'code': code, 'description': description}) + '\n'
    return web.HTTPForbidden(text=body, content_type='application/json')


def not_found_response(code: str, description: str) -> 'web.HTTPNotFound':
    body = DEFAULT_ENCODER.encode({'code': code, 'description': description}) + '\n'
    return web.HTTPNotFound(text=body, content_type='application/json')


def bad_request(code: str, description: str) -> 'web.HTTPBadRequest':
    body = DEFAULT_ENCODER.encode({'code': code, 'description': description}) + '\n'
    return web.HTTPBadRequest(text=body, content_type='application/json')


def internal_server_error(code: str, description: str) -> 'web.HTTPInternalServerError':
    body = DEFAULT_ENCODER.encode({'code': code, 'description': description}) + '\n'
    return web.HTTPInternalServerError(text=body, content_type='application/json')


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

    @routes.get('/healthz')
    async def get_container_health(request: 'Request') -> 'Response':
        response_dict = {
            **_get_status(request),
            '_self': str(request.url)
        }
        return json_response(response_dict)

    @routes.get('/status')
    async def get_container_status(request: 'Request') -> 'Response':
        return json_response(_get_status(request))

    @routes.post('/log-level')
    async def set_level(request: 'Request') -> 'Response':
        body = await request.json()

        set_log_level(int(body['log_level']))

        return json_response(body)

    return routes


def _suppressed_route(path: str) -> bool:
    return path.startswith('/healthz') or path.startswith('/status')


class IntegrationAccessLogger(AccessLogger):
    def log(self, request: 'BaseRequest', response: 'StreamResponse', time: float):

        path = request.rel_url.path

        # Suppress polled routes to avoid cluttering the logs.
        if _suppressed_route(path) and not is_debug_enabled():
            return

        return super().log(request, response, time)


async def start_web_endpoint(
        config: 'Configuration',
        integration_context: 'IntegrationContext'):

    # prepare the web application
    app = Application(client_max_size=CLIENT_MAX_SIZE)

    app.add_routes(_build_control_routes(integration_context))

    if integration_context.running and integration_context.webhook_context:
        app.add_routes(integration_context.webhook_context.route_table)

    LOG.info('Starting web server on %s...', config.health_port)
    runner = AppRunner(
        app,
        access_log_class=IntegrationAccessLogger,
        access_log_format='%a %t "%r" %s %b')
    await runner.setup()
    site = TCPSite(runner, '0.0.0.0', config.health_port)

    LOG.info('...Web server started')

    return ensure_future(site.start())
