# Export von Facharztprotokollen nach Markdown

Dieses Projekt enthält ein Python-Skript, das nach Login alle Protokollseiten crawlt und den eigentlichen Protokolltext als eine strukturierte Markdown-Datei ausgibt.

## Voraussetzungen

1. Python-Umgebung ist eingerichtet.
2. Abhängigkeiten installieren:

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python -m pip install -r requirements.txt
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python -m playwright install chromium
```

## Erstlauf (mit interaktivem Login)

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --list-url "https://medi-pro-club.de/club/wegweiser/facharztprotokolle" \
  --output protokolle_gesamt.md \
  --max-pages 12 \
  --headful \
  --force-login \
  --verbose
```

Ablauf beim Erstlauf:
1. Browser öffnet sich.
2. Du loggst dich ein.
3. Im Terminal Enter drücken.
4. Das Skript sammelt Links und extrahiert Inhalte.

## Folgelauf (ohne erneuten Login)

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --list-url "https://medi-pro-club.de/club/wegweiser/facharztprotokolle" \
  --output protokolle_gesamt.md \
  --max-pages 12
```

Die Session wird standardmäßig in `session/storage_state.json` gespeichert.

## Update-Lauf (nur neue Protokolle laden)

Beim Crawlen wird eine IDs-Datei (`protokolle_ids.txt`) mit allen bereits geladenen Protokoll-IDs gelesen. Schon bekannte IDs werden beim Laden übersprungen, und sobald eine Listenseite nur noch bekannte IDs enthält, bricht der Crawl frühzeitig ab. Neue Protokolle werden an die bestehende Ausgabedatei angehängt (Nummerierung wird fortgesetzt) und die IDs-Datei wird danach aktualisiert.

```bash
/home/ruhri/Projekte/johanna_FA_protokolle/.venv/bin/python scripts/export_protokolle.py \
  --list-url "https://medi-pro-club.de/club/wegweiser/facharztprotokolle" \
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
| `--list-url` (erforderlich) | – | Gefilterte Listen-URL (Seite 1) nach dem Login. |
| `--output` | `protokolle_gesamt.md` | Ausgabe-Markdown-Datei; neue Protokolle werden angehängt. |
| `--session-file` | `session/storage_state.json` | Pfad zur gespeicherten Playwright-Session. |
| `--ids-file` | `protokolle_ids.txt` | Datei mit IDs bereits geladener Protokolle (wird gelesen und aktualisiert). |
| `--max-pages` | `12` | Maximale Anzahl der zu durchsuchenden Listenseiten. |
| `--min-date` | – | Nur Protokolle ab diesem Datum laden (Format `TT.MM.JJJJ`). Hat Vorrang vor `--max-pages`: der Crawl stoppt sofort, sobald ältere Protokolle gefunden werden, unabhängig davon, ob `--max-pages` schon erreicht ist. |
| `--headful` | aus | Browser sichtbar starten (nützlich zum Debuggen). |
| `--force-login` | aus | Gespeicherte Session ignorieren und interaktiv neu einloggen. |
| `--delay-seconds` | `0.35` | Wartezeit zwischen den Abrufen der Detailseiten. |
| `--timeout-ms` | `30000` | Playwright-Timeout in Millisekunden. |
| `--max-protocols` | `0` | Optionales Limit für Detailseiten (`0` = kein Limit). |
| `--verbose` | aus | Fortschritt pro Seite/Protokoll ausgeben. |
