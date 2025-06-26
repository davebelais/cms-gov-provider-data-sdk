import pytest

from cms_gov_provider_data_sdk.client import Client


@pytest.fixture(name="client", autouse=True, scope="session")
def get_client() -> Client:
    return Client(echo=True)
