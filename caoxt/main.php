<?php
// error_reporting(E_ALL); 
// ini_set("display_errors", true);
//	-------------------------------------------
//	Habacher Dorfladen CAO-XTensions
//	http://habacher-dorfladen.de
//	-------------------------------------------
//	Last Edit by Marc Ledermann
//	-------------------------------------------
//	based on CAO-XTensions by
//	Daniel Marcus (http://blackheartware.com)
//	-------------------------------------------
//	published under GPL -
//      GNU GENERAL PUBLIC LICENSE
//	-------------------------------------------

//	Datenkompression bei der Übertragung durch Ausgabepuffer:
if (substr_count($_SERVER['HTTP_ACCEPT_ENCODING'], 'gzip')) { ob_start("ob_gzhandler"); }
else { ob_start(); }

date_default_timezone_set('CET');
session_start();
set_time_limit(6000);
error_reporting(E_ALL & ~E_NOTICE);

// ------------------------------------------------------------------------------------------------
//	MySQL-Erweiterung:
if(!extension_loaded('mysql')) {
    if(strstr(getenv('SERVER_SOFTWARE'), "Win")) {
        if(!dl('php_mysql.dll')) {
            $_SESSION['error'] = 1004;
            $module = "konfig";
        }
    } else {
        if(!dl('mysql.so')) {
            $_SESSION['error'] = 1004;
            $module = "konfig";
        }
    }
}

//	Globale Einstellungen / Variablenresets:
include("includes/ini.php");						// Initialisierungsvariablen
$xt_version = "0.7.1b";						// Versionsinformationen
$xt_name = "Lastschrift";							// Versionsname

$module = $_GET['module'];						// Variablen holen
$usr_rights = "";							// Sicherheitsinitialisierung
if(!$_SESSION['user']) {							// Sessiondaten Login
  if($_POST['user']) {
    $_SESSION['user'] = $_POST['user'];
    $_SESSION['pmd5'] = md5($_POST['pass']);
  }
}
if($_POST['login']=="Abmelden") {				// Logout
    unset($_SESSION['user']);
    unset($_SESSION['pmd5']);
}

if($db_user && $db_loc) { 									//	Datenbank-Login Check
	$tmp_address = $db_loc.":".$db_port;
	if($db_id = mysql_connect($tmp_address, $db_user, $db_pass)) {
		if(mysql_select_db($db_name, $db_id)) { 			//	Userdaten aus Datenbank holen oder User ausloggen:
			if($_SESSION['user']) {
				$db_res = mysql_query("SELECT LOGIN_NAME, VNAME, NAME FROM MITARBEITER WHERE LOGIN_NAME=\"".$_SESSION['user']."\" AND USER_PASSWORD=\"".$_SESSION['pmd5']."\"", $db_id);
				$usr_data = mysql_fetch_array($db_res, MYSQL_ASSOC);
				mysql_free_result($db_res);
				if($usr_data['LOGIN_NAME']) {
					$usr_rights = 1;
					$usr_name = $usr_data['VNAME']." ".$usr_data['NAME'];
				} else {
					$usr_rights = 0;
					unset($_SESSION['user']);
					unset($_SESSION['pmd5']);
				}
			}
		} else { // Datenbank / Errorhandling:
			if(!$_SESSION['error']) {
				$_SESSION['error'] = 1001;
			}
			$module = "konfig";
		}
	} else {
		if(!$_SESSION['error']) {
			$_SESSION['error'] = 1002;
		}
		$module = "konfig";
	}
} else { // Datenbank / Keine Zugangsdaten:
	$_SESSION['error'] = 1000;
	$module = "konfig";
}
include(realpath("modules/".$module.'.php'));			//	Modul einbinden
include("includes/login.php");							//	Login verwalten
include("includes/navi.php");							//	Javascript / Navigation:

//	Template einlesen, Spacer ersetzen und Ausgabe:
$output = file_get_contents("includes/template.html");
$output = str_replace("@@title@@", $xt_version." - ".$xt_name, $output);	// Seitentitel
$output = str_replace("@@head@@", $o_head, $output);				// Seitenkopf / -name
$output = str_replace("@@cont@@", $o_cont, $output);				// Inhalt der Seite
$output = str_replace("@@login@@", $o_login, $output);				// Login
$output = str_replace("@@navi@@", $o_navi, $output);				// Zusatznavigation
$output = str_replace("@@java@@", $o_java, $output);				// Javascript generieren
$output = str_replace("@@jnv1@@", $o_jnv1, $output);				// Menü
$output = str_replace("@@jnv2@@", $o_jnv2, $output);				// Menü
$output = str_replace("@@jnv3@@", $o_jnv3, $output);				// Menü
$output = str_replace("@@jnv4@@", $o_jnv4, $output);				// Menü
$output = str_replace("@@jnv5@@", $o_jnv5, $output);				// Menü
$output = str_replace("@@jnv6@@", $o_jnv6, $output);				// Menü
print $output;
ob_end_flush();									// Ausgabepuffer leeren
?>