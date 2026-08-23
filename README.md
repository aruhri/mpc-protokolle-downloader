# Export von Facharztprotokollen nach Markdown

Dieses Projekt enthält ein Python-Skript, das nach Login alle Protokollseiten crawlt und den eigentlichen Protokolltext als eine strukturierte Markdown-Datei ausgibt.

## Voraussetzungen

1. Python-Umgebung ist eingerichtet.
2. Abhängigkeiten installieren:

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python -m pip install -r requirements.txt
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python -m playwright install chromium
```

## Erstlauf (mit interaktivem Login und Filter-Einrichtung)

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --output protokolle_gesamt.md \
  --max-pages 12 \
  --headful \
  --force-login \
  --verbose
```

Ablauf beim Erstlauf:
1. Browser öffnet sich (auf der Protokollliste, ggf. `--list-url` als Startpunkt).
2. Du loggst dich ein und stellst die gewünschte Filterung (Fachrichtung, Ort, Prüfer, Suche) direkt im Browser ein.
3. Im Terminal Enter drücken, sobald die gefilterte Liste sichtbar ist.
4. Das Skript speichert die tatsächlich genutzte, gefilterte URL in `session/list_url.txt` und sammelt anschließend Links und extrahiert Inhalte.

Optional kannst du mit `--list-url "..."` eine URL als Startpunkt vorgeben (z. B. um beim ersten Aufruf schneller zur richtigen Fachrichtung zu gelangen); die Filterung selbst nimmst du aber im Browser vor.

## Folgelauf (ohne erneuten Login, ohne --list-url)

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --output protokolle_gesamt.md \
  --max-pages 12
```

Die Session wird standardmäßig in `session/storage_state.json`, die gefilterte Listen-URL in `session/list_url.txt` gespeichert und automatisch wiederverwendet. `--list-url` ist danach nicht mehr nötig.

## Update-Lauf (nur neue Protokolle laden)

Beim Crawlen wird eine IDs-Datei (`protokolle_ids.txt`) mit allen bereits geladenen Protokoll-IDs gelesen. Schon bekannte IDs werden beim Laden übersprungen, und sobald eine Listenseite nur noch bekannte IDs enthält, bricht der Crawl frühzeitig ab. Neue Protokolle werden an die bestehende Ausgabedatei angehängt (Nummerierung wird fortgesetzt) und die IDs-Datei wird danach aktualisiert.

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --output protokolle_gesamt.md \
  --max-pages 12
```

So kann die Liste jederzeit einfach aktualisiert werden, ohne alle Protokolle erneut zu laden.

## Ergebnisformat

Die Ausgabe enthält für jedes Protokoll Datum und Prüfer aus der Listenansicht sowie den extrahierten Inhalt:

```markdown
## Protokoll 1

**Datum:** 06.07.1825
**Prüfer:** Dr. med. Wurst (Vorsitz), Dr. Hammer

...extrahierter Markdown-Text...
```

Es wird nur der Protokollinhalt aus dem Quill-Editor übernommen.

## Nützliche Optionen

- `--max-protocols 5` für Testläufe.
- `--delay-seconds 0.5` für langsameren Abruf.
- `--session-file session/custom_state.json` für alternative Session-Datei.
- `--ids-file protokolle_ids.txt` für alternative Datei mit bereits geladenen IDs.
- `--min-date 01.01.2026` um nur Protokolle ab diesem Datum zu laden.

## Alle Optionen

| Option | Standard | Beschreibung |
| --- | --- | --- |
| `--list-url` | – | Optionaler Startpunkt für den ersten Lauf bzw. `--force-login`. Die im Browser tatsächlich eingestellte, gefilterte URL wird danach automatisch in `--list-url-file` gespeichert und wiederverwendet. |
| `--output` | `protokolle_gesamt.md` | Ausgabe-Markdown-Datei; neue Protokolle werden angehängt. |
| `--session-file` | `session/storage_state.json` | Pfad zur gespeicherten Playwright-Session. |
| `--ids-file` | `protokolle_ids.txt` | Datei mit IDs bereits geladener Protokolle (wird gelesen und aktualisiert). |
| `--list-url-file` | `session/list_url.txt` | Datei mit der zuletzt genutzten, gefilterten Listen-URL (wird gelesen und aktualisiert). |
| `--max-pages` | `12` | Maximale Anzahl der zu durchsuchenden Listenseiten. |
| `--min-date` | – | Nur Protokolle ab diesem Datum laden (Format `TT.MM.JJJJ`). Hat Vorrang vor `--max-pages`: der Crawl stoppt sofort, sobald ältere Protokolle gefunden werden, unabhängig davon, ob `--max-pages` schon erreicht ist. |
| `--headful` | aus | Browser sichtbar starten (nützlich zum Debuggen). |
| `--force-login` | aus | Gespeicherte Session ignorieren und interaktiv neu einloggen. |
| `--delay-seconds` | `0.35` | Wartezeit zwischen den Abrufen der Detailseiten. |
| `--timeout-ms` | `30000` | Playwright-Timeout in Millisekunden. |
| `--max-protocols` | `0` | Optionales Limit für Detailseiten (`0` = kein Limit). |
| `--verbose` | aus | Fortschritt pro Seite/Protokoll ausgeben. |
