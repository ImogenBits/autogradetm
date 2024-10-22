# autogradetm

## Installation

1. Wenn man noch kein Docker hat, das von der [Docker Seite](https://www.docker.com/) runterladen und installieren.

2. Dieses Repo runterladen.

3. Package installieren, z.B. indem man ins Repo geht und `pip install -e .` ausführt.

## Benutzung

- Die Abgaben der Studis runterladen und die zip datei entpacken. Man sollte nun einen Ordner habn, mit ganz vielen
Unterordnern die sowas wie `Tut 123 Abgabegruppe 456_3452345_assignsubmission...` heißen.

- Für Aufgabe 3 `autogradetm simulators pfad/zum/ordner` (also z.B. `autogradetm simulators .` wenn man in dem Ornder
von Oben ist) ausführen. Das versucht dann den Code von allen Gruppen auszuführen und einem zu sagen ob der richtig
läuft oder was die Fehler sind.

    - Falls gesagt wird, dass keine Code Dateien gefunden werden liegt das warscheinlich daran dass die ne Sprache
    benutzen an die ich nicht gedacht hab, dann muss man die Gruppe manuell testen.

    - Falls gesagt wird, dass man keinen entrypoint finden kann und einem Optionen gegeben werden muss man den Pfad zu
    der Datei eingeben die die main Funktion enthält (o.ä. bei Sprachen die das anders machen).

    - Falls Fehler beim Kompilieren oder Ausführen angezeigt werden ist entweder der Studi Code falsch oder man muss
    deren Sachen auf ne weirde Art ausführen. In letzterem Fall kann man die `--build-command/-b` und `--run-command/-r`
    Optionen benutzen (sinnvollerweise nur wenn man nur diese einzelne Gruppe testet). Die nehmen strings die statt den
    automatischen Befehlen benutzt werden um den Code zu compilen bzw. auszuführen. Details dazu sind auch in den
    `--help` docs.

    - Einige Studis werden warscheinlich dass I/O Format falsch machen. Das Tool hier versucht so nett wie möglich deren
    Output zu parsen, aber manche werden es sicher zu falsch machen oder den Input versuchen anders zu lesen oder
    sonstwas. Wenn es nur falsch formatierter Output ist wird der auch angezeigt damit man es selbst überprüfen kann,
    sonst muss man entweder deren I/O fixen oder manuell deren sachen ausführen.

- Für Aufgaben 4 und 5 `autogradetm tms pfad/zum/ordner` ausführen. Dann werden deren Turingmaschinen durchgetestet.

    - Falls hier ein Fehler kommt dass deren Datei falsch ist kann es sein dass die die einfach falsch formatiert haben,
    dann kann man gucken ob man es schnell fixen kann (also z.B. Kommentare löschen, sachen richtig trennen, etc.) und
    es nochmal laufen lassen.

- Bei beiden Aufgaben kann man mit `--group/-g` eine oder mehrere Gruppennummern angeben, dann werden nur die Abgaben
dieser spezifischen Gruppen getestet. Also z.B. `autogradetm tms -g 1 -g 5` um nur Gruppe 1 und 5 zu testen.
