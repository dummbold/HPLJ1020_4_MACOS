>🇺🇸🇬🇧🇫🇷🇪🇸🇮🇹🇪🇺🇺🇦🇦🇺🇫🇮🇨🇿🇧🇷🇨🇦🇰🇿🇨🇴🇲🇶🇳🇬🇸🇨🇪🇭🇺🇾🇺🇬🏳️🏴‍☠️
>
>_International users:_
>
>_This Text is intentionally written in german language. Please use your Browsers translation feature. A translation from german into other languages mainly generates better results then a translation from any language (especially english) into german due to the linguistic specifications of the languages. German is one of the most complex languages that can easily be auto-translated into less complex languages. Thanks for your compliance an let me know your experience._
>
---


# HPLJ1020_4_MACOS

Hier findet ihr eine Anleitung und ein bisschen Software um einen alten HP LaserJet 1020 (Baujahr 2005) weiterhin zu betreiben, auch wenn MacOS ab V27 (Golden Gate) den alten Druckertreiber HP LaserJet 1022 V1.6.1 nicht mehr unterstützt. Er ist damit auch AirPrint-fähig!

Dazu müsst ihr einen CUPS-Druckerserver auf einem Raspberry Pi aufsetzen. Dabei gibt es zwei Kleinigkeiten zu beachten, die ich im Wiki beschreibe. Bei Aufsetzen lasst euch von der KI helfen. Das besondere an meinem CUPS-Server ist ein kleines OLED-Display, dass Systemdaten und auch den Druckerstatus anzeigt - ein Feature, das ich beim Drucker selbst schmerzhaft vermisst habe. Der hat ja nur eine LED die anzeigt dass er eingeschaltet ist.

Lest einfach alle Details im [**Wiki**](https://github.com/dummbold/HPLJ1020_4_MACOS/wiki)

---

**Neu in MacOS 27.0.1:**

Wenn ihr AirPrint aktiviert habt melden sich beim ersten Druckjob zwei Drucker: einer direkt über Bonjour und einer als Netzwerkdrucker. Bitte den Bonjour Drucker unbedingt löschen! Bei mir konnte CUPS nicht drucken wenn beide Drucker angelegt waren. Der Netzwerkdrucker alleine funktioniert problemlos. Das Schöne: er wird in MacOS automatisch als Netzwerkdrucker erkannt und sofort korrekt eingerichtet. Ihr brauche ihn NICHT manuell anlegen!

**Neu in MacOS 27.2.x:**
Wie ich inzwischen mitbekommen habe lag die mangelnde Unterstützung des Druckertreibers einfach daran, dass in MacOS 27 Rosetta (Laufzeitumgebung für ältere Software) zunächst nicht automatisch mitinstalliert wurde. Mit einer händischen Installation hätte ich den Drucker ganz normal wieder zum Laufen gebracht. Das wusste ich damals aber nicht und setzte den Server auf. Ab Version 27.2. soll Rosetta wohl weiterhin installiert bleiben. Aber jetzt habe ich den Server aufgesetzt und er läuft. Ein paar Kinderkrankheiten treibe ich ihm noch aus. Und wer weiß - irgendwann wird Apple Rosetta ganz aufgeben. Mein CUPS-Server läuft weiter.

**Bugfix am 17.11.2026:**
Beim Drucken über AirPrint wurden mehrfach ungültige Attribute für das Druckende an den Server gereicht. Es wurde eine geplante Seite gedruckt. Der Druckerserver wartete auf eine zweite Seite – die aber nie gesendet wurde - und das Display fror quasi ein. Ein kleiner Bugfix bereitet diesem Treiben ein Ende. Da das Problem nicht immer auftrat kann ich es schlecht überprüfen und bin auf eure Mithilfe angewiesen. Bitte installiert die aktuelle Version der _oled_status.py_ und probiert AirPrint aus.



[hpljcupsdisplay.webm](https://github.com/user-attachments/assets/8a37256c-d5c6-4891-83c9-5749d2a5ec92)

Das Video ist ungeschnitten und in Originalgeschwindigkeit, aber leicht gekürzt. Nach PRINT folgt wieder die IDLE-Anzeige.


 
    UPDATE 5 - 17.11.2026/17:00 Uhr
