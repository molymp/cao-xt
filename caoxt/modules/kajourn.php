<?php
// error_reporting(E_ALL); 
// ini_set("display_errors", true);

$o_head = "Kassenjournal für Lastschriftbelege";
$o_navi = "";

if ($usr_rights) {
	if ($_GET['action'] == "detail") {
		// Header: main.php?section=".$_GET['section']."&module=kajourn&action=details&id=xxxxxxx
		$res_id   = mysql_query("SELECT VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, KUN_NUM, NSUMME, BSUMME, BRUTTO_FLAG FROM JOURNAL WHERE REC_ID=" . $_GET[id], $db_id);
		$maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
		mysql_free_result($res_id);
		$res_id  = mysql_query("SELECT REC_ID, ARTIKEL_ID, POSITION, MENGE, ARTNUM, BEZEICHNUNG, BARCODE, EPREIS, GPREIS, STEUER_CODE, ARTIKELTYP, BRUTTO_FLAG FROM JOURNALPOS WHERE JOURNAL_ID=" . $_GET[id] . " ORDER BY POSITION ASC", $db_id);
		$posdata = array();
		$number  = mysql_num_rows($res_id); // Detaildaten / Positionen abarbeiten
		for ($j = 0; $j < $number; $j++) {
			array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
		}
		mysql_free_result($res_id);
		
		// Grunddaten gesammelt, suche Kurzname und gebe aus:
		$o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
		$o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"10\" valign=\"middle\"><b>&nbsp;Allgemeine Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td>" .$maindata[BRUTTO_FLAG] . "</td></tr>";
		$o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"11\" align=\"center\">";
		$o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
		$o_cont .= "<td>Beleg:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;" . $maindata[VRENUM] . "</td></tr></table></td><td>Kunde:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;" . $maindata[KUN_NAME1] . " " . $maindata[KUN_NAME2] . "</td></tr></table></td><td>VK-Netto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">" . $maindata[NSUMME] . " &euro;&nbsp;</td></tr></table></td></tr>";
		$o_cont .= "<tr><td>Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;" . $maindata[RDATUM] . "</td></tr></table></td><td>Kundenr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;" . $maindata[KUN_NUM] . "</td></tr></table></td><td>VK-Brutto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">" . $maindata[BSUMME] . " &euro;&nbsp;</td></tr></table></td>";
		$o_cont .= "</tr></table></td></tr>";
		$o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"10\" valign=\"middle\"><b>&nbsp;Positionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
		$o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Pos.</td><td>&nbsp;Typ</td><td>&nbsp;Artikelnummer</td><td>&nbsp;Barcode</td><td>&nbsp;Kurzname</td><td>&nbsp;Menge</td><td>&nbsp;E-Preis</td><td>&nbsp;G-Preis</td><td>&nbsp;SteuerCode</td></tr>";
		
		for ($j = 0; $j < $number; $j++) {
			$o_cont .= "<tr bgcolor=\"";
			if ($j % 2) {$o_cont .= "#ffffdd";} else {$o_cont .= "#ffffff";}
			$o_cont .= "\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;" . $posdata[$j][POSITION] . "</td><td>&nbsp;" . $posdata[$j][ARTIKELTYP] . "</td><td>&nbsp;" . $posdata[$j][ARTNUM] . "</td><td>&nbsp;" . $posdata[$j][BARCODE] . "</td><td>&nbsp;" . $posdata[$j][BEZEICHNUNG] . "</td><td align=\"right\">" . number_format($posdata[$j][MENGE], 0) . "&nbsp;</td><td>&nbsp;" . $posdata[$j][EPREIS] . "</td><td>&nbsp;" . $posdata[$j][GPREIS] . "</td><td>&nbsp;" . $posdata[$j][STEUER_CODE] . "</td><td>&nbsp;" . $posdata[$j][BRUTTO_FLAG] . "</td>";
		}
		$o_cont .= "</table>";
		
		$o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=" . $_GET['section'] . "&module=kajourn&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";
	} elseif ($_GET['action'] == "create") {
		// Header: main.php?section=".$_GET['section']."&module=kajourn&action=create&type=xxxxxxx&id=xxxxxxx
		$res_id   = mysql_query("SELECT * FROM JOURNAL WHERE REC_ID=" . $_GET[id], $db_id);
		$maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
		mysql_free_result($res_id);
		$res_id  = mysql_query("SELECT * FROM JOURNALPOS WHERE JOURNAL_ID=" . $_GET[id] . " ORDER BY POSITION ASC", $db_id);
		$posdata = array();
		$number  = mysql_num_rows($res_id); // Detaildaten / Positionen abarbeiten
		for ($j = 0; $j < $number; $j++) {
			array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
		}
		mysql_free_result($res_id);
		$res_id = mysql_query("SELECT REC_ID FROM JOURNAL WHERE 1 ORDER BY REC_ID DESC LIMIT 1", $db_id);
		$tmp_id = mysql_fetch_array($res_id, MYSQL_ASSOC);
		mysql_free_result($res_id);
		$maindata['REC_ID'] = $tmp_id['REC_ID'] + 1;
		
		// VRENUM bauen ----------
		$rec_id  = mysql_query("SELECT VAL_INT2, VAL_INT3 FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='EDIT'", $db_id);
		
		$rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
		mysql_free_result($rec_id);
		
		$l_template = $rec_tmp['VAL_INT3']; // Wieviele Stellen hat die Belegnummer?
		$l_current  = strlen($rec_tmp['VAL_INT2']);
		$l_diff     = $l_template - $l_current;
		
		$kassenbeleg = $maindata['VRENUM'];
		$maindata['VRENUM'] = "EDI-"; // String mit führenden Nullen bauen
		
		while ($l_diff) {
			$maindata['VRENUM'] .= "0";
			$l_diff--;
		}
		$rec_tmp['VAL_INT2']++;
		$maindata['VRENUM'] .= $rec_tmp['VAL_INT2']; // String komplett, neue NEXT_EDIT in REGISTRY eintragen
		$rec_id = mysql_query("UPDATE REGISTRY SET VAL_INT2='" . $rec_tmp['VAL_INT2'] . "' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='EDIT'", $db_id);
		$poscnt = 0;
		
		// Quelle setzen (Lieferschein in Bearbeitung)
		if ($_GET['type'] == "lieferschein") {
			$maindata['QUELLE'] = "12";
			$b_type             = "ein Lieferschein";
			$b_link             = "lieferschein";
		} 
		
		// Datensatz in LIEFERSCHEIN erstellen
		if (mysql_query("INSERT INTO LIEFERSCHEIN (VLSNUM, EDI_FLAG, STORNO_FLAG, KM_STAND, ADDR_ID, PR_EBENE, LIEFART, ZAHLART, GEWICHT, KOST_NETTO, WERT_NETTO, LOHN, WARE, TKOST, ROHGEWINN, MWST_0, MWST_1, MWST_2, MWST_3, NSUMME_0, NSUMME_1, NSUMME_2, NSUMME_3, NSUMME, MSUMME_0, MSUMME_1, MSUMME_2, MSUMME_3, MSUMME, BSUMME_0, BSUMME_1, BSUMME_2, BSUMME_3, BSUMME, ATSUMME, PROVIS_WERT, WAEHRUNG, KURS, GEGENKONTO, ERSTELLT, LDATUM, ERST_NAME, KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3, KUN_ABTEILUNG, KUN_STRASSE, KUN_LAND, KUN_PLZ, KUN_ORT, PROJEKT, INFO, BRUTTO_FLAG, MWST_FREI_FLAG) VALUES (\"" . $maindata['VRENUM'] . "\", \"Y\", \"N\", \"-1\", \"" . $maindata['ADDR_ID'] . "\", \"" . $maindata['PR_EBENE'] . "\", \"7\", \"9\", \"" . $maindata['GEWICHT'] . "\", \"" . $maindata['KOST_NETTO'] . "\", \"" . $maindata['WERT_NETTO'] . "\", \"" . $maindata['LOHN'] . "\", \"" . $maindata['WARE'] . "\", \"" . $maindata['TKOST'] . "\", \"" . $maindata['ROHGEWINN'] . "\", \"" . $maindata['MWST_0'] . "\", \"" . $maindata['MWST_1'] . "\", \"" . $maindata['MWST_2'] . "\", \"" . $maindata['MWST_3'] . "\", \"" . $maindata['NSUMME_0'] . "\", \"" . $maindata['NSUMME_1'] . "\", \"" . $maindata['NSUMME_2'] . "\", \"" . $maindata['NSUMME_3'] . "\", \"" . $maindata['NSUMME'] . "\", \"" . $maindata['MSUMME_0'] . "\", \"" . $maindata['MSUMME_1'] . "\", \"" . $maindata['MSUMME_2'] . "\", \"" . $maindata['MSUMME_3'] . "\", \"" . $maindata['MSUMME'] . "\", \"" . $maindata['BSUMME_0'] . "\", \"" . $maindata['BSUMME_1'] . "\", \"" . $maindata['BSUMME_2'] . "\", \"" . $maindata['BSUMME_3'] . "\", \"" . $maindata['BSUMME'] . "\", \"" . $maindata['ATSUMME'] . "\", \"" . $maindata['PROVIS_WERT'] . "\", \"" . $maindata['WAEHRUNG'] . "\", \"" . $maindata['KURS'] . "\", \"" . $maindata['GEGENKONTO'] . "\", CURDATE(), CURDATE(), \"" . $usr_name . "\", \"" . $maindata['KUN_NUM'] . "\", \"" . $maindata['KUN_ANREDE'] . "\", \"" . $maindata['KUN_NAME1'] . "\", \"" . $maindata['KUN_NAME2'] . "\", \"" . $maindata['KUN_NAME3'] . "\", \"" . $maindata['KUN_ABTEILUNG'] . "\", \"" . $maindata['KUN_STRASSE'] . "\", \"" . $maindata['KUN_LAND'] . "\", \"" . $maindata['KUN_PLZ'] . "\", \"" . $maindata['KUN_ORT'] . "\", \"Aus Kassenbeleg " . $kassenbeleg . "\", \"" . $maindata['INFO'] . "\", \"" . $maindata['BRUTTO_FLAG'] . "\", \"" . $maindata['MWST_FREI_FLAG'] . "\")", $db_id)) {
			$b_id = mysql_insert_id($db_id);

			// Datensätze in LIEFERSCHEIN_POS erstellen
			foreach ($posdata as $pos) {
				mysql_query("INSERT INTO LIEFERSCHEIN_POS (LIEFERSCHEIN_ID, ARTIKELTYP, ARTIKEL_ID, TOP_POS_ID, ADDR_ID, ATRNUM, VLSNUM, POSITION, MATCHCODE, ARTNUM, BARCODE, MENGE, LAENGE, BREITE, HOEHE, GROESSE, DIMENSION, GEWICHT, ME_EINHEIT, PR_EINHEIT, VPE, EK_PREIS, CALC_FAKTOR, EPREIS, GPREIS, E_RGEWINN, G_RGEWINN, RABATT, RABATT2, RABATT3, E_RABATT_BETRAG, G_RABATT_BETRAG, STEUER_CODE, ALTTEIL_PROZ, ALTTEIL_STCODE, PROVIS_PROZ, PROVIS_WERT, GEBUCHT, GEGENKTO, BEZEICHNUNG, SN_FLAG, ALTTEIL_FLAG, BEZ_FEST_FLAG, BRUTTO_FLAG, NO_RABATT_FLAG) VALUES (\"" . $b_id . "\", \"F\", \"" . $pos['ARTIKEL_ID'] . "\", \"" . $pos['TOP_POS_ID'] . "\", \"" . $pos['ADDR_ID'] . "\", \"" . $pos['ATRNUM'] . "\", \"" . $pos['VLSNUM'] . "\", \"" . $pos['POSITION'] . "\", \"" . addslashes($pos['MATCHCODE']) . "\", \"" . $pos['ARTNUM'] . "\", \"" . $pos['BARCODE'] . "\", \"" . $pos['MENGE'] . "\", \"" . $pos['LAENGE'] . "\", \"" . $pos['BREITE'] . "\", \"" . $pos['HOEHE'] . "\", \"" . $pos['GROESSE'] . "\", \"" . $pos['DIMENSION'] . "\", \"" . $pos['GEWICHT'] . "\", \"" . $pos['ME_EINHEIT'] . "\", \"" . $pos['PR_EINHEIT'] . "\", \"" . $pos['VPE'] . "\", \"" . $pos['EK_PREIS'] . "\", \"" . $pos['CALC_FAKTOR'] . "\", \"" . $pos['EPREIS'] . "\", \"" . $pos['GPREIS'] . "\", \"" . $pos['E_RGEWINN'] . "\", \"" . $pos['G_RGEWINN'] . "\", \"" . $pos['RABATT'] . "\", \"" . $pos['RABATT2'] . "\", \"" . $pos['RABATT3'] . "\", \"" . $pos['E_RABATT_BETRAG'] . "\", \"" . $pos['G_RABATT_BETRAG'] . "\", \"" . $pos['STEUER_CODE'] . "\", \"" . $pos['ALTTEIL_PROZ'] . "\", \"" . $pos['ALTTEIL_STCODE'] . "\", \"" . $pos['PROVIS_PROZ'] . "\", \"" . $pos['PROVIS_WERT'] . "\", \"N\", \"" . $pos['GEGENKTO'] . "\", \"Aus Kassenbeleg " . $kassenbeleg . " - " . addslashes($pos['BEZEICHNUNG']) . "\", \"" . $pos['SN_FLAG'] . "\", \"" . $pos['ALTTEIL_FLAG'] . "\", \"" . $pos['BEZ_FEST_FLAG'] . "\", \"" . $maindata['BRUTTO_FLAG'] . "\", \"" . $pos['NO_RABATT_FLAG'] . "\")", $db_id);
				$poscnt++;
			}
			// Zum Schluss schreiben wir noch in unser YT_LIEFERSCHEIN-Journal, dass wir für den aktuellen Beleg einen neuen Lieferschein
			// erstellt haben, damit wir in der Übersicht entsprechend markieren können.
			mysql_query("INSERT INTO XT_LIEFERSCHEINE (BERECHNET, KUN_ID, KUN_NAME, BELEG_NR, BELEG_DATUM, LIEFERSCHEIN_ID, LIEFERSCHEIN_DATUM, ANZAHL_POSITIONEN, NSUMME, MSUMME, BSUMME) VALUES ( \"N\", \"" . $maindata['ADDR_ID'] . "\", \"" . $maindata['KUN_NAME1'] . "\",  \"" . $kassenbeleg . "\", \"" . $maindata['RDATUM'] . "\", \"" . $maindata['VRENUM'] . "\",  CURDATE(), $poscnt , \"" . $maindata['NSUMME'] . "\",  \"" . $maindata['MSUMME'] . "\",  \"" . $maindata['BSUMME'] . "\")", $db_id); 
			// Jetzt kommt noch ein kurzer Status mit einem 'Zurück'-Knopf
			$o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         Es wurde " . $b_type . " mit " . $poscnt . " Positionen erstellt.<br><br>
                        <br>
                         &nbsp;&nbsp;&nbsp;&nbsp;<button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
		} else {
			$o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         <b>Fehler:</b> " . mysql_error() . "<br><br>
                        <br>
                         <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
		}
	} else {
		if (!$_GET['month']) {
			// Header: main.php?section=".$_GET['section']."&module=kajourn
			$month = date("n");
			$year  = date("Y");
		} else {
			// Header: main.php?section=".$_GET['section']."&module=kajourn&month=xx&year=xxxx
			$month = $_GET['month'];
			$year  = $_GET['year'];
		}
		include("modules/inc/dateselectordatevex.php");
		$o_navi = $dateselector;
		
		$mysqlquery = "SELECT REC_ID, VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, NSUMME, MSUMME, BSUMME, WAEHRUNG FROM JOURNAL WHERE QUELLE=3 AND QUELLE_SUB=2 AND ZAHLART=5 AND YEAR(RDATUM)=" . $year;
		IF ($month < 20) $mysqlquery .= " AND MONTH(RDATUM)=" . $month;
		$mysqlquery .= " ORDER BY KUN_NAME1, VRENUM ASC";
		$res_id  = mysql_query($mysqlquery, $db_id);
		$res_num = mysql_numrows($res_id);
		$result  = array();
		for ($i = 0; $i < $res_num; $i++) {
			array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC)); // Journaldatensätze in Array
		}
		mysql_free_result($res_id);
		
		
		$o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>Beleg</td><td>Datum</td><td>Name des Kunden</td><td>Netto</td><td>MwSt</td><td>Brutto</td><td>Erstelle Lieferschein</td><td>Hammascho</td></tr>";
		foreach ($result as $row) {
			
			$res_id = mysql_query("select BELEG_NR from XT_LIEFERSCHEINE where BELEG_NR = " . $row['VRENUM'] . " limit 1", $db_id);
			$gebucht = 0;
			$res_num = mysql_numrows($res_id);
			if ($res_num > 0 ) $gebucht = 1;
			mysql_free_result($res_id);
			
			$color++;
			$o_cont .= "<tr bgcolor=\"";
			if ($color % 2) {$o_cont .= "#ffffff";} else {$o_cont .= "#ffffdd";}
			$o_cont .= "\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=" . $_GET['section'] . "&module=kajourn&action=detail&id=" . $row['REC_ID'] . "\">" . $row['VRENUM'] . "</a></td><td>" . $row['RDATUM'] . "</td><td>" . $row['KUN_NAME1'] . " " . $row['KUN_NAME2'] . "</td><td align=\"right\">" . number_format($row['NSUMME'], 2, ",", ".") . "&nbsp;&euro;</td><td align=\"right\">" . number_format($row['MSUMME'], 2, ",", ".") . "&nbsp;&euro;</td><td align=\"right\">" . number_format($row['BSUMME'], 2, ",", ".") . "&nbsp;&euro;</td><td align=\"center\"><a href=\"main.php?section=" . $_GET['section'] . "&module=kajourn&action=create&type=lieferschein&id=" . $row['REC_ID'] . "\">Lieferschein</a></td><td>" . $gebucht . "</td></tr>";
		}
		$o_cont .= "</table>";
	}
} else {
	$o_cont = "<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
}
?>