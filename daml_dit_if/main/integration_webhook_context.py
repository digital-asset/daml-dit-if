from dataclasses import dataclass
from typing import List, Optional, Sequence
from functools import wraps

from aiohttp import web
from aiohttp.web import RouteTableDef
from aiohttp.helpers import sentinel

from dazl import AIOPartyClient

from .common import \
    InvocationStatus, \
    without_return_value, \
    as_handler_invocation

from ..api import \
    AuthorizationLevel, \
    IntegrationWebhookRoutes, \
    IntegrationWebhookResponse, \
    json_response

from .log import LOG
from .auth_handler import set_handler_auth
from .integration_deferral_queue import IntegrationDeferralQueue

def empty_success_response() -> 'web.HTTPOk':
    return web.HTTPOk()


@dataclass
class WebhookRouteStatus(InvocationStatus):
    url_path: str
    method: str


def get_http_response(hook_response: 'IntegrationWebhookResponse'):
    response = empty_success_response()  # type: web.Response

    if hook_response.response is not None:
        LOG.debug("Returning 'response' field as HTTP response. ")

        response = hook_response.response

    elif hook_response.json_response is not None:
        LOG.debug("Returning 'json_response' field as HTTP response")

        response = json_response(
            data=hook_response.json_response,
            status=hook_response.http_status)

    elif hook_response.text_response is not None:
        LOG.debug("Returning 'text_response' field as HTTP response")

        response = web.Response(
            text=hook_response.text_response,
            content_type=hook_response.http_content_type,
            status=hook_response.http_status)

    elif hook_response.blob_response is not None:
        LOG.debug("Returning 'blob_response' field as HTTP response")

        response = web.Response(
            body=hook_response.blob_response,
            content_type=hook_response.http_content_type,
            status=hook_response.http_status)

    else:
        LOG.debug("Returning default successful HTTP response")


    LOG.debug('Webhook Response: %r', response)

    return response


class IntegrationWebhookContext(IntegrationWebhookRoutes):

    def __init__(self, queue: 'IntegrationDeferralQueue', client: 'AIOPartyClient'):
        self.route_table = RouteTableDef()
        self.client = client

        self.routes = []  # type: List[WebhookRouteStatus]

    def _with_resp_handling(self, status: 'InvocationStatus', fn):

        @wraps(fn)
        async def wrapped(request):
            return get_http_response(await fn(request))

        return wrapped

    def _notice_hook_route(self, url_path: str, method: str,
                           label: 'Optional[str]') -> 'WebhookRouteStatus':

        LOG.info('Registered hook (label: %s): %s %r', label, method, url_path)

        route_status = \
            WebhookRouteStatus(
                index=len(self.routes),
                url_path=url_path,
                method=method,
                label=label,
                command_count=0,
                use_count=0,
                error_count=0,
                error_message=None,
                error_time=None)

        self.routes.append(route_status)

        return route_status

    def _url_path(self, url_suffix: 'Optional[str]'):
        return '/integration/{integration_id}' + (url_suffix or '')

    def post(self, url_suffix: 'Optional[str]' = None, label: 'Optional[str]' = None,
             auth: 'Optional[AuthorizationLevel]' = AuthorizationLevel.PUBLIC):
        path = self._url_path(url_suffix)
        hook_status = self._notice_hook_route(path, 'post', label)

        def wrap_method(func):
            return set_handler_auth(
                self.route_table.post(path=path)(
                    self._with_resp_handling(
                        hook_status,
                        as_handler_invocation(
                            self.client, hook_status, func))),
                auth)

        return wrap_method

    def get(self, url_suffix: 'Optional[str]' = None, label: 'Optional[str]' = None,
             auth: 'Optional[AuthorizationLevel]' = AuthorizationLevel.PUBLIC):
        path = self._url_path(url_suffix)
        hook_status = self._notice_hook_route(path, 'get', label)

        def wrap_method(func):
            return set_handler_auth(
                self.route_table.get(path=path)(
                    self._with_resp_handling(
                        hook_status,
                        as_handler_invocation(
                            self.client, hook_status, func))),
                auth)

        return wrap_method

    def get_status(self) -> 'Sequence[WebhookRouteStatus]':
        return self.routes
