from typing import Optional

from dazl.damlast.lookup import parse_type_con_name
from dazl.damlast.util import package_ref

from daml_dit_api import DamlModelInfo


def ensure_package_id(daml_model: 'Optional[DamlModelInfo]', template: str) -> str:

    if template == '*':
        return template

    package = package_ref(parse_type_con_name(template))

    if package != '*':
        return template

    if daml_model is None:
        raise Exception(f'No default model known when ensuring package ID: {template}')
    else:
        return f'{daml_model.main_package_id}:{template}'
