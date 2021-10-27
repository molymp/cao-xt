<?php
$db_loc  = "";									// Adresse des Datenbankservers
$db_port = "";									// Port des Datenbankservers
$db_name = "";									// Name der Datenbank
$db_user = "";									// Datenbank-Login
$db_pass = "";									// Datenbank-Passwort
$db_pref = "";									// Tabellennamen Präfix
$ini_navstyle = "";								// Klassische CAO-Journalnavigation?
$ini_editsn = "";								// Seriennummern in RMA-Modul ausbuchen?
$ini_pass = "";									// Passwort für ini-Bearbeitung (md5)
$xt_online = "";								// Online Versionscheck

if($xt_config = file("caoxt.ini")) { 			// Konfiguration in Array (zeilenweise)
	foreach($xt_config as $row) {
		$temp = explode(" ", $row);				// Überflüssiges abschneiden
		$row_data = explode("=", $temp[0]);		// Zeilendaten einlesen
		if		($row_data[0]=="db_loc")		$db_loc = chop($row_data[1]); 
		elseif	($row_data[0]=="db_port")		$db_port = chop($row_data[1]);
		elseif	($row_data[0]=="db_name")		$db_name = chop($row_data[1]);
		elseif	($row_data[0]=="db_user")		$db_user = chop($row_data[1]);
		elseif	($row_data[0]=="db_pass")		$db_pass = chop($row_data[1]);
		elseif($row_data[0]=="db_pref")			$db_pref = chop($row_data[1]);
		elseif($row_data[0]=="ini_navstyle")	$ini_navstyle = chop($row_data[1]);
		elseif($row_data[0]=="ini_editsn")		$ini_editsn = chop($row_data[1]);
		elseif($row_data[0]=="ini_pass")		$ini_pass = chop($row_data[1]);
		elseif($row_data[0]=="xt_online")		$xt_online = chop($row_data[1]);
	}
} else {
	$_SESSION['error'] = 1003;
	$module = "konfig";
}
?>