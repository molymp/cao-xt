<?php


          // Mit diesem Tool hat der Benutzer die Moeglichkeit, CSV-Dateien
          // in bestehende Datenbanken zu uebertragen.

          // In erster Linie wurde diese Anwendung entwickelt, um Dateien
          // (CSV, Text), die in externen Programmen entstehen
          // (Tabellenkalkulation, Warenwirtschaft, Produktdatenbanken)
          // und die regelmaessig in eine MySQL-Datenbank auf dem Web-Server
          // uebertragen werden muessen, einfach und auf Knopfdruck zu
          // konvertieren.

          // Voraussetzung ist, dass sich die in die MySQL-Datenbank zu
          // importierende Datei auf dem Webserver befindet. Das heisst,
          // die Datei muss zuvor mit Hilfe eines FTP-Programms auf den
          // Server uebertragen werden.

          // Beim Aufruf des Scripts wird ein Select-Menue erzeugt, das auf
          // den folgenden Eintraegen basiert. Jeder Block stellt ein
          // Eintrag im Menue dar.
          // Sollen mehrere Eintraege definiert werden, muessen die folgenden
          // Definitions-Bloecke 'entkommentiert' werden.

          // Beim Ausfuehren des Scripts wird der Inhalt der CSV direkt in die
          // Datenbank uebertragen.

          // Wichtig: Um die Daten erfolgreich in die Datenbank uebertragen zu
          // koennen, muss eine passende Tabelle bereits bestehen.

          // Auch wichtig: Mit dem Import der Daten aus Ihrer Datei, werden die
          // gesamten Daten, die sich in der Datenbank befinden, geloescht und
          // durch die neuen Daten ersetzt.



          // Definition der Datenbanken und csv-Dateien

          $db_MenuTitle[0]  = "Eintrag 1";         // Bezeichnung des Eintrags - erscheint im Dropdown
          $db_Hostname[0]   = "localhost";         // Datenbank-Host (muss nicht zwingend immer localhost sein)
          $db_UserName[0]   = "";                  // Benutzername f&uuml;r diese Datenbank
          $db_Password[0]   = "";                  // Zugehoeriges Passwort
          $db_Database[0]   = "";                  // Datenbank, auf die zugegriffen werden soll
          $db_Table[0]      = "";                  // Table, in den die CSV-Datei &uuml;bertragen werden soll
          $db_File[0]       = "";                  // Verzeichnispfad zur Textdatei (CSV etc.) auf dem Webserver
          $db_Terminated[0] = ";";                 // Trennzeichen, das in der Textdatei verwendet wird


          //$db_MenuTitle[1]  = "";
          //$db_Hostname[1]   = "localhost";
          //$db_UserName[1]   = "";
          //$db_Password[1]   = "";
          //$db_Database[1]   = "";
          //$db_Table[1]      = "";
          //$db_File[1]       = "";
          //$db_Terminated[1] = ";";


          //$db_MenuTitle[2]  = "";
          //$db_Hostname[2]   = "localhost";
          //$db_UserName[2]   = "";
          //$db_Password[2]   = "";
          //$db_Database[2]   = "";
          //$db_Table[2]      = "";
          //$db_File[2]       = "";
          //$db_Terminated[2] = ";";


          //$db_MenuTitle[3]  = "";
          //$db_Hostname[3]   = "localhost";
          //$db_UserName[3]   = "";
          //$db_Password[3]   = "";
          //$db_Database[3]   = "";
          //$db_Table[3]      = "";
          //$db_File[3]       = "";
          //$db_Terminated[3] = ";";


          //$db_MenuTitle[4]  = "";
          //$db_Hostname[4]   = "localhost";
          //$db_UserName[4]   = "";
          //$db_Password[4]   = "";
          //$db_Database[4]   = "";
          //$db_Table[4]      = "";
          //$db_File[4]       = "";
          //$db_Terminated[4] = ";";


          //$db_MenuTitle[5]  = "";
          //$db_Hostname[5]   = "localhost";
          //$db_UserName[5]   = "";
          //$db_Password[5]   = "";
          //$db_Database[5]   = "";
          //$db_Table[5]      = "";
          //$db_File[5]       = "";
          //$db_Terminated[5] = ";";










































    if (isset ($select_db)) {


            // Connect zur Datenbank
            mysql_connect($db_Hostname[$select_db], $db_UserName[$select_db], $db_Password[$select_db]) || die("Can't Connect to Database: ".mysql_error());
            mysql_select_db($db_Database[$select_db]);

            // Bisherige Daten aus der Datenbank l&ouml;schen
            $del = "DELETE FROM ".$db_Table[$select_db];

            // CSV-Datei in die Datenbank &uuml;bertragen
            $sql = "LOAD DATA INFILE '$db_File[$select_db]' REPLACE INTO TABLE ".$db_Table[$select_db]." FIELDS TERMINATED BY '$db_Terminated[$select_db]'";

            // MySQL-Statements ausf&uuml;hren
            if (mysql_query ($del) and mysql_query ($sql)) {
                $message = "&Uuml;bertragung erfolgreich";
                }
            else {
                $message = "&Uuml;bertragung fehlgeschlagen. Grund: ". mysql_error ();
                }


            }




      // Generierung des DropDown-Menues

      function generate_dropdown () {

          global $db_MenuTitle, $db_Hostname, $db_UserName, $db_Password, $db_Table, $db_File, $db_Terminated;


          if (is_array ($db_MenuTitle)) {

              reset ($db_MenuTitle);

              while (list ($key, $val) = each ($db_MenuTitle)) {
                  echo "<option value=\"".$key."\">".$val."</option>";
                  }

              }

          }


?>



<html>
  <head>
    <title>CSV to SQL</title>
  </head>
  <body bgcolor="#EAEAEA">
    <form action="<?php echo $PHP_SELF; ?>" method="POST">
      <table border="0" cellspacing="0" cellpadding="5" bgcolor="#C0C0C0" width="50%">
        <tr>
          <th>CSV to MySQL</th>
          <th>&nbsp;</th>
        </tr>
        <tr valign="bottom">
          <td>
            <select name="select_db" size="<?php echo count ($db_MenuTitle); ?>">
              <?php generate_dropdown (); ?>
            </select>
          </td>
          <td>
            <input type="Submit" name="submit" value="Und los!">
          </td>
        </tr>
      </table>
    </form>

    <p><?php echo $message; ?></p>

    <table border="0" cellspacing="0" cellpadding="5" bgcolor="#C0C0C0" width="50%">
      <tr>
        <td>
          <p>
            Mit diesem Tool hat der Benutzer die Moeglichkeit, CSV-Dateien
            in eine bestehende MySQL-Datenbank zu uebertragen.
            In erster Linie wurde diese Anwendung entwickelt, um Dateien
            (CSV, Text), die in externen Programmen entstehen
            (Tabellenkalkulation, Warenwirtschaft, Produktdatenbanken)
            und die regelmaessig in eine MySQL-Datenbank auf dem Web-Server
            uebertragen werden muessen, einfach und auf Knopfdruck zu
            konvertieren.
          </p>

          <p>
            Beim Aufruf des Scripts wird ein Select-Menue erzeugt, das auf
            den folgenden Eintraegen basiert. Jeder Block stellt ein
            Eintrag im Menue dar.
            Sollen mehrere Eintraege definiert werden, muessen die folgenden
            Definitions-Bloecke 'entkommentiert' werden.
          </p>

          <p>
            Beim Ausf&uuml;hren des Scripts wird der Inhalt der CSV direkt in die
            Datenbank uebertragen.
          </p>

          <p>
            Wichtig: Um die Daten erfolgreich in die Datenbank uebertragen zu
            koennen, muss eine passende Tabelle bereits bestehen und die Datei
            muss sich auf dem Server befinden. Die alten
            Daten werden dabei komplett gel&ouml;scht und durch die neuen Daten
            ersetzt.
          </p>

          <p>
            Verschiedene Ausgangsdateien und Datenbanktabellen k&ouml;nnen Sie im
            Quellcode des Scripts editieren.
          </p>
        </td>
      </tr>
    </table>

  </body>
</html>

