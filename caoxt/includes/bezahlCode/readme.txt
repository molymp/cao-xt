-----------------------------------
Beispiel-Implementierung BezahlCode
-----------------------------------

Folgendes Archiv enthält alle nötigen Dateien um BezahlCodes zu generieren. Bitte entpacken Sie das Archiv in einen Ordner welcher von Ihrem Webserver (mit PHP-Erweiterung) erreicht werden kann und rufen Sie die Datei index.html auf.

-----------------------------------
Archiv-Inhalt:
index.html:
Enthält ein Formular welches die Eingabe von Kontodaten ermöglicht. Diese werden mittels POST-Request an die Datei bezahlcodetest.php weitergereicht

bezahlcodetest.php:
Enthält die Funktion generateBezahlCode($name, $blz, $kontonummer, $vwz, $betrag), welche eine validierte BezahlCode-URL generiert und an die PHP QR Code Bibliothek weitergibt.
Zusätzlich beinhaltet diese Datei alle Funktionen zur Validierung und Encodierung der Parameter.
Ganz am Ende befindet sich Beispielcode, welcher auf POST-Requests, wie in index.html erzeugt, reagiert.

phpqrcode:
Ordner mit angepasster Version 1.1.4 der Bibliothek PHP QR Code. Es wurde Funktionalität in qrencode.php und qrimage.php eingefügt, welche QR Codes mit der Bildunterschrift "www.BezahlCode.de" erstellt. Ist diese nicht gewünscht, kann auch die unmodifizierte Version von http://phpqrcode.sourceforge.net/ benutzt werden.

-----------------------------------
Lizenz:
Die verwendete Bibliothek PHP QR Code untersteht der LGPL 3.0. Veränderungen an dieser unterstehen allen Einschränkungen die die LGPL mit sich bringt.
Die Dateien ausserhalb des Ordners phpqrcode dürfen ohne Einschränkungen weitergegeben und modifiziert werden.