# Radoff integration for Home Assistant
Install this repository using HACS

### Limitations
Currently supported devices:
- Now+

## Installation

You can install it using HACS or manually.

### With HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=raelix&category=integration&repository=ha-radoff-integration)

More informations about HACS [here](https://hacs.xyz/).

#### Manually

Clone this repository and copy `custom_components/radoff` to your Home Assistant config durectory (ex : `config/custom_components/radoff`)

Restart Home Assistant.

## Configuration

Once your Home Assistant has restarted, go to `Settings -> Devices & Services -> Add an  integration`.

Search for `radoff` and select the `Radoff` integration.

Enter your Radoff credentials.

If connection is working, you should have a list of devices configured on your account.

Select the device you want to add.

### Required parameters

- ```username```
- ```password```
- ```client_id```
- ```pool_id```
- ```pool_region```

### Warnings

Please do not use this against the real Radoff APIs as they are not intended to be exposed so I'm not responsible for any wrong use of this repository.