# cms-gov-provider-data-sdk

[![test](https://github.com/davebelais/cms-gov-provider-data-sdk/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/davebelais/cms-gov-provider-data-sdk/actions/workflows/test.yml)

This project demonstrates use of [`oapi`](https://oapi.enorganic.org)
to generate an SDK/client for the Center for Medicare & Medicaid Services
[provider data API](https://data.cms.gov/provider-data/docs).

## Install

You can install this package from Github with pip:

```bash
pip3 install git+https://github.com/davebelais/cms-gov-provider-data-sdk.git@main#egg=cms_gov_provider_data_sdk
```

Currently, I have no plans to distribute this package to PYPI, as adequate
support would be cumbersome without additional API access and a sandbox or test
environment—but "watch" this repo if you'd like to know if the status
of development changes.
