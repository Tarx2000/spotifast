# Persönlicher Spotifast-Fork für macOS

Eine native Musik-App mit integrierter Spotify-Kompatibilität für Canopy.
Die laufende App heißt **Spotify**. Es läuft keine zusätzliche Bridge-App,
kein Hintergrunddienst und keine regelmäßige Abfrage eines zweiten Prozesses.
Die Wiedergabe und Oberfläche stammen weiterhin von Spotifast. Dies ist keine
offizielle Spotify-App und die Signatur stammt nicht von Spotify.

## Updates erhalten die Anpassungen

Der Updateknopf fragt ausschließlich `Tarx2000/spotifast` ab. Auf macOS sind
die automatische Download- und Installationsaktion gesperrt. Bei einer neuen
Version öffnet der Dialog die Veröffentlichungsseite dieses Forks. Dort die
DMG oder ZIP herunterladen, die Musik-App beenden und die App ersetzen.
Anschließend kann macOS eine Freigabe in **Datenschutz & Sicherheit → Dennoch
öffnen** verlangen. Globale Sicherheitseinstellungen werden nicht geändert.
Apple kann die angebotenen Freigabemöglichkeiten ändern; nicht jede Art von
Sicherheitswarnung lässt sich damit freigeben.

Die App ist lokal beziehungsweise im Build nur ad-hoc signiert und wird nicht
bei Apple zur Notarisierung eingereicht. Dafür ist kein Apple-Entwicklerkonto
eingerichtet. Die zusätzliche Ed25519-Signatur der Download-Prüfsummen ist
unabhängig davon und bestätigt die Herkunft vom persönlichen Buildkanal.

Eine Ausschlussliste für App-Ordner würde die Änderungen im kompilierten
Programm nicht schützen. Stattdessen enthält `patches/spotify.patch` die
komplette Änderungssammlung. Der GitHub-Workflow prüft alle sechs Stunden auf
neue stabile Originalveröffentlichungen. Er kann auch manuell gestartet werden.

Jeder neue Build beginnt mit dem unveränderten, exakt aufgelösten Original-Tag.
Der Workflow wendet die gesamte Änderungssammlung an. Er verwendet dabei
keine erzwungenen Änderungen und keinen Rückfall auf ein unverändertes Original.
Die persönlichen Workflow-, Schlüssel- und Richtliniendateien stammen immer
aus diesem Fork. Sie werden nicht durch Dateien aus dem Original ersetzt.

Danach müssen die Profil- und Kompatibilitätsprüfungen, Quelltextprüfungen,
Formatierung, Clippy, die Rust-Tests und die Dokumentationserzeugung bestehen.
Erst danach werden die App gebaut, ihre Pakete geprüft und veröffentlicht.
Ein Konflikt oder fehlgeschlagener Test beendet den Ablauf ohne neue
Veröffentlichung. Die bereits installierte Version wird dabei nicht berührt.
Solche Konflikte müssen gelegentlich angepasst werden; dies ist kein
Wartungsfreiheitsversprechen für beliebige zukünftige Originaländerungen.

Die Versionsnummer enthält eine eigene Revision: Aus Original `0.14.1` und
persönlicher Revision `1` wird `0.14.1001`. Aus `0.14.2` wird `0.14.2001`.
Eine weitere eigene Änderung auf derselben Originalversion erhöht `revision`
in `config.json`. Das verhindert, dass der Updatevergleich eine eigene
Korrektur übersieht. `upstream.json` nennt Originalversion, Commit und den
SHA-256-Wert der angewendeten Änderungssammlung.

## Vorhandene Daten

Die Profilidentität bleibt absichtlich unverändert:

- Einstellungen und Verlauf: `~/Library/Application Support/me.paolino.spotifast`
- Fensterzustand: `~/Library/Application Support/spotifast`
- Schlüsselbund-Dienst: `rocks.spotifast.Spotifast`
- Single-Instance-Steuerung: weiterhin Spotifasts eigener Slot

Der neue macOS-Auftritt verwendet dagegen `com.spotify.client`. Es wird nicht
global jeder interne Name ersetzt. Die bestehende Anmeldung wird nicht
ausgelesen oder exportiert. macOS kann beim Wechsel von der ursprünglichen
Entwicklersignatur zur eigenen Signatur eine neue Schlüsselbundfreigabe
verlangen; gegebenenfalls muss die Spotify-Anmeldung wiederholt werden.
Bestehende benutzerdefinierte Connect-Gerätenamen bleiben unverändert. Der
ursprüngliche Standardname wird nur für die laufende Engine als Spotify
angezeigt, ohne das gespeicherte Profil umzubenennen.

Die App übernimmt Spotifasts vorhandene System-Metadatenveröffentlichung.
AppleScript-Anfragen werden direkt aus dem aktuellen Player-Zustand
beantwortet. Wiedergabe, Pause, Titelwechsel, Lautstärke, Position, Shuffle
und Wiederholung gehen an dieselbe interne Befehlswarteschlange wie andere
Bedienelemente. Die aktuelle Track-ID ist verfügbar. Titelwiedergabe mit einem
zusätzlichen AppleScript-Kontext wird ausdrücklich als nicht unterstützt
beantwortet. Apps mit weiteren proprietären Schnittstellen oder einer Prüfung
von Spotifys echter Signatur können den Fork weiterhin unterscheiden.

## Entwicklung und Wiederaufbau

Der erste Build ist auf Original `v0.14.1` gepinnt. Veröffentlicht wird derzeit
für Apple silicon. MilkDrop bleibt enthalten; dessen eigener Visualisierungs-
prozess und der bestehende Updatehelfer sind keine zusätzliche dauerhaft
laufende Kompatibilitäts-App.

Nach Änderungen an der Integration:

```sh
cargo fmt --all
python3 fork/refresh_patch.py
python3 fork/test_automation.py
python3 fork/prepare.py --tag v0.14.1 --output /absolute/path/to/new-candidate
python3 fork/verify.py
```

Der Kandidatenordner muss neu sein. Der automatische `--write`-Modus verlangt
einen sauberen Checkout und wird im kurzlebigen GitHub-Runner verwendet.
Die Originalveröffentlichung wird nur aus `crmne/spotifast` bezogen; eigene
Updates werden nur in diesem Fork veröffentlicht.

Der Workflow benötigt das Repository-Secret `PERSONAL_UPDATE_SIGNING_KEY`.
Der private Schlüssel gehört ausschließlich in dieses Secret und in eine
private lokale Sicherung, niemals ins Repository. Der öffentliche Schlüssel
liegt in `update-public-key.hex` und ist in der App eingebettet.

Ein lokales Paket lässt sich nach den Prüfungen erzeugen:

```sh
cargo build --release --locked
python3 fork/package.py --binary target/release/spotifast --output dist/personal --dmg
```

`examples/spotify-event-fixture.rs` dient ausschließlich dem isolierten
AppleScript-Test mit erfundenen Metadaten. Es öffnet kein Benutzerprofil und
ist kein Teil des ausgelieferten App-Programms.

Die Originalquellen und ihre MIT-Lizenz bleiben erhalten. Das verwendete
Icon stammt aus [Spotifys offiziellen Designressourcen](https://developer.spotify.com/documentation/design).
