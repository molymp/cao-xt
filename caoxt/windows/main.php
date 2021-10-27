<?php

// ------------------------------------------------------------------------------------------------
//      Session:

session_start();
set_time_limit(6000);
error_reporting(E_ALL & ~E_NOTICE);

// ------------------------------------------------------------------------------------------------
//	Datenkompression bei der Übertragung:

if(substr_count($_SERVER['HTTP_ACCEPT_ENCODING'], 'gzip'))
  {
    ob_start("ob_gzhandler");
  }
else
  {
    ob_start();
  }

// ------------------------------------------------------------------------------------------------
//      Initialisierungsvariablen:

$db_loc  = "";								// Adresse des Datenbankservers
$db_port = "";								// Port des Datenbankservers
$db_name = "";								// Name der Datenbank
$db_user = "";								// Datenbank-Login
$db_pass = "";								// Datenbank-Passwort
$db_pref = "";								// Tabellennamen Präfix

if($xt_config = file("../caoxt.ini")) 					// Konfiguration in Array (zeilenweise)
  {
    foreach($xt_config as $row)
      {
        $temp = explode(" ", $row);					// Überflüssiges abschneiden
        $row_data = explode("=", $temp[0]);                             // Zeilendaten einlesen

        if($row_data[0]=="db_loc")
          {
            $db_loc = chop($row_data[1]);
          }
        elseif($row_data[0]=="db_port")
          {
            $db_port = chop($row_data[1]);
          }
        elseif($row_data[0]=="db_name")
          {
            $db_name = chop($row_data[1]);
          }
        elseif($row_data[0]=="db_user")
          {
            $db_user = chop($row_data[1]);
          }
        elseif($row_data[0]=="db_pass")
          {
            $db_pass = chop($row_data[1]);
          }
        elseif($row_data[0]=="db_pref")
          {
            $db_pref = chop($row_data[1]);
          }
      }
  }

$usr_rights = "";								// Sicherheitsinitialisierung

if($_SESSION['user'])
  {
    $tmp_address = $db_loc.":".$db_port;					// Login im Schnelldurchlauf
    $db_id = mysql_connect($tmp_address, $db_user, $db_pass);
    mysql_select_db($db_name, $db_id);

    $db_res = mysql_query("SELECT LOGIN_NAME, VNAME, NAME FROM MITARBEITER WHERE LOGIN_NAME=\"".$_SESSION['user']."\" AND USER_PASSWORD=\"".$_SESSION['pmd5']."\"", $db_id);
    $usr_data = mysql_fetch_array($db_res, MYSQL_ASSOC);
    mysql_free_result($db_res);

    if($usr_data['LOGIN_NAME'])
      {
        $usr_rights = 1;
        $usr_name = $usr_data['VNAME']." ".$usr_data['NAME'];
      }
    else
      {
        $usr_rights = 0;
        unset($_SESSION['user']);
        unset($_SESSION['pmd5']);
      }

    if($_GET['module']=="address")
      {
        include("modules/address.php");
      }
    elseif($_GET['module']=="article")
      {
        include("modules/article.php");
      }
    elseif($_GET['module']=="liefaddr")
      {
        include("modules/liefaddr.php");
      }
    elseif($_GET['module']=="snum")
      {
        include("modules/snum.php");
      }
    else
      {
        $o_head = "Fehler";
        $o_cont = "<div align=\"center\"><br><br><br><h1>Modul nicht gefunden!</h1><br><br><br></div>";
        $o_navi = "";
      }
  }
else
  {
    $o_head = "Fehler";
    $o_cont = "<div align=\"center\"><br><br><br><h1>Zugriff verweigert!</h1><br><br><br></div>";
    $o_navi = "";
  }

$output = file_get_contents("includes/mtemplate.html");
$output = str_replace("@@head@@", $o_head, $output);				// Seitenkopf / -name
$output = str_replace("@@java@@", $o_java, $output);				// Javascripte
$output = str_replace("@@cont@@", $o_cont, $output);				// Inhalt der Seite
$output = str_replace("@@navi@@", $o_navi, $output);				// Zusatznavigation
$output = str_replace("@@body@@", $o_body, $output);				// Zusatznavigation

print $output;

ob_end_flush();									// Ausgabepuffer leeren

?>