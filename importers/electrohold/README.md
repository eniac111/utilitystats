# ⚡ Electrohold Invoice Importer

Automates the extraction of electricity usage data from Electrohold PDF invoices.  
The script fetches invoices from your email inbox, archives them to Nextcloud, and stores usage metrics in InfluxDB for visualization in Grafana.

---

## 📦 Features

- ✅ Fetch unread emails with Electrohold invoices (PDFs)
- ✅ Parse consumption data (day/night kWh, total, cost)
- ✅ Archive the PDF to Nextcloud via WebDAV
- ✅ Store data in InfluxDB in time-series format
- ✅ Ideal for dashboards (e.g. Grafana)

---

## ⚙️ Configuration

Create a `config.ini` file or set the corresponding environment variables.  
The script prioritizes environment variables over `config.ini`.
To use the config file, set the environment variable to the corresponding path:

```shell
export CONFIG_FILE=config.ini
```

### 🔧 `config.ini` example

```ini
[electrohold]

# IMAP Email Access
IMAP_SERVER = imap.yourmailserver.com
EMAIL_USER = your-email@example.com
EMAIL_PASS = your-email-password
EMAIL_SOURCE_FOLDER = INBOX
EMAIL_DESTINATION_FOLDER = Processed

# Nextcloud WebDAV
NEXTCLOUD_URL = https://nextcloud.example.com
NEXTCLOUD_USER = your-nextcloud-user
NEXTCLOUD_PASS = your-nextcloud-pass
NEXTCLOUD_FILE_PATH = Invoices/Electricity

# InfluxDB
INFLUXDB_URL = http://localhost:8086
INFLUXDB_TOKEN = your-influxdb-api-token
INFLUXDB_ORG = my-org
INFLUXDB_BUCKET = energy_data
```

## 🐳 Running in a Container

```shell
podman build -t electrohold-importer .
```

## ▶️ Run

```shell
podman run --rm \
  -e CONFIG_FILE=/app/config.ini \
  -v $(pwd)/config.ini:/app/config.ini:ro \
  electrohold-importer

```

Secrets may also be passed via ENV variables or `--env-file`.

The container may be executed periodicaly in a Crontab or a Kubernetes Cron Job.

## 📊 Visualizing in Grafana

A sample dashboard is in the `../../grafana_dashboards` directory.

## 🛡️ Disclaimer

This project is not affiliated with Electrohold or any utility provider. Use at your own risk.
