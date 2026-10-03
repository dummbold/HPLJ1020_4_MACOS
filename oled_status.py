#!/home/pi/oled_env/bin/python3
#
# FILENAME: oled_status.py
#
# CUPS-Statusanzeige für ein SSD1306-OLED mit 128 x 32 Pixeln.
#
# Das Display gibt drei Zustände aus: IDLE. DATA und PRINT
#
# - IDLE holt Systemdaten aus dem Pi Linux und gibt sie als Laufschrift aus
#
# - DATA kommt aus der CUPS-Auftragserkennung. 
#
# - PRINT startet mit der Übertragung der Daten an den Drucker (aus CUPS).
# Dann wird f002zfs_monitor.py gestartet. Dieser Prozess überwacht 
# die Datenübertragung von und zum Drucker und reicht die Daten unverändert
# an den eigentlichen Prozess foomatic-rip weiter (man-in-the-middle). 
# Aus diesem Datenstrom liest er das Ende jedes Seitendruckes aus, das der
# Drucker sendet. Diese Information wird von oled_status.py verarbeitet,
# um eine synchronisierte Seitenzählung am Display auszugeben.
#
##################################################################################

import os
import re
import socket
import subprocess
import sys
import time

import psutil
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont


# ============================================================
# KONFIGURATION
# ============================================================

I2C_PORT = 1
I2C_ADDRESS = 0x3C
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 32

PRINTER = "HP_LaserJet_1020"
PRINTER_URI = "ipp://localhost/printers/HP_LaserJet_1020"

SCROLL_SPEED = 24                 # Pixel pro Sekunde
DISPLAY_INTERVAL = 0.05           # Sekunden
CUPS_INTERVAL = 0.5               # Sekunden
STATS_INTERVAL = 5.0              # Sekunden
JOB_TEST_FILE = "/tmp/cups_oled_job.test"

# Der CUPS-Filter schreibt strukturierte EVENT-Zeilen in diese Datei.
MONITOR_LOGS = (
    "/home/pi/foo2zfs_monitor.log",
    "/tmp/foo2zfs_monitor.log",
)


# ============================================================
# SCHRIFT
# ============================================================

try:
    font_large = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24
    )
except OSError:
    try:
        font_large = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 24
        )
    except OSError:
        font_large = ImageFont.load_default()

try:
    font_small = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
    )
except OSError:
    font_small = ImageFont.load_default()


# ============================================================
# OLED
# ============================================================

serial = i2c(port=I2C_PORT, address=I2C_ADDRESS)
device = ssd1306(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)


# ============================================================
# SYSTEMINFORMATIONEN
# ============================================================

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return f"{int(f.read()) // 1000}°C"
    except (OSError, ValueError):
        return "N/A°C"


def get_system_stats():
    cpu = f"{psutil.cpu_percent(interval=0.1):.0f}%"
    ram = f"{psutil.virtual_memory().percent:.0f}%"
    disk = f"{psutil.disk_usage('/').percent:.0f}%"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    return cpu, ram, disk, ip


# ============================================================
# IPP-TESTDATEI UND CUPS-ABFRAGE
# ============================================================

def create_job_test_file():
    """Erzeugt die Abfrage für Get-Job-Attributes."""
    content = '''{
    NAME "OLED Job Status"
    OPERATION Get-Job-Attributes
    GROUP operation-attributes-tag
    ATTR charset attributes-charset utf-8
    ATTR language attributes-natural-language en
    ATTR uri printer-uri $uri
    ATTR integer job-id $job_id
    GROUP end-of-attributes-tag
}
'''
    with open(JOB_TEST_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def find_new_job():
    """Liefert die Job-ID eines nicht abgeschlossenen CUPS-Auftrags."""
    try:
        result = subprocess.run(
            ["lpstat", "-W", "not-completed", "-o", PRINTER],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        match = re.search(rf"{re.escape(PRINTER)}-(\d+)", result.stdout)
        return int(match.group(1)) if match else None
    except (OSError, subprocess.TimeoutExpired):
        return None


_last_ipp_warning = 0.0


def warn_ipp(message):
    """Begrenzt Fehlermeldungen, damit das Systemprotokoll nicht überläuft."""
    global _last_ipp_warning
    now = time.monotonic()
    if now - _last_ipp_warning >= 10:
        print(f"IPP-Abfrage: {message}", file=sys.stderr, flush=True)
        _last_ipp_warning = now


def get_job_attributes(job_id):
    """Liest CUPS-Zustand und bekannte Gesamtseitenzahl."""
    try:
        result = subprocess.run(
            [
                "ipptool", "-t", "-v", "-d", f"job_id={job_id}",
                PRINTER_URI, JOB_TEST_FILE,
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            detail = output.strip().replace("\n", " ")
            warn_ipp(detail or f"ipptool endete mit Status {result.returncode}")
            return None, 0, 0

        state_match = re.search(
            r"job-state\s+\(enum\)\s*=\s*(\w+)", output
        )
        if not state_match:
            warn_ipp("keinen job-state in der ipptool-Antwort gefunden")
            return None, 0, 0

        impressions_match = re.search(
            r"job-impressions-completed\s+\(integer\)\s*=\s*(\d+)", output
        )
        sheets_match = re.search(
            r"job-media-sheets-completed\s+\(integer\)\s*=\s*(\d+)", output
        )
        impressions = int(impressions_match.group(1)) if impressions_match else 0
        sheets = int(sheets_match.group(1)) if sheets_match else 0
        return state_match.group(1), impressions, sheets
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn_ipp(str(exc))
        return None, 0, 0


# ============================================================
# PJL-EVENTS AUS DEM CUPS-MONITORLOG
# ============================================================

EVENT_RE = re.compile(
    r"^(\S+) EVENT job_id=(\S+) type=(PJL_JOB_START|PJL_PAGE|PJL_JOB_END)"
    r"(?: value=(\d+))?(?: pages=(\d+))?$"
)
RAW_HEX_RE = re.compile(r"\bhex=([0-9a-fA-F ]+)\s*$")


def events_in_pjl_frame(frame):
    """Erkennt Ereignisse in einem vollständigen PJL-Frame."""
    events = []
    page = re.search(
        rb"@PJL\s+USTATUS\s+PAGE\b\s*[\r\n]+\s*(\d+)",
        frame,
        re.IGNORECASE,
    )
    if page:
        events.append({"type": "PJL_PAGE", "value": int(page.group(1)), "pages": None})

    job = re.search(
        rb"@PJL\s+USTATUS\s+JOB\b\s*[\r\n]+\s*(START|END)\b",
        frame,
        re.IGNORECASE,
    )
    if job:
        action = job.group(1).decode("ascii").upper()
        if action == "START":
            events.append({"type": "PJL_JOB_START", "value": None, "pages": None})
        else:
            total = re.search(rb"\bPAGES\s*=\s*(\d+)", frame, re.IGNORECASE)
            events.append({
                "type": "PJL_JOB_END",
                "value": None,
                "pages": int(total.group(1)) if total else None,
            })
    return events


class EventLogReader:
    """Liest rohe BACKCHANNEL-hex-Zeilen aus dem vorhandenen Monitorlog."""

    def __init__(self, paths):
        self.paths = paths
        self.positions = {}
        self.partial = {}
        self.buffers = {}
        self.modes = {}
        self.pending = []
        # Frühere Druckläufe nicht als aktuellen Auftrag wiederholen.
        for path in paths:
            try:
                stat = os.stat(path)
                self.positions[path] = (stat.st_ino, stat.st_size)
            except OSError:
                pass

    def _start_session(self, path, mode, job_id=None):
        self.modes[path] = mode
        self.buffers[path] = bytearray()
        self.pending.clear()

    def _add_raw_bytes(self, path, data):
        buffer = self.buffers.setdefault(path, bytearray())
        buffer.extend(data)
        while b"\x0c" in buffer:
            frame, _, remainder = buffer.partition(b"\x0c")
            buffer[:] = remainder
            if frame.strip():
                self.pending.extend(events_in_pjl_frame(bytes(frame)))

    def _process_line(self, path, line):
        if re.search(r"\bSTART job_id=(\S+?);", line):
            self._start_session(path, "structured")
            return
        if re.search(r"\bSTART;\s*Logdatei=", line):
            self._start_session(path, "raw")
            return

        mode = self.modes.get(path, "raw")
        if mode == "structured":
            match = EVENT_RE.match(line.strip())
            if match:
                stamp, job_id, kind, value, pages = match.groups()
                self.pending.append({
                    "type": kind,
                    "value": int(value) if value else None,
                    "pages": int(pages) if pages else None,
                    "job_id": job_id,
                    "stamp": stamp,
                })
            return

        if " BACKCHANNEL " not in line:
            return
        match = RAW_HEX_RE.search(line)
        if not match:
            return
        try:
            self._add_raw_bytes(path, bytes.fromhex(match.group(1)))
        except ValueError:
            return

    def poll(self):
        """Reads new monitor-log lines continuously, including while CUPS is idle."""
        for path in self.paths:
            try:
                stat = os.stat(path)
            except OSError:
                continue
            state = self.positions.get(path)
            if state is None:
                offset, carry = 0, ""
            elif state[0] != stat.st_ino or stat.st_size < state[1]:
                offset, carry = 0, ""
                self.buffers[path] = bytearray()
                self.pending.clear()
            else:
                offset = state[1]
                carry = self.partial.get(path, "")
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    text = carry + f.read()
                    new_offset = f.tell()
            except OSError:
                continue
            lines = text.split("\n")
            self.partial[path] = lines.pop()
            self.positions[path] = (stat.st_ino, new_offset)
            for line in lines:
                self._process_line(path, line.strip())

    def read_for_job(self, job_id):
        wanted = str(job_id)
        result, keep = [], []
        for event in self.pending:
            event_job_id = event.get("job_id")
            if event_job_id is None or event_job_id == wanted:
                result.append(event)
            else:
                keep.append(event)
        self.pending = keep
        return result

    def clear_pending(self):
        self.pending.clear()


# ============================================================
# DISPLAY-ICONS UND ANSICHTEN
# ============================================================

def draw_data_icon(draw, x, y, frame):
    positions = [(0, 0), (4, -2), (8, 0), (4, 2)]
    dx, dy = positions[frame % len(positions)]
    x += dx
    y += dy
    draw.rectangle([x, y, x + 8, y + 10], outline="white", fill="black")
    draw.line([x + 5, y, x + 8, y + 3], fill="white")
    draw.line([x + 5, y, x + 5, y + 3], fill="white")
    draw.line([x + 5, y + 3, x + 8, y + 3], fill="white")
    draw.line([x + 2, y + 6, x + 6, y + 6], fill="white")
    draw.line([x + 2, y + 8, x + 6, y + 8], fill="white")


def draw_data(frame):
    with canvas(device) as draw:
        draw.rectangle([0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1], fill="black")
        draw.text((0, 0), "DATA", font=font_large, fill="white")
        draw_data_icon(draw, 88, 9, frame)


def draw_print(current_page, total_pages):
    with canvas(device) as draw:
        draw.rectangle([0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1], fill="black")
        draw.text((0, 0), "PRINT", font=font_large, fill="white")

        total_text = str(total_pages) if total_pages > 0 else "?"
        page_text = f"{current_page}/{total_text}"
        try:
            page_width = font_small.getlength(page_text)
        except AttributeError:
            page_width = len(page_text) * 9
        page_x = max(76, DISPLAY_WIDTH - int(page_width) - 2)
        draw.text((page_x, 5), page_text, font=font_small, fill="white")

        left, right = 2, 125
        top, bottom = 27, 31
        draw.rectangle([left, top, right, bottom], outline="white", fill="black")
        inner_left = left + 1
        inner_right = right - 1
        inner_width = inner_right - inner_left + 1
        fraction = (
            min(1.0, current_page / total_pages) if total_pages > 0 else 0.0
        )
        filled_width = int(fraction * inner_width)
        if filled_width > 0:
            draw.rectangle(
                [inner_left, top + 1, inner_left + filled_width - 1, bottom - 1],
                fill="white",
            )


def draw_idle(text, scroll_pos):
    with canvas(device) as draw:
        draw.rectangle([0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1], fill="black")
        draw.text((int(scroll_pos), 0), text, font=font_large, fill="white")


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():
    create_job_test_file()
    event_log = EventLogReader(MONITOR_LOGS)

    phase = "IDLE"             # IDLE, DATA, PRINT oder DONE
    current_job_id = None
    total_pages = 0
    current_page = 0
    done_until = 0.0

    scroll_pos = DISPLAY_WIDTH
    last_time = time.monotonic()
    last_cups_check = 0.0
    last_stats_update = 0.0

    temp = "N/A°C"
    cpu, ram, disk, ip = "0%", "0%", "0%", "127.0.0.1"

    while True:
        now = time.monotonic()
        elapsed = now - last_time
        last_time = now
        state = None
        event_log.poll()

        # CUPS setzt die Auftragsgrenze und liefert die bekannte Gesamtzahl.
        if now - last_cups_check >= CUPS_INTERVAL:
            last_cups_check = now

            if phase == "IDLE":
                found_job_id = find_new_job()
                if found_job_id is not None:
                    current_job_id = found_job_id
                    total_pages = 0
                    current_page = 0
                    done_until = 0.0
                    phase = "DATA"

            if current_job_id is not None:
                state, impressions, sheets = get_job_attributes(current_job_id)
                total_pages = max(total_pages, impressions, sheets, current_page)

        # PJL JOB START schaltet auf PRINT; jede vollständige PAGE zählt eins.
        # PJL JOB END liefert ggf. noch den Nenner, beendet aber nicht den
        # CUPS-Auftrag: dessen Grenze kommt weiterhin aus CUPS.
        if current_job_id is not None:
            for event in event_log.read_for_job(current_job_id):
                if event["type"] == "PJL_JOB_START":
                    phase = "PRINT"
                elif event["type"] == "PJL_PAGE":
                    phase = "PRINT"
                    current_page += 1
                    total_pages = max(total_pages, current_page)
                elif event["type"] == "PJL_JOB_END" and event["pages"] is not None:
                    total_pages = max(total_pages, event["pages"])

        # CUPS bleibt die maßgebliche Auftragsgrenze. Nach dem letzten Blatt
        # bleibt die fertige Anzeige eine Sekunde sichtbar.
        if current_job_id is not None and state in ("canceled", "aborted"):
            phase = "IDLE"
            current_job_id = None
            total_pages = 0
            current_page = 0
            done_until = 0.0
            event_log.clear_pending()
        elif current_job_id is not None and state == "completed":
            if current_page > 0:
                if phase != "DONE":
                    phase = "DONE"
                    done_until = now + 1.0
            else:
                phase = "IDLE"
                current_job_id = None
                total_pages = 0
                current_page = 0
                done_until = 0.0
                event_log.clear_pending()

        if phase == "DONE" and now >= done_until:
            phase = "IDLE"
            current_job_id = None
            total_pages = 0
            current_page = 0
            done_until = 0.0
            event_log.clear_pending()

        if now - last_stats_update >= STATS_INTERVAL:
            temp = get_cpu_temp()
            cpu, ram, disk, ip = get_system_stats()
            last_stats_update = now

        if phase == "IDLE":
            scroll_text = (
                f"HP LaserJet 1020 • IDLE • {temp} • CPU {cpu} • "
                f"RAM {ram} • DISK {disk} • IP {ip}:631                 "
            )
            scroll_pos -= SCROLL_SPEED * elapsed
            try:
                text_width = font_large.getlength(scroll_text)
            except AttributeError:
                text_width = len(scroll_text) * 14
            if scroll_pos < -text_width:
                scroll_pos = DISPLAY_WIDTH
            draw_idle(scroll_text, scroll_pos)
        elif phase == "DATA":
            frame = int(now * 5) % 4
            draw_data(frame)
        elif phase in ("PRINT", "DONE"):
            draw_print(current_page, total_pages)

        time.sleep(DISPLAY_INTERVAL)


# ============================================================
# START UND AUFRÄUMEN
# ============================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        device.clear()
        try:
            os.remove(JOB_TEST_FILE)
        except FileNotFoundError:
            pass
