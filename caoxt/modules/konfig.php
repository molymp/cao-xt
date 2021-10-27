<?php

$o_head = "Konfiguration";
$o_navi = "";


// HAUPTPROGRAMM

    if((!$_GET['action']) || ($_GET['action']=="login"))
      {
        // Header: main.php?section=".$_GET['section']."&module=konfig&action=login

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                    <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">";

        if($_SESSION['error'])  // Gab es eine Fehlermeldung, die hierher geführt hat?
          {
            switch($_SESSION['error'])
              {
                case 1000: $e_msg = "Keine Zugangsdaten für die Datenbank!"; break;
                case 1001: $e_msg = "Datenbank konnte nicht ge&ouml;ffnet werden!"; break;
                case 1002: $e_msg = "Datenbankserver nicht erreichbar!"; break;
                case 1003: $e_msg = "Keine Konfigurationsdatei vorhanden!"; break;
                case 1003: $e_msg = "PHP konnte die MySQL-Erweiterung nicht laden!"; break;
              }

            $o_cont .= "Das Konfigurationsmodul wurde gestartet, weil folgendes Problem<br>
                        aufgetreten ist: ".$_SESSION['error'].": ".$e_msg."<br><br>";

            unset($_SESSION['error']);
          }

        $o_cont .= "<br><br><br><br>
                    Um die Grundeinstellungen &auml;ndern zu k&ouml;nnen, m&uuml;ssen Sie<br>
                    zun&auml;chst das Supervisorkennwort eingeben:
                    <br><br><br><br>
                     <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                      <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Login</h1></td></tr>
                      <tr><td bgcolor=\"#808080\" align=\"center\">
                       <form action=\"main.php?section=".$_GET['section']."&module=konfig&action=edit\" method=\"post\"><br>
                        Passwort: <input name=\"ini_pass\" size=\"20\" type=\"password\"><br><br>
                        <input type=\"submit\" name=\"login\" value=\"Anmelden\">
                       </form>
                      </td></tr>
                     </table>";

        $o_cont .= "<br><br><br><br>
                    </td></tr>
                    </table>";
      }
    elseif($_GET['action']=="edit")
      {
        // Header: main.php?section=".$_GET['section']."&module=konfig&action=edit

        unset($_SESSION['error']);

        if(!$ini_pass)
          {
            $ini_pass = "7dde970410241b5241717ea841a82fc8"; // Kein Passwort? -> Passwort = sysdba
          }

        if(md5($_POST['ini_pass'])==$ini_pass)
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         <table width=\"300\" cellpadding=\"0\" cellspacing=\"1\">
                          <form action=\"main.php?section=".$_GET['section']."&module=konfig&action=submit\" method=\"post\">
                           <input type=\"hidden\" name=\"ini_pass\" value=\"".$_POST['ini_pass']."\">
                           <tr>
                            <td colspan=\"2\">
                             <b>Datenbankoptionen</b>
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-Adresse:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"loc\" size=\"20\" value=\"".$db_loc."\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-Port:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"port\" size=\"20\" value=\"".$db_port."\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-Name:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"name\" size=\"20\" value=\"".$db_name."\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-Benutzer:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"user\" size=\"20\" value=\"".$db_user."\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-Passwort:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"pass\" size=\"20\" value=\"".$db_pass."\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;DB-K&uuml;rzel:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"text\" name=\"pref\" size=\"20\" value=\"".$db_pref."\">
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             &nbsp;
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             <b>Moduloptionen</b>
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;Navigation Journale:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <select name=\"navstyle\" size=\"1\">";
            if($ini_navstyle=="classic")
              {
                 $o_cont .=  "<option selected>classic</option>
                              <option>web</option>";
              }
            else
              {
                 $o_cont .=  "<option>classic</option>
                              <option selected>web</option>";
              }
            $o_cont .=      "</select>
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;RMA-S/N verwalten:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">";
            if($ini_editsn==1)
              {
                 $o_cont .=  "<input type=\"checkbox\" name=\"editsn\" value=\"1\" checked=\"checked\">";
              }
            else
              {
                 $o_cont .=  "<input type=\"checkbox\" name=\"editsn\" value=\"1\">";
              }
            $o_cont .=      "</select>
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             &nbsp;
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             <b>Online-Versionscheck</b>
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;Version abgleichen:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">";
            if($xt_online==1)
              {
                 $o_cont .=  "<input type=\"checkbox\" name=\"online\" value=\"1\" checked=\"checked\">";
              }
            else
              {
                 $o_cont .=  "<input type=\"checkbox\" name=\"online\" value=\"1\">";
              }
            $o_cont .=      "</select>
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             &nbsp;
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             <b>Passwort &auml;ndern</b>
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;Neues ini-Passwort:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"password\" name=\"n_pass_1\" size=\"20\">
                            </td>
                           </tr>
                           <tr>
                            <td align=\"left\" bgcolor=\"#808080\" valign=\"middle\">
                             &nbsp;Wdh. ini-Passwort:
                            </td>
                            <td align=\"right\" bgcolor=\"#808080\" valign=\"middle\">
                             <input type=\"password\" name=\"n_pass_2\" size=\"20\">
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\">
                             &nbsp;
                            </td>
                           </tr>
                           <tr>
                            <td colspan=\"2\" align=\"center\" valign=\"middle\">
                             <input type=\"submit\" name=\"save\" value=\"Speichern\">
                            </td>
                           </tr>
                          </form>
                         </table><br><br><br><br>";
          }
        else
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         Zugang verweigert, falsches Kennwort.
                        <br><br><br>
                         <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
          }
      }
    elseif($_GET['action']=="submit")
      {
        // Header: main.php?section=".$_GET['section']."&module=konfig&action=submit
        if(md5($_POST['ini_pass'])==$ini_pass)
          {
            if(($_POST['n_pass_1']=="")||($_POST['n_pass_2']==""))  // Kein neues ini-Passwort festgelegt.
              {
                if($ini_file = fopen("caoxt.ini", "w"))
                  {
                    fwrite($ini_file, "[Datenbank]\n");
                    fwrite($ini_file, "db_loc=".$_POST['loc']."\n");
                    fwrite($ini_file, "db_port=".$_POST['port']."\n");
                    fwrite($ini_file, "db_name=".$_POST['name']."\n");
                    fwrite($ini_file, "db_user=".$_POST['user']."\n");
                    fwrite($ini_file, "db_pass=".$_POST['pass']."\n");
                    fwrite($ini_file, "db_pref=".strtoupper($_POST['pref'])."\n");
                    fwrite($ini_file, "[Module]\n");
                    fwrite($ini_file, "ini_navstyle=".$_POST['navstyle']."\n");
                    fwrite($ini_file, "ini_editsn=".$_POST['editsn']."\n");
                    fwrite($ini_file, "[Passwort]\n");
                    fwrite($ini_file, "ini_pass=".$ini_pass."\n");
                    fwrite($ini_file, "[Version]\n");
                    fwrite($ini_file, "xt_version=".$xt_version."\n");
                    fwrite($ini_file, "xt_name=".$xt_name."\n");
                    fwrite($ini_file, "xt_online=".$_POST['online']."\n");
                    fclose($ini_file);

                    unset($_SESSION['error']);

                    $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                                <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                                <br><br><br><br>
                                 Die &Auml;nderungen an der Konfigurationsdatei wurden gespeichert.<br>
                                 Weiter zum Datenbank-Setup?
                                 <br><br>
                                 <button name=\"back\" type=\"button\" value=\"Abbrechen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Abbrechen</button>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<button name=\"forwd\" type=\"button\" value=\"Weiter\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=konfig&action=dbsetup'\">Weiter</button>
                                <br><br><br><br>
                                </td></tr>
                                </table>";
                  }
                else
                  {
                    $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                                <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                                <br><br><br><br>
                                 <b>Fehler:</b> Die &Auml;nderungen an der Konfigurationsdatei konnten nicht gespeichert werden.<br><br>
                                <br>
                                 <button name=\"back\" type=\"button\" value=\"Fertigstellen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Fertigstellen</button>
                                <br><br><br><br>
                                </td></tr>
                                </table>";
                  }
              }
            else
              {
                if($_POST['n_pass_1']==$_POST['n_pass_2'])  // Eingegebene ini-Passwörter stimmen überein.
                  {
                    if($ini_file = fopen("caoxt.ini", "w"))
                      {
                        fwrite($ini_file, "[Datenbank]\n");
                        fwrite($ini_file, "db_loc=".$_POST['loc']."\n");
                        fwrite($ini_file, "db_port=".$_POST['port']."\n");
                        fwrite($ini_file, "db_name=".$_POST['name']."\n");
                        fwrite($ini_file, "db_user=".$_POST['user']."\n");
                        fwrite($ini_file, "db_pass=".$_POST['pass']."\n");
                        fwrite($ini_file, "db_pref=".strtoupper($_POST['pref'])."\n");
                        fwrite($ini_file, "[Module]\n");
                        fwrite($ini_file, "ini_navstyle=".$_POST['navstyle']."\n");
                        fwrite($ini_file, "ini_editsn=".$_POST['editsn']."\n");
                        fwrite($ini_file, "[Passwort]\n");
                        fwrite($ini_file, "ini_pass=".md5($_POST['n_pass_1'])."\n");
                        fwrite($ini_file, "[Version]\n");
                        fwrite($ini_file, "xt_version=".$xt_version."\n");
                        fwrite($ini_file, "xt_name=".$xt_name."\n");
                        fwrite($ini_file, "xt_online=".$_POST['online']."\n");
                        fclose($ini_file);

                        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                                    <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                                    <br><br><br><br>
                                     Die &Auml;nderungen an der Konfigurationsdatei wurden gespeichert.<br><br>
                                    <br>
                                     <button name=\"back\" type=\"button\" value=\"Fertigstellen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Fertigstellen</button>
                                    <br><br><br><br>
                                    </td></tr>
                                    </table>";

                        unset($_SESSION['error']);
                      }
                    else
                      {
                        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                                    <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                                    <br><br><br><br>
                                     <b>Fehler:</b> Die &Auml;nderungen an der Konfigurationsdatei konnten nicht gespeichert werden.<br><br>
                                    <br>
                                     <button name=\"back\" type=\"button\" value=\"Fertigstellen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Fertigstellen</button>
                                    <br><br><br><br>
                                    </td></tr>
                                    </table>";
                      }
                  }
                else
                  {
                    $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                                <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                                <br><br><br><br>
                                 Die eingegebenen Passw&ouml;rter stimmen nicht &uuml;berein.
                                <br><br><br>
                                 <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                                <br><br><br><br>
                                </td></tr>
                                </table>";
                  }
              }
          }
        else
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         Zugang verweigert, falsches Kennwort.
                        <br><br><br>
                         <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
          }
      }
    elseif($_GET['action']=="dbsetup")
      {
        $xt_best = 0;
	$xt_best_aend = 0;
	$xt_rma = 0;
        $xt_rma_status = 0;
        $count = 0;
        $report = "";

        // Herausfinden, welche Tabellen bereits angelegt sind

        if($_SESSION['error'])
          {
            switch($_SESSION['error'])
              {
                case 1000: $e_msg = "Keine Zugangsdaten für die Datenbank!"; break;
                case 1001: $e_msg = "Datenbank konnte nicht ge&ouml;ffnet werden!"; break;
                case 1002: $e_msg = "Datenbankserver nicht erreichbar!"; break;
                case 1003: $e_msg = "Keine Konfigurationsdatei vorhanden!"; break;
              }

            unset($_SESSION['error']);

            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">
                       <br><br><br><br>
                       Es konnte keine Verbindung zur CAO-Datenbank hergestellt werden! Folgender Fehler ist aufgetreten:<br><b>".$e_msg."</b><br><br>Bitte &uuml;berpr&uuml;fen Sie Ihre Eingaben.
                       <br><br><br><br>
                       <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                       <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                       <tr><td bgcolor=\"#808080\" align=\"left\">
                        <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Korrektur\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=konfig'\">Korrektur</button>
                       </td></tr></table>
                       <br><br><br><br><br><br><br><br>
                       </td></tr></table>";
          }
        else
          {
            $res_id = mysql_query("SHOW TABLES FROM ".$db_name." LIKE '".$db_pref."%'", $db_id);
            $table = array();
            $t_num = mysql_num_rows($res_id);
            for($i=0; $i<$t_num; $i++)
              {
                array_push($table, mysql_fetch_row($res_id));
              }
            foreach($table as $tmp)
              {
                $local = strtoupper($tmp[0]);

                if($local == $db_pref."BEST")
                  {
                    $xt_best = 1;
                  }
                elseif($local == $db_pref."BEST_AEND")
                  {
                    $xt_best_aend = 1;
                  }
                elseif($local == $db_pref."SN_AEND")
                  {
                    $xt_sn_aend = 1;
                  }
                elseif($local == $db_pref."RMA")
                  {
                    $xt_rma = 1;
                  }
                elseif($local == $db_pref."RMA_STATUS")
                  {
                    $xt_rma_status = 1;
                  }
                elseif($local == $db_pref."RMA_TEILE")
                  {
                    $xt_rma_teile = 1;
                  }
                elseif($local == $db_pref."DATEV")
                  {
                    $xt_datev = 1;
                  }
                elseif($local == $db_pref."DATEV_SETS")
                  {
                    $xt_datev_sets = 1;
                  }
                elseif($local == $db_pref."DATEV_FILTER")
                  {
                    $xt_datev_filter = 1;
                  }
                elseif($local == $db_pref."LASTSCHRIFTEN")
                  {
                    $xt_lastschriften = 1;
                  }
                elseif($local == $db_pref."KTOAUS")
                  {
                    $xt_ktoaus = 1;
                  }
              }

            // Tabellen erstellen, die noch nicht existieren

            if(!$xt_best)
              {
                mysql_query('CREATE TABLE '.$db_pref.'BEST (
                        ART_ID int(11) NOT NULL,
                        RMA_BEST int(11),
                        E_BEST int(11),
                        PRIMARY KEY (ART_ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."BEST<br>";
              }
            if(!$xt_best_aend)
              {
                mysql_query('CREATE TABLE '.$db_pref.'BEST_AEND (
                        ID int(11) NOT NULL auto_increment,
                        ART_ID int(11),
                        ANZAHL int(11),
                        KONTO varchar(8),
                        GKONTO varchar(8),
                        LAGER_QUELLE varchar(8),
                        LAGER_ZIEL varchar(8),
                        KOMMENTAR varchar(255),
                        ERSTELLT varchar(64),
                        DATUM date,
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."BEST_AEND<br>";
              }
            if(!$xt_sn_aend)
              {
                mysql_query('CREATE TABLE '.$db_pref.'SN_AEND (
                        ID int(11) NOT NULL auto_increment,
                        ART_ID int(11),
                        SNR_ID int(11),
                        O_STATUS varchar(8),
                        N_STATUS varchar(8),
                        ERSTELLT varchar(64),
                        DATUM date,
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."SN_AEND<br>";
              }
            if(!$xt_rma)
              {
                mysql_query('CREATE TABLE '.$db_pref.'RMA (
                        ID int(11) NOT NULL auto_increment,
                        RMANUM int(11),
                        ART_ID int(11),
                        ART_SNR varchar(64),
                        KUN_ID int(11),
                        KUN_RID int(11),
                        LIEF_ID int(11),
                        LIEF_RID int(11),
                        LIEF_RMA varchar(64),
                        FINAL smallint,
                        EIGEN_RMA smallint,
                        ANZAHL smallint,
                        ERSTELLT varchar(64),
                        ERSTDAT date,
                        FEHLER varchar(255),
                        KOMMENTAR varchar(255),
                        RS_EMAIL varchar(128),
                        RS_NAME1 varchar(32),
                        RS_NAME2 varchar(32),
                        RS_STRASSE varchar(64),
                        RS_PLZ varchar(32),
                        RS_ORT varchar(64),
                        RS_TELEFON varchar(32),
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."RMA<br>";
              }
            if(!$xt_rma_teile)
              {
                mysql_query('CREATE TABLE '.$db_pref.'RMA_TEILE (
                        ID int(11) NOT NULL auto_increment,
                        RMA_ID int(11),
                        ANZAHL smallint(6),
                        ARTIKEL_ID int(11),
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."RMA_TEILE<br>";
              }
            if(!$xt_rma_status)
              {
                mysql_query('CREATE TABLE '.$db_pref.'RMA_STATUS (
                        ID int(11) NOT NULL auto_increment,
                        RMA_ID int(11),
                        STATUS smallint,
                        KOMMENTAR text,
                        ERSATZ_ANZAHL smallint(6),
                        ERSATZ_ARTIKEL_ID int(11),
                        ERSTELLT varchar(64),
                        DATUM date,
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."RMA_STATUS<br>";
              }
            if(!$xt_datev)
              {
                mysql_query('CREATE TABLE '.$db_pref.'DATEV (
                        ID int(11) NOT NULL auto_increment,
                        GEAENDERT date,
                        JAHR varchar(4),
                        MONAT varchar(2),
                        EK varchar(1),
                        VK varchar(1),
                        KASSE varchar(1),
                        BANK varchar(1),
                        EXPORT varchar(1),
                        KOMMENTAR varchar(255),
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."DATEV<br>";
              }
            if(!$xt_datev_sets)
              {
                mysql_query('CREATE TABLE '.$db_pref.'DATEV_SETS (
                        ID int(11) NOT NULL auto_increment,
                        MONAT_ID int(11),
                        DATUM date,
                        KONTO varchar(8),
                        GKONTO varchar(8),
                        BUCHTEXT varchar(255),
                        BELEGNR varchar(64),
                        QUELLE varchar(8),
                        BANK_TYP varchar(32),
                        BANK_INFO varchar(128),
                        UMSATZ float,
                        SKONTO float,
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."DATEV_SETS<br>";
              }
            if(!$xt_datev_filter)
              {
                mysql_query('CREATE TABLE '.$db_pref.'DATEV_FILTER (
                        ID int(11) NOT NULL auto_increment,
                        GKONTO varchar(8),
                        BUCHTEXT varchar(255),
                        BANK_TYP varchar(32),
                        BANK_INFO varchar(128),
                        PRIMARY KEY (ID)
                        )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."DATEV_FILTER<br>";
              }
            if(!$xt_lastschriften)
              {
                mysql_query('CREATE TABLE '.$db_pref.'LIEFERSCHEINE (
						`ID` INT(11) NOT NULL AUTO_INCREMENT,
						`BERECHNET` CHAR(50) NULL DEFAULT NULL,
						`KUN_ID` VARCHAR(255) NULL DEFAULT NULL,
						`KUN_NAME` VARCHAR(32) NULL DEFAULT NULL,
						`BELEG_NR` VARCHAR(128) NULL DEFAULT NULL,
						`BELEG_DATUM` DATE NULL DEFAULT NULL,
						`LIEFERSCHEIN_ID` VARCHAR(128) NULL DEFAULT NULL,
						`LIEFERSCHEIN_DATUM` DATE NULL DEFAULT NULL,
						`ANZAHL_POSITIONEN` INT(11) NULL DEFAULT NULL,
						`NSUMME` DECIMAL(10,2) NULL DEFAULT NULL,
						`MSUMME` DECIMAL(10,2) NULL DEFAULT NULL,
						`BSUMME` DECIMAL(10,2) NULL DEFAULT NULL,
						PRIMARY KEY (`ID`)
                       )', $db_id);
                $count++;
                $report .= "<li>".$db_pref."LIEFERSCHEINE<br>";
              }
			  
            if(!$xt_ktoaus)
              {
                mysql_query("CREATE TABLE ".$db_pref."KTOAUS (
	`EIGENKONTO` VARCHAR(50) NOT NULL DEFAULT '1200',
	`BELEG` INT(11) NOT NULL AUTO_INCREMENT,
	`DATUM` DATE NOT NULL DEFAULT '0000-00-00',
	`VALUTA` DATE NOT NULL DEFAULT '0000-00-00',
	`ZP_ZE` VARCHAR(100) NOT NULL DEFAULT '',
	`KTO` VARCHAR(10) NOT NULL DEFAULT '',
	`IBAN` VARCHAR(34) NOT NULL DEFAULT '',
	`BLZ` VARCHAR(8) NOT NULL DEFAULT '',
	`BIC` VARCHAR(11) NOT NULL DEFAULT '',
	`VERWENDUNGSZWECK` TEXT NOT NULL,
	`AUFTRAGSART` TEXT NOT NULL,
	`BUCHUNGSTEXT` TEXT NOT NULL,
	`KATEGORIE` VARCHAR(100) NOT NULL DEFAULT '',
	`BETRAG` DECIMAL(10,0) NOT NULL DEFAULT '0',
	`WAEHRUNG` CHAR(3) NOT NULL DEFAULT 'EUR',
	`SVWZ` TEXT NOT NULL,
	`EREF` VARCHAR(100) NOT NULL DEFAULT '',
	`MREF` VARCHAR(100) NOT NULL DEFAULT '',
	`CRED` VARCHAR(100) NOT NULL DEFAULT '',
	`ENTG` VARCHAR(100) NOT NULL DEFAULT '',
	`IBAN` VARCHAR(100) NOT NULL DEFAULT '',
	`BIC` VARCHAR(100) NOT NULL DEFAULT '',
	`ANAM` VARCHAR(100) NOT NULL DEFAULT '',
	`ABWA` VARCHAR(100) NOT NULL DEFAULT '',
	`ABWE` VARCHAR(100) NOT NULL DEFAULT '',
	PRIMARY KEY (`BELEG`)
)
)", $db_id);
                $count++;
                $report .= "<li>".$db_pref."KTOAUS<br>";
              }

            // Patch für vorhandene Datenbank

            $res_id = mysql_query("SHOW COLUMNS FROM ".$db_pref."RMA_STATUS", $db_id);
            $columns = array();
            $c_num = mysql_num_rows($res_id);
            for($i=0; $i<$c_num; $i++)
              {
                array_push($columns, mysql_fetch_row($res_id));
              }
            foreach($columns as $row)
              {
                if($row[Field]=="KOMMENTAR")
                  {
                    if(!$row[Type]=="text")
                      {
                        mysql_query("ALTER TABLE ".$db_pref."RMA_STATUS CHANGE KOMMENTAR KOMMENTAR text NULL DEFAULT NULL", $db_id);
                      }
                  }
              }


            // Bericht ausgeben

            if($count)
              {
                $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">
                           <br><br><br><br>
                           Es wurde ".$count." Tabellen neu in der Datenbank angelegt:<br>
                           ".$report."
                           <br><br><br><br>
                           <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                           <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                           <tr><td bgcolor=\"#808080\" align=\"left\">
                            <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Fertigstellen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Fertigstellen</button>
                           </td></tr></table>
                           <br><br><br><br><br><br><br><br>
                           </td></tr></table>";
              }
            else
              {
                $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">
                           <br><br><br><br>
                           Alle Datenbanktabellen für CAO-XT ".$xt_version." sind bereits angelegt!
                           <br><br><br><br>
                           <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                           <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                           <tr><td bgcolor=\"#808080\" align=\"left\">
                            <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Fertigstellen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Fertigstellen</button>
                           </td></tr></table>
                           <br><br><br><br><br><br><br><br>
                           </td></tr></table>";
              }
          }
      }
    else
      {
        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                    <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                    <br><br><br><br>
                     <h3>Fehler: Aktion unbekannt!</h3>
                    <br>
                     <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=home'\">Zur&uuml;ck</button>
                    <br><br><br><br>
                    </td></tr>
                    </table>";
      }

?>