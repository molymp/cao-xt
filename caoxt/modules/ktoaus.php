<?php
// error_reporting(E_ALL); 
// ini_set("display_errors", true);

$o_head = "Kontoauszüge";
$o_navi = "";

// Wenn das Modul ohne vorherige Anmeldung aufgerufen wird, kommt man nicht weiter:
if (!$usr_rights) { 
	$o_cont = "<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
}
ELSEIF ($_GET['action']=="save") // Wenn im Modul auf 'Kontoauszug importieren' geklickt wird:
{
	$o_head = "Kontoauszüge gespeichert";
	include_once("includes/parsecsv.lib.php");
	$csv = new parseCSV();
	$csv->input_encoding = "Windows-1252";
	$csv->output_encoding = "Windows-1252";
	$csv->sort_by = 'VALUTA';
	$csv->auto($_GET['filename']);
	
	$o_cont = "
	<table width=\"100%\"><tr bgcolor=\"#f4f0e8\"><td align=\"right\">
	<form action=\"main.php?section=".$_GET['section']."&module=ktoaus\" method='post' enctype='multipart/form-data' style='height:9px;'>
    <input type='submit' name='btn[return]' value='...zur&uuml;ck'></form>
	</td></tr></table>";

	$a = 0;
	foreach($csv->data as $row) {

	$string = preg_replace('/\s+/', '', $row['Verwendungszweck']);
		$pos_ABWE = strpos($string, 'ABWE:');
		$pos_ABWA = strpos($string, 'ABWA:');
		$pos_ANAM = strpos($string, 'ANAM:');
		$pos_BIC = strpos($string, 'BIC:');
		$pos_IBAN = strpos($string, 'IBAN:');
		$pos_ENTG = strpos($string, 'ENTG:');
		$pos_CRED = strpos($string, 'CRED:');
		$pos_MREF = strpos($string, 'MREF:');
		$pos_EREF = strpos($string, 'EREF:');
		$pos_SVWZ = strpos($string, 'SVWZ:');

		if ($pos_ABWE) { $csv->data[$a][ABWE] = substr($string, $pos_ABWE+5); }
		if ($pos_ABWA) {
			if     ($pos_ABWE) { $csv->data[$a][ABWA] = substr($string, $pos_ABWA+5, $pos_ABWE-$pos_ABWA-5); }
			else { $csv->data[$a][ABWA] = substr($string, $pos_ABWA+5); }
		}
		if ($pos_ANAM) {
			if     ($pos_ABWA) { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5, $pos_ABWA-$pos_ANAM-5); }
			elseif ($pos_ABWE) { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5, $pos_ABWE-$pos_ANAM-5); }
			else { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5); }
		}
		if ($pos_BIC) {
			if     ($pos_ANAM) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ANAM-$pos_BIC-4); } 
			elseif ($pos_ABWA) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ABWA-$pos_BIC-4); }
			elseif ($pos_ABWE) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ABWE-$pos_BIC-4); }
			else { $csv->data[$a][BIC] = substr($string, $pos_BIC+4); }
		}
		if ($pos_IBAN) {
			$row['land'][$a] = substr($string, $pos_IBAN+5, 2);
			if ($row['land'][$a] == 'DE') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 22);
			if ($row['land'][$a] == 'AT') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 20);
			if ($row['land'][$a] == 'CH') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 21);
			if ($row['land'][$a] == 'FR') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 27);
		}
		if ($pos_ENTG) {
			if     ($pos_IBAN) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_IBAN-$pos_ENTG-5); }
			elseif ($pos_BIC)  { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_BIC-$pos_ENTG-5); }
			elseif ($pos_ANAM) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ANAM-$pos_ENTG-5); }
			elseif ($pos_ABWA) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ABWA-$pos_ENTG-5); }
			elseif ($pos_ABWE) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ABWE-$pos_ENTG-5); }
			else { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5); }
		}
		if ($pos_CRED) {
			if     ($pos_ENTG) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ENTG-$pos_CRED-5); }
			elseif ($pos_IBAN) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_IBAN-$pos_CRED-5); }
			elseif ($pos_BIC)  { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_BIC-$pos_CRED-5); }
			elseif ($pos_ANAM) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ANAM-$pos_CRED-5); }
			elseif ($pos_ABWA) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ABWA-$pos_CRED-5); }
			elseif ($pos_ABWE) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ABWE-$pos_CRED-5); }
			else { $csv->data[$a][CRED] = substr($string, $pos_CRED+5); }
		}
		if ($pos_MREF) {
			if     ($pos_CRED) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_CRED-$pos_MREF-5); }
			elseif ($pos_ENTG) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ENTG-$pos_MREF-5); }
			elseif ($pos_IBAN) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_IBAN-$pos_MREF-5); }
			elseif ($pos_BIC)  { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_BIC-$pos_MREF-5); }
			elseif ($pos_ANAM) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ANAM-$pos_MREF-5); }
			elseif ($pos_ABWA) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ABWA-$pos_MREF-5); }
			elseif ($pos_ABWE) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ABWE-$pos_MREF-5); }
			else { $csv->data[$a][MREF] = substr($string, $pos_MREF+5); }
		}
		if ($pos_EREF) {
			if     ($pos_MREF) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_MREF-$pos_EREF-5); }
			elseif ($pos_CRED) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_CRED-$pos_EREF-5); }
			elseif ($pos_ENTG) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ENTG-$pos_EREF-5); }
			elseif ($pos_IBAN) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_IBAN-$pos_EREF-5); }
			elseif ($pos_BIC)  { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_BIC-$pos_EREF-5); }
			elseif ($pos_ANAM) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ANAM-$pos_EREF-5); }
			elseif ($pos_ABWA) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ABWA-$pos_EREF-5); }
			elseif ($pos_ABWE) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ABWE-$pos_EREF-5); }
			else { $csv->data[$a][EREF] = substr($string, $pos_EREF+5); }
		}
		if ($pos_SVWZ) {
			if     ($pos_EREF) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_EREF-$pos_SVWZ-5); }
			elseif ($pos_MREF) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_MREF-$pos_SVWZ-5); }
			elseif ($pos_CRED) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_CRED-$pos_SVWZ-5); }
			elseif ($pos_ENTG) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ENTG-$pos_SVWZ-5); }
			elseif ($pos_IBAN) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_IBAN-$pos_SVWZ-5); }
			elseif ($pos_BIC)  { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_BIC-$pos_SVWZ-5); }
			elseif ($pos_ANAM) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ANAM-$pos_SVWZ-5); }
			elseif ($pos_ABWA) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ABWA-$pos_SVWZ-5); }
			elseif ($pos_ABWE) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ABWE-$pos_SVWZ-5); }
			else { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5); }
		}
		$parts = explode('.', $csv->data[$a]['Datum']);
		$date  = "$parts[2]-$parts[1]-$parts[0]";
		$parts = explode('.', $csv->data[$a]['Valuta']);
		$valuta  = "$parts[2]-$parts[1]-$parts[0]";
		
		$poop = mysql_query("SELECT * from XT_KTOAUS 
						WHERE DATUM=\"".$date."\"
						AND VALUTA=\"".$valuta."\"
						AND ZP_ZE=\"".$csv->data[$a]['Zahlungspflichtiger/-empfänger']."\"
						AND VERWENDUNGSZWECK=\"".$csv->data[$a]['Verwendungszweck']."\" 
						AND BETRAG=\"".str_replace(',','.',$csv->data[$a]['Betrag'])."\"
						", $db_id);
		$pee = array();
		$poop_num = mysql_numrows($poop);
		for($i=0; $i<$poop_num; $i++) { array_push($pee, mysql_fetch_array($poop, MYSQL_ASSOC)); }
		
		IF(!$pee){mysql_query("INSERT INTO XT_KTOAUS (DATUM, VALUTA, ZP_ZE, KTO_IBAN, BLZ_BIC, VERWENDUNGSZWECK, AUFTRAGSART, BUCHUNGSTEXT, KATEGORIE, BETRAG, WAEHRUNG, SVWZ, EREF, MREF, CRED, ENTG, IBAN, BIC, ANAM, ABWA, ABWE) VALUES (\"" . $date . "\", \"" . $valuta . "\", \"" . $csv->data[$a]['Zahlungspflichtiger/-empfänger'] . "\", \"" . $csv->data[$a]['ZP/ZE Konto/IBAN'] . "\", \"" . $csv->data[$a]['ZP/ZE Bankleitzahl/BIC'] . "\", \"" . $csv->data[$a]['Verwendungszweck'] . "\", \"" . $csv->data[$a]['Auftragsart'] . "\", \"" . $csv->data[$a]['Buchungstext'] . "\", \"" . $csv->data[$a]['Kategorie'] . "\", \"" . str_replace(',','.',$csv->data[$a]['Betrag']) . "\", \"" . $csv->data[$a]['Währung'] . "\", \"" . $csv->data[$a][SVWZ] . "\", \"" . $csv->data[$a][EREF] . "\", \"" . $csv->data[$a]['MREF'] . "\", \"" . $csv->data[$a]['CRED'] . "\", \"" . $csv->data[$a]['ENTG'] . "\", \"" . $csv->data[$a]['IBAN'] . "\", \"" . $csv->data[$a]['BIC'] . "\", \"" . $csv->data[$a][ANAM] . "\", \"" . $csv->data[$a][ABWA] . "\", \"" . $csv->data[$a][ABWE] . "\")", $db_id);}
		
		$a++;
	}
//	$o_cont .= "</table>";
}
ELSEIF ($_GET['action']=="import") // Wenn im Modul auf 'Kontoauszug importieren' geklickt wird:
{
	$o_head = "Kontoauszüge importieren";
	include_once("includes/parsecsv.lib.php");

	$uploaddir = dirname(__FILE__) . '/ktoaus';
	$uploadfile = time() . '.csv';
	move_uploaded_file($_FILES['dateiupload']['tmp_name'], "$uploaddir/$uploadfile");

	$csv = new parseCSV();
	$csv->input_encoding = "Windows-1252";
	$csv->output_encoding = "Windows-1252";
	$csv->sort_by = 'VALUTA';
	$csv->auto("$uploaddir/$uploadfile");

	$mysqlquery = "SELECT EIGENKONTO, BELEG, DATUM, VALUTA, ZP_ZE, KTO_IBAN, BLZ_BIC, VERWENDUNGSZWECK, AUFTRAGSART, BUCHUNGSTEXT, KATEGORIE, BETRAG, WAEHRUNG, SVWZ, EREF, MREF, CRED, ENTG, IBAN, BIC, ABWA, ABWE, ANAM FROM XT_KTOAUS ORDER BY BELEG";
	$res_id = mysql_query($mysqlquery, $db_id);
	$result = array();
	$res_num = mysql_numrows($res_id);
	for($i=0; $i<$res_num; $i++) { array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC)); } // Kontoauszugsdatensätze in Array

	$o_cont = "
	<table width=\"100%\"><tr bgcolor=\"#f4f0e8\"><td align=\"right\">
	<form action=\"main.php?section=".$_GET['section']."&module=ktoaus&action=save&filename=".$uploaddir."/".$uploadfile."\" method='post' enctype='multipart/form-data' style='height:9px;'>
    <input type='submit' name='btn[save]' value='...und in Datenbank übernehmen'></form>
	</td></tr></table>";
	$o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>#</td><td><b>VALUTA</b><br/>DATUM</td><td>ZP_ZE</td><td>KTO_IBAN<br/>BLZ_BIC</td><td>VERWENDUNGSZWECK</td><td>AUFTRAGSART<br/>BUCHUNGSTEXT</td><td>SVWZ<br/>EREF<br/>MREF<br/>CRED<br/>ENTG</td><td>IBAN<br/>BIC<br/>ANAM<br/>ABWA<br/>ABWE</td><td>KATEGORIE</td><td align=\"right\">BETRAG<br/>WAEHRUNG</td></tr>";
	$a = 0;
	foreach($csv->data as $row) {

	$string = preg_replace('/\s+/', '', $row['Verwendungszweck']);
		$pos_ABWE = strpos($string, 'ABWE:');
		$pos_ABWA = strpos($string, 'ABWA:');
		$pos_ANAM = strpos($string, 'ANAM:');
		$pos_BIC = strpos($string, 'BIC:');
		$pos_IBAN = strpos($string, 'IBAN:');
		$pos_ENTG = strpos($string, 'ENTG:');
		$pos_CRED = strpos($string, 'CRED:');
		$pos_MREF = strpos($string, 'MREF:');
		$pos_EREF = strpos($string, 'EREF:');
		$pos_SVWZ = strpos($string, 'SVWZ:');

		if ($pos_ABWE) { $csv->data[$a][ABWE] = substr($string, $pos_ABWE+5); }
		if ($pos_ABWA) {
			if     ($pos_ABWE) { $csv->data[$a][ABWA] = substr($string, $pos_ABWA+5, $pos_ABWE-$pos_ABWA-5); }
			else { $csv->data[$a][ABWA] = substr($string, $pos_ABWA+5); }
		}
		if ($pos_ANAM) {
			if     ($pos_ABWA) { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5, $pos_ABWA-$pos_ANAM-5); }
			elseif ($pos_ABWE) { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5, $pos_ABWE-$pos_ANAM-5); }
			else { $csv->data[$a][ANAM] = substr($string, $pos_ANAM+5); }
		}
		if ($pos_BIC) {
			if     ($pos_ANAM) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ANAM-$pos_BIC-4); } 
			elseif ($pos_ABWA) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ABWA-$pos_BIC-4); }
			elseif ($pos_ABWE) { $csv->data[$a][BIC] = substr($string, $pos_BIC+4, $pos_ABWE-$pos_BIC-4); }
			else { $csv->data[$a][BIC] = substr($string, $pos_BIC+4); }
		}
		if ($pos_IBAN) {
			$row['land'][$a] = substr($string, $pos_IBAN+5, 2);
			if ($row['land'][$a] == 'DE') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 22);
			if ($row['land'][$a] == 'AT') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 20);
			if ($row['land'][$a] == 'CH') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 21);
			if ($row['land'][$a] == 'FR') $csv->data[$a]['IBAN'] = substr($string, $pos_IBAN+5, 27);
		}
		if ($pos_ENTG) {
			if     ($pos_IBAN) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_IBAN-$pos_ENTG-5); }
			elseif ($pos_BIC)  { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_BIC-$pos_ENTG-5); }
			elseif ($pos_ANAM) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ANAM-$pos_ENTG-5); }
			elseif ($pos_ABWA) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ABWA-$pos_ENTG-5); }
			elseif ($pos_ABWE) { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5, $pos_ABWE-$pos_ENTG-5); }
			else { $csv->data[$a][ENTG] = substr($string, $pos_ENTG+5); }
		}
		if ($pos_CRED) {
			if     ($pos_ENTG) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ENTG-$pos_CRED-5); }
			elseif ($pos_IBAN) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_IBAN-$pos_CRED-5); }
			elseif ($pos_BIC)  { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_BIC-$pos_CRED-5); }
			elseif ($pos_ANAM) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ANAM-$pos_CRED-5); }
			elseif ($pos_ABWA) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ABWA-$pos_CRED-5); }
			elseif ($pos_ABWE) { $csv->data[$a][CRED] = substr($string, $pos_CRED+5, $pos_ABWE-$pos_CRED-5); }
			else { $csv->data[$a][CRED] = substr($string, $pos_CRED+5); }
		}
		if ($pos_MREF) {
			if     ($pos_CRED) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_CRED-$pos_MREF-5); }
			elseif ($pos_ENTG) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ENTG-$pos_MREF-5); }
			elseif ($pos_IBAN) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_IBAN-$pos_MREF-5); }
			elseif ($pos_BIC)  { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_BIC-$pos_MREF-5); }
			elseif ($pos_ANAM) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ANAM-$pos_MREF-5); }
			elseif ($pos_ABWA) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ABWA-$pos_MREF-5); }
			elseif ($pos_ABWE) { $csv->data[$a][MREF] = substr($string, $pos_MREF+5, $pos_ABWE-$pos_MREF-5); }
			else { $csv->data[$a][MREF] = substr($string, $pos_MREF+5); }
		}
		if ($pos_EREF) {
			if     ($pos_MREF) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_MREF-$pos_EREF-5); }
			elseif ($pos_CRED) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_CRED-$pos_EREF-5); }
			elseif ($pos_ENTG) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ENTG-$pos_EREF-5); }
			elseif ($pos_IBAN) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_IBAN-$pos_EREF-5); }
			elseif ($pos_BIC)  { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_BIC-$pos_EREF-5); }
			elseif ($pos_ANAM) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ANAM-$pos_EREF-5); }
			elseif ($pos_ABWA) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ABWA-$pos_EREF-5); }
			elseif ($pos_ABWE) { $csv->data[$a][EREF] = substr($string, $pos_EREF+5, $pos_ABWE-$pos_EREF-5); }
			else { $csv->data[$a][EREF] = substr($string, $pos_EREF+5); }
		}
		if ($pos_SVWZ) {
			if     ($pos_EREF) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_EREF-$pos_SVWZ-5); }
			elseif ($pos_MREF) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_MREF-$pos_SVWZ-5); }
			elseif ($pos_CRED) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_CRED-$pos_SVWZ-5); }
			elseif ($pos_ENTG) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ENTG-$pos_SVWZ-5); }
			elseif ($pos_IBAN) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_IBAN-$pos_SVWZ-5); }
			elseif ($pos_BIC)  { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_BIC-$pos_SVWZ-5); }
			elseif ($pos_ANAM) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ANAM-$pos_SVWZ-5); }
			elseif ($pos_ABWA) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ABWA-$pos_SVWZ-5); }
			elseif ($pos_ABWE) { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5, $pos_ABWE-$pos_SVWZ-5); }
			else { $csv->data[$a][SVWZ] = substr($string, $pos_SVWZ+5); }
		}
		
		$parts = explode('.', $csv->data[$a]['Datum']);
		$date  = "$parts[2]-$parts[1]-$parts[0]";
		$parts = explode('.', $csv->data[$a]['Valuta']);
		$valuta  = "$parts[2]-$parts[1]-$parts[0]";
		$poop = mysql_query("SELECT * from XT_KTOAUS 
						WHERE DATUM=\"".$date."\"
						AND VALUTA=\"".$valuta."\"
						AND ZP_ZE=\"".$csv->data[$a]['Zahlungspflichtiger/-empfänger']."\"
						AND VERWENDUNGSZWECK=\"".$csv->data[$a]['Verwendungszweck']."\" 
						AND BETRAG=\"".str_replace(',','.',$csv->data[$a]['Betrag'])."\"
						", $db_id);
		$pee = array();
		$poop_num = mysql_numrows($poop);
		for($i=0; $i<$poop_num; $i++) { array_push($pee, mysql_fetch_array($poop, MYSQL_ASSOC)); }
		
		$color++;
		IF ($pee) 
		{
			if($color%2) { $o_cont .= "<tr bgcolor=\"#aaffff\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; } 
			else { $o_cont .= "<tr bgcolor=\"#aaffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; }
		} ELSE 
		{
			if($color%2) { $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; } 
			else { $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; }
		}

		$o_cont .= "<img src=\"images/leer.gif\"></td>
		<td align=\"right\">".$a_anzahl."</td>
		<td align=\"right\"><b>".$csv->data[$a]['Valuta']."</b><br/>
			".$csv->data[$a]['Datum']."</td>
		<td>".$csv->data[$a]['Zahlungspflichtiger/-empfänger']."</td>
		<td>".$csv->data[$a]['ZP/ZE Konto/IBAN']."<br/>
			".$csv->data[$a]['ZP/ZE Bankleitzahl/BIC']."</td>
		<td>".$csv->data[$a]['Verwendungszweck']."</td>
		<td>".$csv->data[$a]['Auftragsart']."<br/>".$csv->data[$a]['Buchungstext']."</td>
		<td>".$csv->data[$a][SVWZ]."<br/>".$csv->data[$a][EREF]."<br/>".$csv->data[$a]['MREF']."<br/>".$csv->data[$a]['CRED']."<br/>".$csv->data[$a]['ENTG']."</td>
		<td>".$csv->data[$a]['IBAN']."<br/>".$csv->data[$a]['BIC']."<br/>".$csv->data[$a][ANAM]."<br/>".$csv->data[$a][ABWA]."<br/>".$csv->data[$a][ABWE]."</td>
		<td>".$csv->data[$a]['Kategorie']."</td>
		<td align=\"right\">".$csv->data[$a]['Betrag']."&nbsp;&euro;<br/>
			".$csv->data[$a]['Währung']."</td>
		</tr>";

		$a++;
	}
	$o_cont .= "</table>";
}
ELSE // Normaler Aufruf des Moduls:
{
	if (!$_GET['month']) {
		// Header: main.php?section=".$_GET['section']."&module=ktoaus
		$month = date("n");
		$year  = date("Y");
	} else {
		// Header: main.php?section=".$_GET['section']."&module=ktoaus&month=xx&year=xxxx
		$month = $_GET['month'];
		$year  = $_GET['year'];
	}
	include("modules/inc/dateselectordatevex.php");
	$o_navi = $dateselector;
	
	$mysqlquery = "SELECT BELEG, EIGENKONTO, DATUM, VALUTA, ZP_ZE, KTO_IBAN, BLZ_BIC, VERWENDUNGSZWECK, AUFTRAGSART, BUCHUNGSTEXT, KATEGORIE, BETRAG, WAEHRUNG, SVWZ, EREF, MREF, CRED, ENTG, IBAN, BIC, ABWA, ABWE, ANAM FROM XT_KTOAUS WHERE YEAR(VALUTA)=".$year;
	if ($month < 20) $mysqlquery .= " AND MONTH(VALUTA)=" . $month;
	$mysqlquery .= " ORDER BY VALUTA";
	$res_id = mysql_query($mysqlquery, $db_id);
	
	$result = array();
	$res_num = mysql_numrows($res_id);
	for($i=0; $i<$res_num; $i++) { array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC)); } // Kontoauszugsdatensätze in Array
	mysql_free_result($res_id);
	
	$o_cont = "
	<table width=\"100%\"><tr bgcolor=\"#f4f0e8\"><td align=\"right\">
	<form action=\"main.php?section=".$_GET['section']."&module=ktoaus&action=import\" method='post' enctype='multipart/form-data' style='height:9px;'>
    <span style='font-size:16px;'>CSV-Datei mit Kontoauszugsdaten auswählen...</span><input type='file' name='dateiupload'>
    <input type='submit' name='btn[upload]' value='...und hochladen'></form>
	</td></tr></table>
	<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td align=\"right\">BELEG<br/>EIGENKONTO</td><td><b>VALUTA</b><br/>B-DATUM</td><td>ZP_ZE</td><td>KTO<br/>BLZ</td><td>VERWENDUNGSZWECK</td><td>AUFTRAGSART<br/>BUCHUNGSTEXT</td><td>SVWZ<br/>EREF<br/>MREF<br/>CRED<br/>ENTG</td><td>IBAN<br/>BIC<br/>ANAM<br/>ABWA<br/>ABWE</td><td>KATEGORIE</td><td align=\"right\">BETRAG<br/>WAEHRUNG</td></tr>";
	foreach($result as $row) {
		$a_anzahl++;// += $row['Belege'];
		$color++;
		IF($color%2) { $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; } 
			ELSE { $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\">"; }
		$o_cont .= "<img src=\"images/leer.gif\"></td>
		<td align=\"right\">".$row['BELEG']."<br/>".$row['EIGENKONTO']."</td>
		<td width=\"75\"><b>".$row['VALUTA']."</b><br/>".$row['DATUM']."</td>
		<td>".$row['ZP_ZE']."</td>
		<td>".$row['KTO_IBAN']."<br/>".$row['BLZ_BIC']."</td>
		<td>".$row['VERWENDUNGSZWECK']."</td>
		<td>".$row['AUFTRAGSART']."<br/>".$row['BUCHUNGSTEXT']."</td>
		<td>".$row[SVWZ]."<br/>".$row[EREF]."<br/>".$row['MREF']."<br/>".$row['CRED']."<br/>".$row['ENTG']."</td>
		<td>".$row['IBAN']."<br/>".$row['BIC']."<br/>".$row[ANAM]."<br/>".$row[ABWA]."<br/>".$row[ABWE]."</td>
		<td>".$row['KATEGORIE']."</td>
		<td align=\"right\">".number_format($row['BETRAG'], 2, ",", ".")."&nbsp;&euro;<br/>".$row['WAEHRUNG']."</td>
		</tr>";
	}
	$o_cont .= "</table>";

}
?>