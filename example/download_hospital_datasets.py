"""
Given the CMS provider data metastore, write a script that downloads all
data sets related to the theme "Hospitals".

The column names in the csv headers are currently in mixed case with spaces and
special characters. Convert all column names to snake_case (Example:
"Patients' rating of the facility linear mean score" becomes
"patients_rating_of_the_facility_linear_mean_score").

The csv files should be downloaded and processed in parallel, and the job
should be designed to run every day, but only download files that have been
modified since the previous run (need to track runs/metadata).

Please email your code and a sample of your output to your recruiter or
interviewer.  Add any additional comments or description below.

https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items

Submission Requirements:

-   The job must be written in python and must run on a regular Windows or
    linux computer (i.e. there shouldn't be anything specific to Databricks,
    AWS, etc.)
-   Include a requirements.txt file if your job uses python packages that do
    not come with the default python install
"""

from __future__ import annotations

import csv
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from functools import cache, wraps
from io import TextIOWrapper
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Callable

import sob

from cms_gov_provider_data_sdk.client import Client

if TYPE_CHECKING:
    from collections.abc import Iterable
    from http.client import HTTPResponse

    from cms_gov_provider_data_sdk.model import Dataset, DatasetDistribution

DATA: Path = Path(__file__).parent / "data"
ECHO: bool = False
DUMMY_END_DATE: date = date(1900, 1, 1)


@cache
def get_client() -> Client:
    """
    Get and cache a CMS Provider Data API client.
    """
    return Client(echo=ECHO)


def iter_hospital_dataset_identifier_download_url(
    client: Client | None = None,
) -> Iterable[tuple[str, str]]:
    """
    Iterate over all dataset downloads with the theme "Hospitals".

    Parameters:
        client: If not provided, a new client will be created
            and cached
    """
    client = client or get_client()
    dataset: Dataset
    for dataset in client.get_metastore_schemas_dataset_items():
        if (
            dataset.theme
            and "Hospitals" in dataset.theme
            and dataset.distribution
        ):
            distribution: DatasetDistribution
            for distribution in dataset.distribution:
                if distribution.download_url and (
                    distribution.media_type == "text/csv"
                ):
                    yield dataset.identifier, distribution.download_url


def iter_csv(
    csv_bytes_io: IO[bytes],
    end_dates: set,
    after: date | None = None,
) -> Iterable[tuple[Any, ...]]:
    """
    Iterate over rows in a CSV file

    Parameters:
        csv_bytes_io: An IO stream containing the CSV data.
        end_dates: A set to collect unique end dates from the CSV.
        after: If provided, only yield rows with an end date after this date.
    """
    csv_io: IO[str] = TextIOWrapper(
        csv_bytes_io,
    )
    reader: csv._reader = csv.reader(csv_io)
    # snake_case the column names
    columns: tuple[str, ...] = tuple(
        map(sob.utilities.get_property_name, next(reader))
    )
    yield columns
    end_date_index: int | None = None
    index: int
    for index, column in enumerate(columns):
        if column.endswith("end_date"):
            end_date_index = index
            if column == "end_date":
                # Only stop looking if we found an exact match
                break
    if end_date_index is None:
        # Add a dummy end date to indicate no end dates are in this dataset
        end_dates.add(DUMMY_END_DATE)
    row: tuple
    for row in reader:
        end_date: date | None = None
        if end_date_index and row[end_date_index]:
            end_date = datetime.strptime(  # noqa: DTZ007
                row[end_date_index], "%m/%d/%Y"
            ).date()
            end_dates.add(end_date)
        # Yield rows with an end date after the indicated `after` date
        if (
            end_date_index is None
            or after is None
            or end_date is None
            or end_date > after
        ):
            yield row


def get_after_end_date(directory: Path) -> date | None:
    """
    Get the most recent end date file name prefix from a directory,
    or `None` if no files have an end date prefix.
    """
    path: Path
    for path in directory.iterdir():
        if path.suffix == ".csv" and path.is_file():
            try:
                return datetime.strptime(
                    path.stem.partition(".")[0], "%Y-%m-%d"
                ).date()
            except ValueError:
                # Ignore files that do not match the expected date format
                continue
    return None


def download_hospital_dataset(
    download_url: str, directory: Path, client: Client | None = None
) -> None:
    """
    Download a CSV dataset from the CMS Provider Data API
    having only new records as determined by the end date, if the dataset
    has an end date, or a complete dataset if it does not.

    Parameters:
        download_url: The URL to download the dataset from.
        directory: The directory to download the dataset to.
        client: If not provided, a new client will be created
            and cached
    """
    client = client or get_client()
    os.makedirs(directory, exist_ok=True)
    name: str = download_url.rpartition("/")[-1]
    temp_path: Path = directory / f"{name}"
    response: HTTPResponse
    end_dates: set[date] = set()
    after: date | None = get_after_end_date(directory)
    print(f"Downloading {download_url} to {temp_path!s}")  # noqa: T201
    with (
        client.request(download_url, method="GET") as response,
        open(temp_path, "w") as csv_io,
    ):
        csv.writer(csv_io).writerows(
            iter_csv(response, end_dates, after)
        )
    if DUMMY_END_DATE not in end_dates:
        # Only delete or rename the un-dated file if there is an end date in
        # the dataset
        if end_dates:
            latest_end_date: date = max(end_dates)
            if (after is None) or latest_end_date > after:
                os.rename(
                    temp_path, directory / (
                        f"{latest_end_date.isoformat()}.{name}"
                    )
                )
            elif (after is not None) and latest_end_date <= after:
                # If the latest end date is not after the `after` date,
                # delete the file
                temp_path.unlink()
        else:
            temp_path.unlink()


def starmap_wrap(function: Callable) -> Any:
    """
    Wrap a function having positional arguments
    for use with `ThreadPoolExecutor.map`.
    """

    def wrapper(arguments: tuple) -> Any:
        return function(*arguments)

    return wraps(function)(wrapper)


def download_hospital_datasets(
    directory: Path = DATA, client: Client | None = None
) -> Iterable[Dataset]:
    """
    Download all datasets with the theme "Hospitals".

    Parameters:
        directory: The root directory to download the datasets to.
            If it does not exist, it will be created.
        client: If not provided, a new client will be created
            and cached
    """
    os.makedirs(directory, exist_ok=True)
    identifier: str
    download_url: str
    with ThreadPoolExecutor() as executor:
        deque(
            executor.map(
                # map(
                starmap_wrap(download_hospital_dataset),
                (
                    (
                        download_url,
                        directory / identifier,
                        client,
                    )
                    for identifier, download_url in (
                        iter_hospital_dataset_identifier_download_url(client)
                    )
                ),
            ),
            maxlen=0,
        )


def main() -> None:
    download_hospital_datasets()


if __name__ == "__main__":
    main()
