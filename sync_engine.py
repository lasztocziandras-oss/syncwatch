"""
SyncWatch — iCal Channel Manager with Google Calendar Integration
=================================================================
1. Pulls Airbnb + Booking.com iCal feeds every 15 min
2. Syncs bookings/cancellations to Google Calendar (middle layer)
3. Sends Telegram alerts for new bookings, cancellations, double bookings
4. Built-in web server for Railway deployment
5. Reads all secrets from environment variables (secure)
"""

import time
import json
import logging
import smtplib
import os
import threading
import tempfile
from datetime import datetime, date, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    import requests
    from icalendar import Calendar
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    LIBS_OK = True
except ImportError:
    LIBS_OK = False
    print("Run: pip install icalendar requests google-api-python-client google-auth")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION — all secrets from environment variables
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REFRESH_INTERVAL = 900
PORT             = int(os.environ.get("PORT", 8080))
OUTPUT_DIR       = Path("./ical_output")
SCOPES           = ["https://www.googleapis.com/auth/calendar"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "5469826706")
EMAIL_SENDER   = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")
SMTP_SERVER    = "smtp.gmail.com"
SMTP_PORT      = 587

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  APARTMENTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

APARTMENTS = [
    {"name": "Szasz 6", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/39770689.ics?t=6bd0c8f4116c4e82aaf4a5ddf8df6a08", "booking_ical": "https://ical.booking.com/v1/export?t=e655f1d5-6849-48d6-9ff3-24a2888baf1e", "google_cal_id": "b56bcbd8738f1c8782981f83431e8730d48a67f9ace0e970136d6ac980e88a70@group.calendar.google.com"},
    {"name": "Szasz 1", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/48225090.ics?t=e7a457c98e1e420490908db653d55c85", "booking_ical": "https://ical.booking.com/v1/export/t/73f41f1f-6528-4f25-b44a-03562b0fa01f.ics", "google_cal_id": "8704f6991a4a112f2072804b1f33f87e0f5b9b6a129c6535661c5bec92154952@group.calendar.google.com"},
    {"name": "Bacso", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/597561960433955581.ics?t=c508fe0b09ff479bac795a8f96413f5c", "booking_ical": "https://ical.booking.com/v1/export/t/b3f2b323-9413-46e4-a37d-922e193da6b4.ics", "google_cal_id": "e3331de99407058e738c5cd5f69ba1be01f186308feb71075435630e131eb5f6@group.calendar.google.com"},
    {"name": "Kiraly21", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/634773005345678844.ics?t=bda753882ae94c20b8a9e9f16314e073", "booking_ical": "https://ical.booking.com/v1/export?t=bcfed706-6a95-4beb-996b-50d0897fb070", "google_cal_id": "08fb097cd62783844369a8e1b2895ee98096dca3ad00cbd805a407a488ba95a8@group.calendar.google.com"},
    {"name": "Paulay", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/672873607742826420.ics?t=4a5d85c774c54c3fb2b75dced629dacd", "booking_ical": "https://ical.booking.com/v1/export?t=ab61bd57-86bf-41cc-b874-7832cfffd681", "google_cal_id": "6071b8158a8ccaddb50d1e1a550c12fa4612db461c3ce3ee13dc56e2263968dc@group.calendar.google.com"},
    {"name": "Kisrako", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/826650013123111395.ics?t=58329fabe4024fe78dc2dcf2407b27b1", "booking_ical": "https://ical.booking.com/v1/export?t=a7b4d96f-edce-4fc6-8d03-d98af7c16f47", "google_cal_id": "f8f9c4248ae04b29e30ac92930b67c8c7786a71462596b4b38965645f12355df@group.calendar.google.com"},
    {"name": "Nagyrako", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/826680241770964956.ics?t=a7e5745a305a4cac9a58bea9ad1912bb", "booking_ical": "https://ical.booking.com/v1/export?t=626e4853-3c82-4e76-af2c-e248911c0ea3", "google_cal_id": "d5121a85ecbc18ca44617a247775742a16b16b092f6449b9e62b52bca4ee74e8@group.calendar.google.com"},
    {"name": "Kertesz", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/863651163948938178.ics?t=f8a3db3fff124f80a2dd52f8cc0c2ce3", "booking_ical": "https://ical.booking.com/v1/export/t/4e1d399f-ef64-4024-8658-fff3f7e4ea17.ics", "google_cal_id": "2ec4ef89402f138077eec87aef8d9540b357574947bdb2caf01f8ff5fd737c6c@group.calendar.google.com"},
    {"name": "Papnevelde", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/918031140373505021.ics?t=132f3c47a0234dd08ab9a0d211dbe8e4", "booking_ical": "https://ical.booking.com/v1/export/t/41020573-08e1-42fb-bf5a-c39eb2095c75.ics", "google_cal_id": "9ebee5b00aeb389ef49749a6f82eff450afca28360c839198cc0b1bf9673c046@group.calendar.google.com"},
    {"name": "Liszt", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1021637396445726102.ics?t=2b2d701c7d034ef5a08422c8dbb6f8c8", "booking_ical": "https://ical.booking.com/v1/export?t=377afb97-13b3-4a90-9291-eed8a37ca10e", "google_cal_id": "d5864f9647c35e7befa8e657b773fdff0c4032ceb466c866665aaa49ef45aa9b@group.calendar.google.com"},
    {"name": "Akac", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1467898170189218510.ics?t=1c2d5c837acb4a8d92a9ebb025d7d442", "booking_ical": "https://ical.booking.com/v1/export?t=67d13cc4-3f02-4e59-bf42-9beba0e09317", "google_cal_id": "2a9cadca737dc902cbc6b911abd9d6a33b9eecb8a6de0b3e74bbb8e69752c6c4@group.calendar.google.com"},
    {"name": "Kossuth11", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/614858679243845201.ics?t=8f2b3c832738464f886234fea2f44848", "booking_ical": "https://ical.booking.com/v1/export?t=16d12cf7-d648-4598-8632-a41aa1fe0eae", "google_cal_id": "9ce4ad782cc71f31d23a0b2da81dea18fe25c97dc3f4d0a799e94a67b2257b77@group.calendar.google.com"},
    {"name": "Pozsonyi", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/869448779445987249.ics?t=74f94ba3e12d4cf1a2315476900d7493", "booking_ical": "https://ical.booking.com/v1/export/t/6c14ffeb-53ef-4be8-8b83-7e632a3a06f5.ics", "google_cal_id": "5faa05ecdb2a17d4f29d2f14e4070766bef13ad5cbedf3dbfe498a5af3a849b8@group.calendar.google.com"},
    {"name": "Danube Jegverem", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/783059292361852024.ics?t=0f3094e88a7e4d66a96892353db2ec85", "booking_ical": "https://ical.booking.com/v1/export/t/5868fb88-89cf-4474-ad52-259e8b8a8e49.ics", "google_cal_id": "41dbc25e578b0257767bdb4ef203b2c966166e6f7089edce6b3c5ecc7f5f5653@group.calendar.google.com"},
    {"name": "Gellert", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1262263828865718194.ics?t=35ee6544b0ef4c00aad25b953e7a6d18", "booking_ical": "https://ical.booking.com/v1/export/t/528988c7-b2d2-4fd7-8379-c886ed2343a1.ics", "google_cal_id": "14253d62bf3b9a2e93daeb08a98e72cb912ed8d41b6787f027193d7653af6a72@group.calendar.google.com"},
    {"name": "Vaskapu", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/13351713.ics?t=619fb3a906f649abaac53839455a62f0", "booking_ical": "https://ical.booking.com/v1/export?t=de1b319f-91df-4aab-b64e-899cdc74df38", "google_cal_id": "f1afa9c2ed138c26c00fd4b7003bfdde63d7cd3beb053f5ecd60a6f6b25e288a@group.calendar.google.com"},
    {"name": "Hold", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1268614959374258042.ics?t=fc11bc60e92445ac8492536addce8724", "booking_ical": "https://ical.booking.com/v1/export/t/e4a073dd-990b-4a9a-9969-2f413811ed3b.ics", "google_cal_id": "a33bd992acce7bb0973a5c0337680eedc0a1d0c250bbf2bb6b26a65ba9bd4b91@group.calendar.google.com"},
    {"name": "Jaszai", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1300623420805752108.ics?t=bb10e83939b94a679faff936f8730381", "booking_ical": "https://ical.booking.com/v1/export/t/df64e680-52c5-4312-b192-23579f3732d0.ics", "google_cal_id": "98b842aa2b8bb6e1e2057e3fec4e4da06c115714407577b9d4177cb826da4792@group.calendar.google.com"},
    {"name": "Dohany28", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1518069561830442473.ics?t=af66857e8bf94cca9d7d1e7767adaa6a", "booking_ical": "https://ical.booking.com/v1/export/t/624500d1-d9ea-48a8-b1f1-4609f2f369a1.ics", "google_cal_id": "cd42d93d3470466b82a01799df103d064521615f720465a8ede774725207e4a3@group.calendar.google.com"},
    {"name": "Kiraly33", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/655697222581393957.ics?t=64d757a86900453eb2255d8d9ff739e3", "booking_ical": "https://ical.booking.com/v1/export?t=7fc4c53a-e424-48f4-b447-112e1c6c3476", "google_cal_id": "7e671bab3fa4079694e42da67b0e5d732283226667b4fcce81cbfc4851a8a02e@group.calendar.google.com"},
    {"name": "Dob5", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1156212311866505180.ics?t=6db803067c5d42c0a4a6508127425dc5", "booking_ical": "https://ical.booking.com/v1/export?t=1069a0f9-2f0c-425c-85f1-cadd22030471", "google_cal_id": "aac09b2054f01d13f9c317104cf9904bf984e5f0ed1b3a32f508cf18aed3c051@group.calendar.google.com"},
    {"name": "Mester43", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1546443313772306410.ics?t=e5c51815a37e40daab0d01a5f92ca08e", "booking_ical": "https://ical.booking.com/v1/export?t=c01760f5-7081-4e0a-b708-c6ac8e9d6ab5", "google_cal_id": "c311ebbeaa2442fb71827f292bed6d84e45677ef41772cf9e4d5ebc211703744@group.calendar.google.com"},
    {"name": "Raday", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1252639206711643437.ics?t=07d69d4ef1bf4cb48e86872739d486b5", "booking_ical": "https://ical.booking.com/v1/export?t=f30c0a6a-2553-4274-9b68-fad60fd84fcd", "google_cal_id": "3289144a76d297174397e1d6cade13bb8a097b00f34fbbb9b4a4925dfda60bda@group.calendar.google.com"},
    {"name": "Riverside", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/16989234.ics?t=ab2ee5a7e23545b8ba1fb8596eebd846", "booking_ical": "https://ical.booking.com/v1/export?t=8bcb70be-4096-4d9c-ba10-1e938f6e1791", "google_cal_id": "48b52c5f757c30ea111f1509836e77dc061e52293d4f3fc8cc6139f734ae6c81@group.calendar.google.com"},
    {"name": "Dob28", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/24646380.ics?t=d8cd9f6e38234f0eafebd1c5dd90fcfe", "booking_ical": "https://ical.booking.com/v1/export/t/b9de6741-0a1d-44b0-9e3c-2fc57bb4c823.ics", "google_cal_id": "6a084ad8f8aa5bece5043f2be1cf70e32535029d17330d905fdde6d6d90deb46@group.calendar.google.com"},
    {"name": "Baross40", "airbnb_ical": "https://www.airbnb.hu/calendar/ical/1362977783083661448.ics?t=7f5bfac6ba5a402da3765ec1b0e140ad", "booking_ical": "https://ical.booking.com/v1/export/t/cc5ba8db-4333-4039-a7f4-be48df5f68dc.ics", "google_cal_id": "37fc6787eb97c878e37ea8ff217c47eb0caadc675f0276f0466148afac6bc950@group.calendar.google.com"},
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LOGGING & STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", handlers=[logging.StreamHandler()])
log = logging.getLogger("syncwatch")
STATE_FILE = Path("syncwatch_state.json")

def load_state():
    if STATE_FILE.exists(): return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WEB SERVER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ICalHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)
    def log_message(self, format, *args): pass
    def do_GET(self):
        if self.path in ["/", "/health"]:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"SyncWatch running — {len(APARTMENTS)} apartments\n".encode())
            return
        super().do_GET()

def start_web_server():
    OUTPUT_DIR.mkdir(exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), ICalHandler)
    log.info(f"🌐 Web server on port {PORT}")
    server.serve_forever()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GOOGLE CALENDAR — reads credentials from environment variable
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_gcal_service = None

def get_gcal_service():
    global _gcal_service
    if _gcal_service: return _gcal_service
    try:
        import base64
        creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_raw:
            log.error("GOOGLE_CREDENTIALS environment variable not set")
            return None
        # Support both base64-encoded and raw JSON
        try:
            creds_info = json.loads(base64.b64decode(creds_raw).decode())
        except Exception:
            creds_info = json.loads(creds_raw)
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _gcal_service = build("calendar", "v3", credentials=creds)
        log.info("✅ Google Calendar connected")
    except Exception as e:
        log.error(f"Google Calendar connection failed: {e}")
    return _gcal_service

def sync_to_google_calendar(cal_id, all_bookings, apt_name):
    svc = get_gcal_service()
    if not svc: return
    try:
        result = svc.events().list(calendarId=cal_id, singleEvents=True).execute()
        existing = {e["summary"].replace(" [SW]", "").strip(): e["id"] for e in result.get("items", [])}
        current_keys = {f"{b['start']}_{b['end']}_{b['summary']}" for b in all_bookings}

        # Add new bookings
        for b in all_bookings:
            key = f"{b['start']}_{b['end']}_{b['summary']}"
            if key not in existing:
                event = {
                    "summary": f"{b['summary']} [SW]",
                    "start": {"date": b["start"].strftime("%Y-%m-%d")},
                    "end":   {"date": b["end"].strftime("%Y-%m-%d")},
                }
                svc.events().insert(calendarId=cal_id, body=event).execute()
                log.info(f"    📅 Added to Google Cal: {b['start']} → {b['end']}")

        # Remove cancelled bookings
        for summary, event_id in existing.items():
            if summary not in current_keys:
                svc.events().delete(calendarId=cal_id, eventId=event_id).execute()
                log.info(f"    🗑  Removed from Google Cal: {summary}")

    except Exception as e:
        log.warning(f"  Google Calendar sync failed for {apt_name}: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ICAL FETCHING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_ical(url):
    bookings = []
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "SyncWatch/1.0"})
        resp.raise_for_status()
        cal = Calendar.from_ical(resp.text)
        for component in cal.walk():
            if component.name == "VEVENT":
                dtstart = component.get("DTSTART")
                dtend = component.get("DTEND")
                if dtstart and dtend:
                    start = dtstart.dt
                    end = dtend.dt
                    if isinstance(start, datetime): start = start.date()
                    if isinstance(end, datetime): end = end.date()
                    bookings.append({"uid": str(component.get("UID", "")), "summary": str(component.get("SUMMARY", "Blocked")), "start": start, "end": end})
    except Exception as e:
        log.warning(f"  Failed: {url[:55]}... → {e}")
    return bookings

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFLICT DETECTION & ICAL GENERATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def dates_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end

def find_conflicts(ab, bk):
    return [{"airbnb": a, "booking": b} for a in ab for b in bk if dates_overlap(a["start"], a["end"], b["start"], b["end"])]

def generate_ical(bookings, calendar_name):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SyncWatch//EN",
             f"X-WR-CALNAME:{calendar_name}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for b in bookings:
        lines += ["BEGIN:VEVENT", f"UID:{b['uid'] or 'sw-' + str(b['start'])}",
                  f"DTSTART;VALUE=DATE:{b['start'].strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{b['end'].strftime('%Y%m%d')}",
                  f"SUMMARY:{b['summary']} [SyncWatch]",
                  f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

def save_ical_files(name, ab, bk):
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe = name.lower().replace(" ", "_")
    Path(OUTPUT_DIR / f"{safe}_for_booking.ics").write_text(generate_ical(ab, f"{name} (Airbnb blocks)"))
    Path(OUTPUT_DIR / f"{safe}_for_airbnb.ics").write_text(generate_ical(bk, f"{name} (Booking blocks)"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ALERTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        log.info("  📱 Telegram sent.")
    except Exception as e:
        log.warning(f"  Telegram failed: {e}")

def send_email(subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD: return
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER; msg["To"] = EMAIL_RECEIVER; msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls(); s.login(EMAIL_SENDER, EMAIL_PASSWORD); s.send_message(msg)
    except Exception as e:
        log.warning(f"  Email failed: {e}")

def alert(subject, body):
    log.warning(f"  🚨 {subject}")
    send_telegram(f"🚨 {subject}\n\n{body}")
    send_email(subject, body)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN SYNC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def sync_apartment(apt, state):
    name = apt["name"]
    log.info(f"  Checking: {name}")

    ab = fetch_ical(apt["airbnb_ical"])
    bk = fetch_ical(apt["booking_ical"])
    log.info(f"    Airbnb: {len(ab)} | Booking: {len(bk)}")

    save_ical_files(name, ab, bk)
    sync_to_google_calendar(apt["google_cal_id"], ab + bk, name)

    prev    = state.get(name, {})
    prev_ab = set(prev.get("airbnb_uids", []))
    prev_bk = set(prev.get("booking_uids", []))
    known   = prev.get("known_conflicts", [])

    # New bookings
    for nb in [b for b in ab if b["uid"] not in prev_ab]:
        alert(f"New Airbnb booking: {name}", f"Apartment: {name}\nDates: {nb['start']} → {nb['end']}\nGuest: {nb['summary']}")

    for nb in [b for b in bk if b["uid"] not in prev_bk]:
        alert(f"New Booking.com booking: {name}", f"Apartment: {name}\nDates: {nb['start']} → {nb['end']}\nGuest: {nb['summary']}")

    # Cancellations
    for uid in set(prev_ab) - {b["uid"] for b in ab}:
        alert(f"❌ Cancellation on Airbnb: {name}", f"Apartment: {name}\nA booking was cancelled on Airbnb.\nGoogle Calendar updated — Booking.com will sync automatically.")

    for uid in set(prev_bk) - {b["uid"] for b in bk}:
        alert(f"❌ Cancellation on Booking.com: {name}", f"Apartment: {name}\nA booking was cancelled on Booking.com.\nGoogle Calendar updated — Airbnb will sync automatically.")

    # Double bookings
    conflicts = find_conflicts(ab, bk)
    for c in conflicts:
        key = f"{c['airbnb']['uid']}_{c['booking']['uid']}"
        if key not in known:
            alert(f"⚠️ DOUBLE BOOKING: {name}", f"Apartment: {name}\n\nAirbnb:      {c['airbnb']['start']} → {c['airbnb']['end']}\nBooking.com: {c['booking']['start']} → {c['booking']['end']}\n\nACTION NEEDED: Cancel one booking immediately.")

    return {
        "airbnb_uids":     [b["uid"] for b in ab],
        "booking_uids":    [b["uid"] for b in bk],
        "known_conflicts": [f"{c['airbnb']['uid']}_{c['booking']['uid']}" for c in conflicts],
        "last_checked":    datetime.now().isoformat(),
    }

def run_sync():
    log.info("=" * 50)
    log.info(f"SyncWatch — {len(APARTMENTS)} apartments")
    log.info("=" * 50)
    state = load_state()
    for apt in APARTMENTS:
        state[apt["name"]] = sync_apartment(apt, state)
    save_state(state)
    log.info(f"✅ Done. Next sync in {REFRESH_INTERVAL // 60} min.")

def sync_loop():
    while True:
        try:
            run_sync()
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    if not LIBS_OK:
        print("Run: pip install icalendar requests google-api-python-client google-auth")
        exit(1)
    OUTPUT_DIR.mkdir(exist_ok=True)
    threading.Thread(target=start_web_server, daemon=True).start()
    log.info("🏠 SyncWatch starting...")
    sync_loop()
