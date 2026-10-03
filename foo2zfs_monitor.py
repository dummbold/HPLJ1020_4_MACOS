#!/usr/bin/env python3
#
# FILENAME: foo2zfs.py
#
# CUPS Filter für oled_status.py
#
# Das Programm nimmt den Datenstrom von CUPS und leitet ihn an foomatic-rip weiter,
# liest dabei aber die Information für das Ende einer Druckseite aus dem
# Backchannel des Druckers und leitet sie an oled_status.py weiter.
#
# Nicht direkt in einer Shell starten!
# Programm wird automatisch gestartet und beendet sobald Daten von CUPS 
# in Richtung des Druckers gesendet werden bzw. das letzte Blatt gedruckt wurde.
####################################################################################

import fcntl
import os
import re
import select
import subprocess
import sys
import threading
import time
from datetime import datetime


REAL_FOOMATIC_RIP = "/usr/lib/cups/filter/foomatic-rip"
BACKCHANNEL_FD = 3

LOG_FILE = "/home/pi/foo2zfs_monitor.log"
FALLBACK_LOG_FILE = "/tmp/foo2zfs_monitor.log"

READ_CHUNK_SIZE = 8192
JOB_END_TIMEOUT = 30.0
QUERY_REPLY_GRACE = 2.0

UEL = b"\x1b%-12345X"
ACTIVE_QUERIES = (
    ("INFO STATUS", UEL + b"@PJL INFO STATUS\r\n" + UEL),
    ("INFO PAGECOUNT", UEL + b"@PJL INFO PAGECOUNT\r\n" + UEL),
)

stop_reader = threading.Event()
job_end_seen = threading.Event()
log_lock = threading.Lock()
log_fd = None
log_path = None


def open_log():
    global log_fd, log_path
    for path in (LOG_FILE, FALLBACK_LOG_FILE):
        try:
            log_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
            log_path = path
            return
        except OSError:
            continue
    log_fd = None
    log_path = None


def log(message):
    stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    line = f"{stamp} {message}\n"
    with log_lock:
        if log_fd is not None:
            try:
                os.write(log_fd, line.encode("utf-8", errors="replace"))
            except OSError:
                pass
    # DEBUG prefix prevents CUPS interpreting monitor output as PAGE/STATE.
    print(f"DEBUG: foo2zfs_monitor: {message}", file=sys.stderr, flush=True)


def decode_bytes(data):
    text = data.decode("latin-1", errors="replace")
    escaped = text.encode("unicode_escape").decode("ascii")
    return f"text={escaped!r} hex={data.hex(' ')}"


def backchannel_is_readable():
    try:
        flags = fcntl.fcntl(BACKCHANNEL_FD, fcntl.F_GETFL)
        return (flags & os.O_ACCMODE) != os.O_WRONLY
    except OSError:
        return False


def backchannel_reader():
    rolling = b""
    log(f"BACKCHANNEL lauscht auf fd {BACKCHANNEL_FD}")

    while not stop_reader.is_set():
        try:
            ready, _, _ = select.select([BACKCHANNEL_FD], [], [], 0.25)
            if not ready:
                continue
            data = os.read(BACKCHANNEL_FD, READ_CHUNK_SIZE)
            if not data:
                log("BACKCHANNEL EOF")
                return
        except (OSError, ValueError) as exc:
            log(f"BACKCHANNEL-Lesefehler: {exc}")
            return

        log("BACKCHANNEL " + decode_bytes(data))
        upper = data.upper()
        old_rolling = rolling
        rolling = (rolling + upper)[-2048:]

        if b"@PJL USTATUS PAGE" in upper and b"@PJL USTATUS PAGE" not in old_rolling:
            log("ERKANNT: unsolicited PJL PAGE-Meldung")

        if re.search(rb"@PJL\s+USTATUS\s+JOB(?:[ \t]+|[\r\n]+)END\b", rolling):
            if not job_end_seen.is_set():
                log("ERKANNT: unsolicited PJL JOB END-Meldung")
                job_end_seen.set()

        if b"@PJL INFO STATUS" in upper:
            log("ERKANNT: PJL INFO STATUS-Antwort")
        if b"@PJL INFO PAGECOUNT" in upper:
            log("ERKANNT: PJL INFO PAGECOUNT-Antwort")


def run_foomatic_rip():
    """Ruft foomatic-rip mit den CUPS-Argumenten auf und reicht ZjStream durch."""
    command = [REAL_FOOMATIC_RIP] + sys.argv[1:]
    log(f"Starte Originalfilter: {REAL_FOOMATIC_RIP}")

    try:
        child = subprocess.Popen(
            command,
            stdin=sys.stdin.buffer,
            stdout=subprocess.PIPE,
            # Originale CUPS-/Foomatic-Meldungen unverändert weiterreichen.
            stderr=None,
            close_fds=True,
            bufsize=0,
        )
    except OSError as exc:
        log(f"Kann foomatic-rip nicht starten: {exc}")
        return 127

    try:
        while True:
            chunk = child.stdout.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    except BrokenPipeError:
        child.terminate()
        child.wait()
        log("CUPS hat die Ausgabe-Pipe geschlossen")
        return 1
    finally:
        if child.stdout:
            child.stdout.close()

    return child.wait()


def send_active_queries():
    for name, query in ACTIVE_QUERIES:
        log(f"AKTIVE PJL-ABFRAGE wird gesendet: {name}")
        sys.stdout.buffer.write(query)
        sys.stdout.buffer.flush()
        time.sleep(0.15)


def wait_for_printer_end():
    """Wartet auf PJL JOB END oder das Diagnose-Zeitlimit."""
    deadline = time.monotonic() + JOB_END_TIMEOUT
    grace_deadline = time.monotonic() + QUERY_REPLY_GRACE

    while time.monotonic() < deadline:
        if job_end_seen.is_set() and time.monotonic() >= grace_deadline:
            log("Warteende durch PJL JOB END")
            return
        time.sleep(0.1)

    if job_end_seen.is_set():
        log("PJL JOB END erkannt")
    else:
        log(f"Zeitlimit {JOB_END_TIMEOUT:.1f}s; kein PJL JOB END erkannt")


def main():
    # CUPS-Filter werden mit Job-ID, Benutzer, Titel, Kopien und Optionen
    # gestartet. Ohne diese Argumente ist dies kein CUPS-Aufruf.
    if len(sys.argv) < 6:
        print(
            "foo2zfs_monitor.py ist ein CUPS-Filter und darf nicht direkt "
            "aus der Shell gestartet werden.",
            file=sys.stderr,
        )
        return 2

    open_log()
    log(f"START; Logdatei={log_path or 'keine beschreibbare Logdatei'}")

    # Wenn CUPS fd 3 nicht bereitstellt, trotzdem normal drucken:
    # In diesem Fall wird nur der Monitor übersprungen.
    has_backchannel = backchannel_is_readable()
    reader = None
    if has_backchannel:
        reader = threading.Thread(target=backchannel_reader, daemon=True)
        reader.start()
    else:
        log("Kein lesbarer CUPS-Backchannel auf fd 3; nur Durchleitung")

    try:
        # Passiv PJL USTATUS PAGE/JOB mitschneiden, während foomatic-rip läuft.
        child_status = run_foomatic_rip()
        log(f"foomatic-rip beendet mit Status {child_status}")

        if child_status == 0 and has_backchannel:
            # foo2zjs hat seinen PJL/ZjStream-Job beendet; danach abfragen.
            send_active_queries()
            wait_for_printer_end()

        return child_status

    except Exception as exc:
        log(f"MONITOR-FEHLER: {type(exc).__name__}: {exc}")
        return 1

    finally:
        stop_reader.set()
        if reader is not None:
            reader.join(timeout=1.0)
        if log_fd is not None:
            try:
                os.close(log_fd)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
