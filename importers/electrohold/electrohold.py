import os
import io
import re
import requests
import base64
import pdfplumber
from datetime import datetime
from imapclient import IMAPClient
import mailparser
import configparser
from email.header import decode_header, make_header
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

# Load environment
IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_SOURCE_FOLDER = os.getenv("EMAIL_SOURCE_FOLDER", "INBOX")
EMAIL_DESTINATION_FOLDER = os.getenv("EMAIL_DESTINATION_FOLDER", "Processed")
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL")
NEXTCLOUD_USER = os.getenv("NEXTCLOUD_USER")
NEXTCLOUD_PASS = os.getenv("NEXTCLOUD_PASS")
NEXTCLOUD_FILE_PATH = os.getenv("NEXTCLOUD_FILE_PATH")
INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")

CONFIG_FILE = os.getenv("CONFIG_FILE")
if CONFIG_FILE and os.path.isfile(CONFIG_FILE):
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    if "electrohold" in config:
        IMAP_SERVER = config["electrohold"].get("IMAP_SERVER", IMAP_SERVER)
        EMAIL_USER = config["electrohold"].get("EMAIL_USER", EMAIL_USER)
        EMAIL_PASS = config["electrohold"].get("EMAIL_PASS", EMAIL_PASS)
        NEXTCLOUD_URL = config["electrohold"].get("NEXTCLOUD_URL", NEXTCLOUD_URL)
        NEXTCLOUD_USER = config["electrohold"].get("NEXTCLOUD_USER", NEXTCLOUD_USER)
        NEXTCLOUD_PASS = config["electrohold"].get("NEXTCLOUD_PASS", NEXTCLOUD_PASS)
        NEXTCLOUD_FILE_PATH = config["electrohold"].get("NEXTCLOUD_FILE_PATH", NEXTCLOUD_FILE_PATH)
        INFLUXDB_URL = config["electrohold"].get("INFLUXDB_URL", INFLUXDB_URL)
        INFLUXDB_TOKEN = config["electrohold"].get("INFLUXDB_TOKEN", INFLUXDB_TOKEN)
        INFLUXDB_ORG = config["electrohold"].get("INFLUXDB_ORG", INFLUXDB_ORG)
        INFLUXDB_BUCKET = config["electrohold"].get("INFLUXDB_BUCKET", INFLUXDB_BUCKET)


def decode_mime_header(value):
    try:
        return str(make_header(decode_header(value)))
    except Exception as e:
        print(f"[WARN] Failed to decode header: {e}")
        return str(value)

def fetch_latest_bills():
    print("[INFO] Connecting to IMAP server...")
    bills = []

    try:
        with IMAPClient(IMAP_SERVER, ssl=True) as client:
            client.login(EMAIL_USER, EMAIL_PASS)
            print("[INFO] Logged in to IMAP.")

            client.select_folder(EMAIL_SOURCE_FOLDER)
            print("[INFO] Selected folder.")

            messages = client.search(['UNSEEN'], charset=None)
            print(f"[INFO] Found {len(messages)} unseen emails.")

            for uid in messages:
                print(f"[INFO] Processing email UID: {uid}")
                msg_data = client.fetch([uid], ['RFC822'])[uid][b'RFC822']
                mail = mailparser.parse_from_bytes(msg_data)

                raw_subject = mail.headers.get("Subject", "")
                if isinstance(raw_subject, (bytes, str)):
                    subject = decode_mime_header(raw_subject)
                else:
                    print(f"[WARN] Unexpected Subject header type: {type(raw_subject)}. Skipping.")
                    continue

                if "Електрохолд Продажби - Фактура" not in subject:
                    print(f"[DEBUG] Skipping email with subject: {subject}")
                    continue

                valid_pdf_found = False

                for attachment in mail.attachments:
                    filename = attachment.get("filename")
                    content_type = attachment.get("mail_content_type")

                    print(f"[DEBUG] Found attachment: {filename}")

                    if content_type != "application/pdf":
                        continue

                    payload = attachment.get("payload")

                    # Decode base64 or fallback
                    if isinstance(payload, str):
                        try:
                            pdf_bytes = base64.b64decode(payload)
                        except Exception:
                            print("[WARN] Could not decode attachment as base64.")
                            continue
                    else:
                        pdf_bytes = payload

                    if not pdf_bytes.startswith(b'%PDF'):
                        print("[ERROR] Skipping invalid PDF:", filename)
                        continue

                    client.move([uid], EMAIL_DESTINATION_FOLDER)
                    print(f"[INFO] Email moved to {EMAIL_DESTINATION_FOLDER}. PDF ready: {filename}")

                    bills.append((filename, io.BytesIO(pdf_bytes)))
                    valid_pdf_found = True

                if not valid_pdf_found:
                    print("[WARN] No valid PDF found in email UID:", uid)

    except Exception as e:
        print(f"[ERROR] Failed to fetch bill: {e}")

    return bills

def upload_to_nextcloud(filename, pdf_data):
    url = f"{NEXTCLOUD_URL}/remote.php/dav/files/{NEXTCLOUD_USER}/{NEXTCLOUD_FILE_PATH}/{filename}"
    response = requests.put(url, auth=(NEXTCLOUD_USER, NEXTCLOUD_PASS), data=pdf_data)
    response.raise_for_status()

def parse_pdf(pdf_data):
    with pdfplumber.open(pdf_data) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages)

    billing_period = re.search(r'от ([\d.]+) до ([\d.]+)', text)
    day_kwh = re.search(r'Дневна\s+\d+\s+\d+\s+(\d+)', text)
    night_kwh = re.search(r'Нощна\s+\d+\s+\d+\s+(\d+)', text)
    total_kwh = re.search(r'Общо:\s+(\d+)', text)
    total_cost = re.search(r'СУМА ЗА ПЛАЩАНЕ\s+([\d,]+)', text)

    # Convert Bulgarian dates (DD.MM.YYYY) to ISO (YYYY-MM-DD)
    start_raw = billing_period.group(1)
    end_raw = billing_period.group(2)
    start_iso = datetime.strptime(start_raw, "%d.%m.%Y").date().isoformat()
    end_iso = datetime.strptime(end_raw, "%d.%m.%Y").date().isoformat()

    return {
        "start_date": start_iso,
        "end_date": end_iso,
        "day_kwh": int(day_kwh.group(1)),
        "night_kwh": int(night_kwh.group(1)),
        "total_kwh": int(total_kwh.group(1)),
        "total_cost_bgn": float(total_cost.group(1).replace(',', '.'))
    }

def write_to_influx(data):
    with InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG
    ) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        point = Point("electricity_invoice") \
            .field("day_kwh", data["day_kwh"]) \
            .field("night_kwh", data["night_kwh"]) \
            .field("total_kwh", data["total_kwh"]) \
            .field("total_cost_bgn", data["total_cost_bgn"]) \
            .time(f"{data['end_date']}T00:00:00Z")

        print("[DEBUG] Writing to Influx:")
        print(point.to_line_protocol())

        write_api.write(bucket=INFLUXDB_BUCKET, record=point)
        print("Successfully imported invoice to InfluxDB.")


if __name__ == "__main__":
    bills = fetch_latest_bills()

    if not bills:
        print("No new invoice found.")
    else:
        for filename, pdf_data in bills:
            print(f"Processing: {filename}")
            pdf_data.seek(0)
            upload_to_nextcloud(filename, pdf_data.getvalue())

            pdf_data.seek(0)
            parsed_data = parse_pdf(pdf_data)

            write_to_influx(parsed_data)
            print("Successfully imported invoice to InfluxDB.")
