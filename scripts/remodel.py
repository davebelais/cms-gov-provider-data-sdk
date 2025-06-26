from __future__ import annotations

import json
import os
from collections.abc import Sequence
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import gettempdir
from typing import IO, TYPE_CHECKING, Any, cast
from urllib.request import urlopen

import gittable.download
import oapi
import yaml  # type: ignore
from sob.model import serialize

OPENAPI_DOCUMENT_URL: str = "https://data.cms.gov/provider-data/api/1"
OPENAPI_GIT_REPOSITORY_URL: str = ""
OPENAPI_GIT_REPOSITORY_DOCUMENT_PATH: str = ""

PROJECT_PATH: Path = Path(__file__).absolute().parent.parent
OPENAPI_PATH: Path = PROJECT_PATH / "openapi"
OPENAPI_ORIGINAL: Path = OPENAPI_PATH / "original.json"
OPENAPI_FIXED: Path = OPENAPI_PATH / "fixed.json"
MODEL_PY: Path = PROJECT_PATH / "src/cms_gov_provider_data_sdk" / "model.py"
CLIENT_PY: Path = PROJECT_PATH / "src/cms_gov_provider_data_sdk" / "client.py"
STRING_SCHEMA: oapi.oas.Schema = oapi.oas.Schema(type_="string")
BOOLEAN_SCHEMA: oapi.oas.Schema = oapi.oas.Schema(type_="boolean")


def fix_openapi_data(data: str) -> str:
    """
    Fix errors in an Open API document which prevent the document from being
    parsed.

    This is an atypical issue, so this function can remain
    empty or be removed for most clients.

    Returns:
        Parseable JSON/YAML data.
    """
    return data


def get_openapi(
    openapi_document_path: str | Path = OPENAPI_ORIGINAL,
) -> oapi.oas.OpenAPI:
    """
    Load and parse a locally saved Open API document.
    """
    schema_path_lowercase: str = (
        str(openapi_document_path.absolute()).lower()
        if isinstance(openapi_document_path, Path)
        else openapi_document_path.lower()
    )
    openapi_document_io: IO[str]
    openapi_document_json: str
    openapi_document_dict: dict[str, Any]
    with open(openapi_document_path) as openapi_document_io:
        openapi_document_json = openapi_document_io.read()
    openapi_document_json = fix_openapi_data(openapi_document_json)
    openapi_document_io = StringIO(openapi_document_json)
    if schema_path_lowercase.endswith((".yaml", ".yml")):
        openapi_document_dict = yaml.safe_load(openapi_document_io)
    else:
        openapi_document_dict = json.load(openapi_document_io)
    return oapi.oas.OpenAPI(openapi_document_dict)


def fix_openapi(
    openapi_document: oapi.oas.OpenAPI,
) -> None:
    """
    Modify the Open API document to correct discrepancies between the
    document and actual API behavior/responses/etc.

    We script these fixes in order to be able to re-generate the client
    and model if/when the source document is modified, without losing these
    fixes we've identified as necessary.
    """
    # Add a server
    if not openapi_document.servers:
        openapi_document.servers = (
            oapi.oas.Server(
                url="https://data.cms.gov/provider-data/api/1",
                description="CMS Provider Data API V1",
            ),
        )
    # Create a model for an array of datasets
    if TYPE_CHECKING:
        assert openapi_document.components
    schemas: oapi.oas.Schemas = cast(
        oapi.oas.Schemas,
        cast(oapi.oas.Components, openapi_document.components).schemas,
    )
    schemas["datasets"] = oapi.oas.Schema(
        type_="array",
        items=oapi.oas.Reference(ref="#/components/schemas/dataset"),
        description="An array of datasets.",
    )
    # Remove unnecessary path prefixes
    openapi_document_paths: oapi.oas.Paths = cast(
        oapi.oas.Paths, openapi_document.paths
    )
    path: str
    path_item: oapi.oas.PathItem
    for path in tuple(openapi_document_paths.keys()):
        if not path.startswith("/provider-data/api/1/"):
            raise ValueError(path)
        openapi_document_paths[path[20:]] = openapi_document_paths.pop(path)
    # Add the metastore schemas dataset endpoint for retrieving *all* datasets
    # by copying the path for retrieving a single dataset
    metastore_schemas_dataset_items: oapi.oas.PathItem
    metastore_schemas_dataset_items = openapi_document_paths[
        "/metastore/schemas/dataset/items"
    ] = deepcopy(
        openapi_document_paths["/metastore/schemas/dataset/items/{identifier}"]
    )
    get_metastore_schemas_dataset_items: oapi.oas.Operation = cast(
        oapi.oas.Operation, metastore_schemas_dataset_items.get
    )
    get_metastore_schemas_dataset_items.summary = "Get all datasets."
    # Filter out the copied `datasetUuid` parameter
    parameter: oapi.oas.Parameter
    get_metastore_schemas_dataset_items.parameters = tuple(
        filter(
            lambda parameter: (
                (not isinstance(parameter, oapi.oas.Reference))
                or parameter.ref != "#/components/parameters/datasetUuid"
            ),
            get_metastore_schemas_dataset_items.parameters or (),
        )
    )
    # Change the response type from dataset to datasets
    if TYPE_CHECKING:
        assert get_metastore_schemas_dataset_items.responses
    get_metastore_schemas_dataset_items.responses["200"].content[
        "application/json"
    ].schema.ref = "#/components/schemas/datasets"
    # Add missing dataset attributes
    schemas["dataset"].properties["landingPage"] = STRING_SCHEMA


def download(
    url: str = OPENAPI_DOCUMENT_URL,
    path: str | Path = OPENAPI_ORIGINAL,
) -> None:
    """
    Download the original Open API document.

    Note: If you need to download the Open API document from a private
    repository, add the import `import gittable.download` and replace the
    following use of `urllib.request.urlopen` with
    with use of `gittable.download.download`.
    """
    response: IO[bytes]
    with urlopen(url) as response:  # noqa: S310
        data: bytes = response.read()
    with open(path, "wb") as file:
        file.write(data)


def update_openapi_original() -> Path | None:
    os.makedirs(OPENAPI_PATH, exist_ok=True)
    if OPENAPI_DOCUMENT_URL:
        download(OPENAPI_DOCUMENT_URL, OPENAPI_ORIGINAL)
        return OPENAPI_ORIGINAL
    if OPENAPI_GIT_REPOSITORY_URL and OPENAPI_GIT_REPOSITORY_DOCUMENT_PATH:
        # Download the OpenAPI document to your temp directory, then
        # move it to the specified `OPENAPI_ORIGINAL` file path
        os.rename(
            gittable.download.download(
                repo=OPENAPI_GIT_REPOSITORY_URL,
                files=(OPENAPI_GIT_REPOSITORY_DOCUMENT_PATH,),
                directory=gettempdir(),
            )[0],
            OPENAPI_ORIGINAL,
        )
        return OPENAPI_ORIGINAL
    return None


def update_model() -> Path | None:
    """
    Refresh (or initialize) the client's data model from the source Open API
    document.
    """
    update_openapi_original()
    if not OPENAPI_ORIGINAL.exists():
        raise FileNotFoundError(str(OPENAPI_ORIGINAL))
    open_api: oapi.oas.OpenAPI = get_openapi(OPENAPI_ORIGINAL)
    fix_openapi(open_api)  # If needed
    fixed_io: IO[str]
    with open(
        OPENAPI_FIXED,
        "w",
    ) as fixed_io:
        fixed_io.write(serialize(open_api, indent=4))
    oapi.write_model_module(
        MODEL_PY,
        open_api=open_api,
    )
    return MODEL_PY


def update_client() -> None:
    open_api: oapi.oas.OpenAPI = get_openapi(OPENAPI_FIXED)
    url: str = ""
    if open_api.servers:
        url = cast(str, cast(Sequence, open_api.servers)[0].url)
    oapi.write_client_module(
        CLIENT_PY,
        open_api=open_api,
        model_path=MODEL_PY,
        # Important: See the documentation for detailed information about all
        # parameters:
        # https://oapi.enorganic.org/api/oapi.client/#oapi.client.write_client_module
        # Most use cases will require, or at least benefit from, use of
        # customization via the `imports`, `init_decorator`,
        # `add_init_parameters`, `include_init_parameters`,
        # `init_parameter_defaults`, and/or `init_parameter_defaults_source`
        # arguments (among others). Additionally, most clients will NOT us all
        # initialization parameters, so limiting initialization parameters
        # using `include_init_parameters` is important to avoid confusing
        # users (particularly with regards to authentication options).
        include_init_parameters=(
            # Remove unused parameters from this tuple
            "url",
            "user",
            "password",
            "bearer_token",
            "api_key",
            "api_key_in",
            "api_key_name",
            "oauth2_client_id",
            "oauth2_client_secret",
            "oauth2_token_url",
            "oauth2_username",
            "oauth2_password",
            "oauth2_authorization_url",
            "oauth2_token_url",
            "oauth2_scope",
            "oauth2_refresh_url",
            "oauth2_flows",
            "open_id_connect_url",
            "headers",
            "timeout",
            "retry_number_of_attempts",
            "retry_for_errors",
            "retry_hook",
            "verify_ssl_certificate",
            "logger",
            "echo",
        ),
        init_parameter_defaults={
            "url": url,
            "retry_number_of_attempts": 3,
        },
    )


def main() -> None:
    update_model()
    update_client()


if __name__ == "__main__":
    main()
