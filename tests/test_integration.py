from typing import TYPE_CHECKING

import pytest
import sob

from cms_gov_provider_data_sdk.client import Client

if TYPE_CHECKING:
    from cms_gov_provider_data_sdk.model import Datasets


def test_client_get_provider_data_api_1_metastore_schemas_dataset_items(
    client: Client,
) -> None:
    """
    Test a GET request to
    https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items
    """
    datasets: Datasets = client.get_metastore_schemas_dataset_items()
    sob.model.validate(datasets)


if __name__ == "__main__":
    pytest.main(["tests/test_integration.py"])
