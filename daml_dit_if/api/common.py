import logging

from typing import Any, Optional

from dazl.damlast.lookup import parse_type_con_name
from dazl.damlast.util import package_ref

from daml_dit_api import DamlModelInfo

from aiohttp import web
from aiohttp.typedefs import LooseHeaders
from dazl.protocols.v0.json_ser_command import LedgerJSONEncoder
from aiohttp.helpers import sentinel

LOG = logging.getLogger('daml-dit-if')

def ensure_package_id(daml_model: 'Optional[DamlModelInfo]', template: str) -> str:

    if template == '*':
        return template

    package = package_ref(parse_type_con_name(template))

    if package != '*':
        return template

    if daml_model is None:
        raise Exception(f'No default model {package} known when ensuring package ID: {template}')
    else:
        return f'{daml_model.main_package_id}:{template}'



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


def empty_success_response() -> "web.HTTPOk":
    return web.HTTPOk()


def blob_success_response(
    body: bytes, content_type: "Optional[str]" = "application/octet-stream"
) -> "web.HTTPOk":

    return web.HTTPOk(body=body, content_type=content_type)


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
