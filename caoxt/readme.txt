---------------------------------

 CAO-XTensions

 http://caoxt.blackheartware.com

---------------------------------

 Created by

 Black Heartware OHG
 Daniel Marcus

 http:blackheartware.com
 info@blackheartware.com

 published under GPL -
 GNU GENERAL PUBLIC LICENSE

---------------------------------

 Anpassung an CAO Version 1.4 by
 
 Wolfgang Schwarz
 http://www.imc-media.com

---------------------------------


 Haftungsausschluss:

 Weder ich, Daniel Marcus, noch die Firma
 Black Heartware OHG oder einer ihrer Angestellten
 �bernehmen irgendeine Art der Haftung f�r die
 Folgen der Verwendung dieser Software.

 DIE INSTALLATION UND BENUTZUNG DER BEILIEGENDEN
 SOFTWARE ERFOLGT AUF EIGENES RISIKO!

 Datenverluste oder andere Sch�den werden vom
 Benutzer der Software selbst verantwortet!

---------------------------------

 Sicherheitshinweis:

 Zuerst eine Testdatenbank benutzen,
 am besten ein Backup der CAO-DB.
 Diese Software ist BETA, ich kann
 nicht garantieren, dass sie zu 100%
 einwandfrei l�uft!
 Sie wurde in unserem Hause nach bestem
 Wissen und Gewissen getestet, wir selbst
 haben sie im Produktiveinsatz, aber wir
 sind nicht unfehlbar!

 SOLLTE DAS SYSTEM �BER DAS OFFENE INTERNET
 GENUTZT WERDEN: UNBEDINGT SSL-VERSCHL�SSELUNG
 NUTZEN! ANDERNFALLS WERDEN PASSW�RTER UND
 NUTZDATEN IM KLARTEXT �BERTRAGEN!

 GETESTET WURDE LEDIGLICH MIT CAO 1.2.X.X,
 EINE KOMPATIBILIT�T F�R ALLE MODULE
 MIT CAO 1.4.X.X IST NICHT GEW�HRLEISTET!

---------------------------------

 Supporthinweis:

 Die Software wird "as-is" geliefert.
 F�r kurze Fragen bin ich zu haben,
 extensiven Support kann ich nicht
 (kostenlos) leisten, Sorry!
 Falls Probleme bei der Installation
 auftreten, am besten jemand mit
 "Ahnung" fragen.
 Wer weiss, wie man einen Apache, einen
 FTP-Server und MySQL-Server aufsetzt,
 sollte bestens klarkommen.
 Sollte das nicht der Fall sein, erstmal
 in diese Themen einlesen oder jemand
 anders machen lassen!


---------------------------------

 Systemvoraussetzungen:


  - Webserver mit PHP4- oder PHP5-
    Unterst�tzung
  - MySQL-Support in PHP aktiviert
  - MySQL-Server mit CAO-DB
  - Administratorrechte und -kenntnisse
    f�r beides.


---------------------------------

 Installation:

  - Den o.g. Haftungsausschluss lesen
    und verstehen.

  - Den o.g. Sicherheitshinweis lesen
    und verstehen.

  - Den o.g. Supporthinweis lesen
    und verstehen.

  - Die o.g. Systemanforderungen
    erf�llen.

  - Das komplette Paket entpacken.

  - Alle Dateien / Ordner auf ein
    Verzeichnis des Webservers
    hochladen.

  - Die Datei caoxt.ini muss f�r den
    Webserver beschreibbar sein,
    im Zweifelsfall volle Dateirechte
    setzen: chmod 777 caoxt.ini (Linux)

  - Den Browser starten.

  - http://meinserver.irgendwas/meincaoxtordner/

  - Auf "Setup" klicken

  - Passwort "sysdba" eingeben (ohne "")

  - Die Datei caoxt.ini mit
    dem Webinterface
    an die eigenen Gegebenheiten
    anpassen.

    loc		- Serveradresse
    port	- Serverport,
              Standardport = leer
    name	- der Datenbank
    user	- MySQL Username
    pass	- MySQL Passwort
    pref	- Finger weg!

  - Auf "Weiter" klicken, CAO-XT
    legt nun ggf. die notwendingen
    Datenbanktabellen an.

  - Viel Erfolg und Spass mit
    dem System!


---------------------------------

  Bekannte Probleme:

  - php.ini -> register_globals=On verursacht Probleme,
    tempor�re L�sung: register_globals=Off (ist eh sicherer :)

  - Bescheiden kommentierter, nat�rlich gewachsener Sourcecode,
    zuviel Interface-HTML/CSS, das man auslagern m�sste.
    Falls jemand basteln will, viel Erfolg!