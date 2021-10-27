<?php

// ------------------------------------------------------------------------------------------------
//	Benötigte Funktionen:

function get_zahlart($db_id) {
	$res_id = mysql_query("SELECT NAME, VAL_CHAR AS NUMMER FROM REGISTRY WHERE MAINKEY='MAIN\\\\ZAHLART' ORDER BY VAL_CHAR ASC", $db_id);
	$data = array();
	$number = mysql_num_rows($res_id);
	$data[0]['NAME'] = "";
	$data[0]['NUMMER'] = "";
	for($i=0; $i<$number; $i++) array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
	mysql_free_result($res_id);
	return $data;
}

// ------------------------------------------------------------------------------------------------
//	Session:
session_start();
set_time_limit(6000);
error_reporting(E_ALL & ~E_NOTICE);

if(!$_SESSION['user']) {								// Sessiondaten Login
	echo "FEHLER: Kein Zugriff, nicht am System angemeldet!";
} else {
	include("includes/ini.php");						// Initialisierungsvariablen
	if($db_user && $db_loc) {							//	Datenbank-Login Check
		$tmp_address = $db_loc.":".$db_port;			//	Datenbank-Login
		if($db_id = mysql_connect($tmp_address, $db_user, $db_pass)) {
			if(mysql_select_db($db_name, $db_id)) {
				if($_GET['module']=="rma") {
					$b_kunde = "";
					$b_bericht = "";
					$b_vorgang = "";
					$b_datum = date("d.m.Y");
					$b_name = $_POST['user'];

					if($_GET['id']) {					// Kundendaten zusammenstellen:
						$res_id = mysql_query("SELECT KUN_ID, RS_NAME1, RS_NAME2, RS_STRASSE, RS_PLZ, RS_ORT FROM ".$db_pref."RMA WHERE ID='".$_GET['id']."'", $db_id);
						$kd_rma = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);

						$res_id = mysql_query("SELECT KUNNUM1, NAME1, NAME2, PLZ, ORT, STRASSE FROM ADRESSEN WHERE REC_ID='".$kd_rma['KUN_ID']."'", $db_id);
						$kd_adr = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);

						if(!$kd_rma['RS_NAME1']) $kd_use['NAME1'] = $kd_adr['NAME1']; else $kd_use['NAME1'] = $kd_rma['RS_NAME1'];
						if(!$kd_rma['RS_NAME2']) $kd_use['NAME2'] = $kd_adr['NAME2']; else $kd_use['NAME2'] = $kd_rma['RS_NAME2'];
						if(!$kd_rma['RS_STRASSE']) $kd_use['STRASSE'] = $kd_adr['STRASSE']; else $kd_use['STRASSE'] = $kd_rma['RS_STRASSE'];
						if(!$kd_rma['RS_PLZ']) $kd_use['PLZ'] = $kd_adr['PLZ']; else $kd_use['PLZ'] = $kd_rma['RS_PLZ'];
						if(!$kd_rma['RS_ORT']) $kd_use['ORT'] = $kd_adr['ORT']; else $kd_use['ORT'] = $kd_rma['RS_ORT'];
						$kd_use['KUNNUM'] = $kd_adr['KUNNUM1'];

						$b_kunde = "<table width=\"300\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                 <tr><td align=\"left\">".$kd_use['NAME1']."</td></tr>
                                 <tr><td align=\"left\">".$kd_use['NAME2']."</td></tr>
                                 <tr><td align=\"left\">".$kd_use['STRASSE']."</td></tr>
                                 <tr><td>&nbsp;</td></tr>
                                 <tr><td align=\"left\"><b>".$kd_use['PLZ']."</b> ".$kd_use['ORT']."</td></tr></table>";

                    // Bericht zusammenstellen:
						$res_id = mysql_query("SELECT ART_ID, ART_SNR, ANZAHL, RMANUM, FEHLER, KOMMENTAR FROM ".$db_pref."RMA WHERE ID='".$_GET['id']."'", $db_id);
						$ad_rma = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);

						$res_id = mysql_query("SELECT ARTNUM, KURZNAME FROM ARTIKEL WHERE REC_ID='".$ad_rma['ART_ID']."'", $db_id);
						$ad_art = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);

						$ad_rma['KOMMENTAR'] = stripslashes($ad_rma['KOMMENTAR']);
						$ad_rma['FEHLER'] = stripslashes($ad_rma['FEHLER']);

						if(($_POST['notes']==1) && $ad_rma['KOMMENTAR']) {
							$KOMMENTAR = $ad_rma['KOMMENTAR']."<br><br>".$_POST['info'];
						} else {
							$KOMMENTAR = $_POST['info'];
						}

						$b_bericht = "<table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                   <tr>
                                    <td align=\"left\" width=\"15%\">
                                     <b>Kundennr.:</b>
                                    </td>
                                    <td align=\"left\" width=\"35%\">
                                     ".$kd_use['KUNNUM']."
                                    </td>
                                    <td align=\"left\" width=\"15%\">
                                     <b>RMA-Nr.:</b>
                                    </td>
                                    <td align=\"left\" width=\"35%\">
                                     ".$ad_rma['RMANUM']."
                                    </td>
                                   </tr>
                                   <tr>
                                    <td colspan=\"4\">
                                     &nbsp;
                                    </td>
                                   </tr>
                                   <tr>
                                    <td align=\"left\">
                                     <b>Artikelnr.:</b>
                                    </td>
                                    <td align=\"left\">
                                     ".$ad_art['ARTNUM']."
                                    </td>
                                    <td align=\"left\">
                                     <b>Artikel.:</b>
                                    </td>
                                    <td align=\"left\">
                                     ".$ad_art['KURZNAME']."
                                    </td>
                                   </tr>
                                   <tr>
                                    <td align=\"left\">
                                     <b>Anzahl:</b>
                                    </td>
                                    <td align=\"left\">
                                     ".$ad_rma['ANZAHL']."
                                    </td>
                                    <td align=\"left\">
                                     <b>Seriennr.:</b>
                                    </td>
                                    <td align=\"left\">
                                     ".$ad_rma['ART_SNR']."
                                    </td>
                                   </tr>
                                   <tr>
                                    <td colspan=\"4\">
                                     &nbsp;
                                    </td>
                                   </tr>
                                   <tr>
                                    <td align=\"left\">
                                     <b>Fehler:</b>
                                    </td>
                                    <td align=\"left\"  colspan=\"3\">
                                     ".$ad_rma['FEHLER']."
                                    </td>
                                   </tr>
                                   <tr>
                                    <td colspan=\"4\">
                                     &nbsp;
                                    </td>
                                   </tr>
                                   <tr>
                                    <td align=\"left\">
                                     <b>Bericht:</b>
                                    </td>
                                    <td align=\"left\"  colspan=\"3\">
                                     ".$KOMMENTAR."
                                    </td>
                                   </tr>
                                   <tr>
                                    <td colspan=\"4\">
                                     <br><br><br><br>
                                    </td>
                                   </tr>
                                  </table>";

                    // Sonstiges:

                    $b_vorgang = $ad_rma['RMANUM'];

					} else {
						echo "FEHLER: Keine RMA-Nummer angegeben!";
					}
				} elseif($_GET['module']=="sammler") {
					$b_kunde = "";
					$b_vorgang = "";
					$b_datum = date("d.m.Y");
					$b_name = $_POST['user'];

					if($_GET['id']) {						// Kundendaten zusammenstellen:
						$res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, KUN_NUM, KUN_STRASSE, KUN_PLZ, KUN_LAND, KUN_ORT FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
						$maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);
						$res_id = mysql_query("SELECT REC_ID, ARTIKEL_ID, POSITION, MENGE, ARTNUM FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
						$posdata = array();
						$number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
						for($j=0; $j<$number; $j++) {
							array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
						}
						mysql_free_result($res_id);

						$b_kunde = "<table width=\"300\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                 <tr><td align=\"left\">".$maindata['KUN_NAME1']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME2']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_STRASSE']."</td></tr>
                                 <tr><td>&nbsp;</td></tr>
                                 <tr><td align=\"left\"><b>".$maindata['KUN_LAND']."-".$maindata['KUN_PLZ']."</b> ".$maindata['KUN_ORT']."</td></tr></table>";

                    // Bericht zusammenstellen:
						$b_bericht = "<table width=\"100%\" cellpadding=\"2\" cellspacing=\"0\" border=\"0\">
                                   <tr>
                                    <td align=\"left\" width=\"10%\">
                                     <b>Position</b>
                                    </td>
                                    <td align=\"left\" width=\"10%\">
                                     <b>Artikelnr.</b>
                                    </td>
                                    <td align=\"left\" width=\"50%\">
                                     <b>Artikel</b>
                                    </td>
                                    <td align=\"left\" width=\"10%\">
                                    <b>Anzahl (Soll)</b>
                                    </td>
                                    <td align=\"left\" width=\"10%\">
                                    <b>Anzahl (Ist)</b>
                                    </td>
                                    <td align=\"left\" width=\"10%\">
                                    <b>Fehlmenge</b>
                                    </td>
                                   </tr>
                                   <tr>
                                    <td colspan=\"5\">
                                     &nbsp;
                                    </td>
                                   </tr>";

						foreach($posdata as $row) {
							$tmp_id = mysql_query("SELECT KURZNAME FROM ARTIKEL WHERE REC_ID=".$row['ARTIKEL_ID'], $db_id);
							$tmp = mysql_fetch_array($tmp_id, MYSQL_ASSOC);
							mysql_free_result($tmp_id);

							$b_bericht .= "<tr>
                                        <td align=\"left\">
                                         ".$row['POSITION']."
                                        </td>
                                        <td align=\"left\">
                                         ".$row['ARTNUM']."
                                        </td>
                                        <td align=\"left\">
                                         ".$tmp['KURZNAME']."
                                        </td>
                                        <td align=\"left\">
                                        ".$row['MENGE']."
                                        </td>
                                        <td align=\"left\">
                                        _____
                                        </td>
                                        <td align=\"left\">
                                        _____
                                        </td>
                                       </tr>";
						}

						$b_bericht .= "</table>";
						$b_vorgang = $maindata['VRENUM'];
					} else {
						echo "FEHLER: Keine Belegnummer angegeben!";
					}
				} elseif($_GET['module']=="rechnung") {
					$b_kunde = "";
					$b_vorgang = "";
					$b_kopfdaten = "";
					$b_fussdaten = "";
					$b_datum = date("d.m.Y");
					$b_name = $_POST['user'];

					$zahlarten = get_zahlart($db_id);
					$zahlziel = "";

					if($_GET['id']) {					// Kundendaten zusammenstellen:
						$res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3, KUN_NUM, KUN_STRASSE, KUN_PLZ, KUN_LAND, KUN_ORT, NSUMME, BSUMME, MSUMME, ERST_NAME, ZAHLART, LIEFART, BEST_NAME, ORGNUM, PROJEKT, LDATUM FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
						$maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);
						$res_id = mysql_query("SELECT REC_ID, POSITION, MENGE, ARTNUM, BEZEICHNUNG, EPREIS, GPREIS FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
						$posdata = array();
						$number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
						for($j=0; $j<$number; $j++) {
							array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
						}
						mysql_free_result($res_id);

						$b_kunde = "<table width=\"300\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                 <tr><td align=\"left\">".$maindata['KUN_ANREDE']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME1']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME2']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME3']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_STRASSE']."</td></tr>
                                 <tr><td>&nbsp;</td></tr>
                                 <tr><td align=\"left\"><b>".$maindata['KUN_LAND']."-".$maindata['KUN_PLZ']."</b> ".$maindata['KUN_ORT']."</td></tr></table>";

                    // Kopfdaten zusammenstellen:
						if($maindata['LDATUM']=="1899-12-30") {
							$maindata['LDATUM'] = "";
						}

						$b_kopfdaten = "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\" border=\"1\">
                                     <tr>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Rechnungs-Nr.</div><b>".$maindata['VRENUM']."</b></td>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Kunden-Nr.</div><b>&nbsp;".$maindata['KUN_NUM']."</b></td>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Datum</div><b>".$maindata['RDATUM']."</b></td></tr><tr>
                                      <td align=\"left\" colspan=\"3\"><div style=\"font-size: 10px\">Sachbearbeiter(in)</div><b>&nbsp;".$maindata['ERST_NAME']."</b></td>
                                     </tr></table>";
						$b_info = "<table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                     <tr><td align=\"left\" width=\"10%\">Bestellt durch</td><td align=\"left\" width=\"5%\">:</td><td align=\"left\" width=\"35%\">".$maindata['BEST_NAME']."</td><td align=\"left\" width=\"50%\">".$maindata['PROJEKT']."</td></tr>
                                     <tr><td align=\"left\" width=\"10%\">Bestell-Nr.</td><td align=\"left\" width=\"5%\">:</td><td align=\"left\" width=\"35%\">".$maindata['ORGNUM']."</td><td align=\"left\" width=\"50%\" rowspan=\"2\">Falls nicht anders angegeben stimmt das Lieferdatum mit dem Rechnungsdatum &uuml;berein.</td></tr>
                                     <tr><td align=\"left\" width=\"10%\">Lieferdatum</td><td align=\"left\" width=\"5%\">:</td><td align=\"left\" width=\"35%\">".$maindata['LDATUM']."</td></tr>
                                     </table>";

                    // Fussdaten zusammenstellen:

						foreach($zahlarten as $set) {
							if($set['NUMMER']==$maindata['ZAHLART']) {
								$zahlart = $set['NAME'];
							}
						}

						if($maindata['SOLL_SKONTO']) {
							$zahlziel = $maindata['SOLL_STAGE']." Tage ".$maindata['SOLL_SKONTO']."% Skonto";
							if($maindata['SOLL_NTAGE']) {
								$zahlziel .= ", ".$maindata['SOLL_NTAGE']." Tage Netto";
							}
						} else {
							if($maindata['SOLL_NTAGE']) {
								$zahlziel = $maindata['SOLL_NTAGE']." Tage";
							} else {
								$zahlziel = "Zahlbar sofort";
							}
						}

						$b_fussdaten = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\">
                    		         <tr><td>
                    		          <div style=\"font-size: 10px\">Es gelten unsere allgemeinen Gesch&auml;ftsbedingungen.<br>S&auml;mtliche Ware bleibt bis zur vollständigen Bezahlung unser Eigentum.<br></div>
                    		          <table width=\"250\" cellpadding=\"2\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Zahlungsziel:</b></td><td align=\"right\"><b>".$zahlziel."</b></td></tr><tr><td align=\"left\"><b>Zahlungsart:</b></td><td align=\"right\"><b>".$zahlart."</b></td></tr></table>
                    		         </td><td align=\"right\">
                                      <table width=\"300\" cellpadding=\"3\" cellspacing=\"0\" border=\"1\">
                                       <tr>
                                        <td><table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Zwischensumme</b></td><td align=\"right\"><b>".number_format($maindata['NSUMME'], 2, ",", ".")." &euro;</b></td></tr><tr><td align=\"left\"><b>zzgl. MwSt</b></td><td align=\"right\"><b>".number_format($maindata['MSUMME'], 2, ",", ".")." &euro;</b></td></tr></table></td></tr></tr>
                                        <td><table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Endbetrag</b></td><td align=\"right\"><b>".number_format($maindata['BSUMME'], 2, ",", ".")." &euro;</b></td></tr></table></td>
                                       </tr></table></td></tr></table>";

                    // Bericht zusammenstellen:

						$b_bericht = "<table width=\"100%\" cellpadding=\"2\" cellspacing=\"0\" border=\"0\">
                                   <tr>
                                    <td align=\"center\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Position
                                    </td>
                                    <td align=\"left\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Artikelnr.
                                    </td>
                                    <td align=\"left\" width=\"50%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Artikelbezeichnung
                                    </td>
                                    <td align=\"left\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Menge
                                    </td>
                                    <td align=\"right\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Einzelpreis
                                    </td>
                                    <td align=\"right\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Gesamtpreis
                                    </td>
                                   </tr>";

						foreach($posdata as $row) {
							$b_bericht .= "<tr>
                                        <td align=\"center\" valign=\"top\">
                                         ".$row['POSITION']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                         ".$row['ARTNUM']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                         ".$row['BEZEICHNUNG']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                        ".number_format($row['MENGE'], 2, ',', '')."
                                        </td>
                                        <td align=\"right\" valign=\"top\">
                                        ".number_format($row['EPREIS'], 2, ',', '.')." &euro;
                                        </td>
                                        <td align=\"right\" valign=\"top\">
                                        ".number_format($row['GPREIS'], 2, ',', '.')." &euro;
                                        </td>
                                       </tr>
                                       <tr>
                                        <td colspan=\"6\">
                                         <hr align=\"center\" size=\"1\" noshade>
                                        </td>
                                       </tr>";
						}

						$b_bericht .= "</table>";

                    // Sonstiges:

						$b_vorgang = $maindata['VRENUM'];

					} else {
						echo "FEHLER: Keine Belegnummer angegeben!";
					}
				} elseif($_GET['module']=="angebot") {
					$b_kunde = "";
					$b_vorgang = "";
					$b_kopfdaten = "";
					$b_fussdaten = "";
					$b_datum = date("d.m.Y");
					$b_name = $_POST['user'];

					$zahlarten = get_zahlart($db_id);
					$zahlziel = "";

					if($_GET['id']) { 					// Kundendaten zusammenstellen:
						$res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3, KUN_NUM, KUN_STRASSE, KUN_PLZ, KUN_LAND, KUN_ORT, NSUMME, BSUMME, MSUMME, ERST_NAME, ZAHLART, LIEFART, BEST_NAME, ORGNUM, PROJEKT, LDATUM FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
						$maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
						mysql_free_result($res_id);
						$res_id = mysql_query("SELECT REC_ID, POSITION, MENGE, ARTNUM, BEZEICHNUNG, EPREIS, GPREIS FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
						$posdata = array();
						$number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
						for($j=0; $j<$number; $j++) {
							array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
						}
						mysql_free_result($res_id);

						$b_kunde = "<table width=\"300\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                 <tr><td align=\"left\">".$maindata['KUN_ANREDE']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME1']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME2']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_NAME3']."</td></tr>
                                 <tr><td align=\"left\">".$maindata['KUN_STRASSE']."</td></tr>
                                 <tr><td>&nbsp;</td></tr>
                                 <tr><td align=\"left\"><b>".$maindata['KUN_LAND']."-".$maindata['KUN_PLZ']."</b> ".$maindata['KUN_ORT']."</td></tr></table>";

                    // Kopfdaten zusammenstellen:

						if($maindata['LDATUM']=="1899-12-30") {
							$maindata['LDATUM'] = "";
						}

						$b_kopfdaten = "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\" border=\"1\">
                                     <tr>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Angebots-Nr.</div><br><b>".$maindata['VRENUM']."</b></td>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Kunden-Nr.</div><br><b>".$maindata['KUN_NUM']."</b></td>
                                      <td align=\"center\"><div style=\"font-size: 10px\">Datum</div><br><b>".$maindata['RDATUM']."</b></td></tr><tr>
                                      <td align=\"left\" colspan=\"3\"><div style=\"font-size: 10px\">Sachbearbeiter(in)</div><br><b>".$maindata['ERST_NAME']."</b></td>
                                     </tr></table>";
						$b_info = "<table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">
                                     <tr><td align=\"left\" width=\"10%\">Angefragt durch</td><td align=\"left\" width=\"5%\">:</td><td align=\"left\" width=\"35%\">".$maindata['BEST_NAME']."</td><td align=\"left\" width=\"50%\">".$maindata['PROJEKT']."</td></tr>
                                     <tr><td align=\"left\" width=\"10%\">Anfrage-Nr.</td><td align=\"left\" width=\"5%\">:</td><td align=\"left\" width=\"35%\">".$maindata['ORGNUM']."</td></tr>
                                     </table>";

                    // Fussdaten zusammenstellen:

						foreach($zahlarten as $set) {
							if($set['NUMMER']==$maindata['ZAHLART']) {
								$zahlart = $set['NAME'];
							}
						}

						if($maindata['SOLL_SKONTO']) {
							$zahlziel = $maindata['SOLL_STAGE']." Tage ".$maindata['SOLL_SKONTO']."% Skonto";
							if($maindata['SOLL_NTAGE']) {
								$zahlziel .= ", ".$maindata['SOLL_NTAGE']." Tage Netto";
							}
						} else {
							if($maindata['SOLL_NTAGE']) {
								$zahlziel = $maindata['SOLL_NTAGE']." Tage";
							} else {
								$zahlziel = "Zahlbar sofort";
							}
						}

						$b_fussdaten = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\">
                    		         <tr><td>
                    		          <div style=\"font-size: 10px\">Es gelten unsere allgemeinen Gesch&auml;ftsbedingungen.<br>S&auml;mtliche Ware bleibt bis zur vollständigen Bezahlung unser Eigentum.<br></div>
                    		          <table width=\"250\" cellpadding=\"2\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Zahlungsziel:</b></td><td align=\"right\"><b>".$zahlziel."</b></td></tr><tr><td align=\"left\"><b>Zahlungsart:</b></td><td align=\"right\"><b>".$zahlart."</b></td></tr></table>
                    		         </td><td align=\"right\">
                                      <table width=\"300\" cellpadding=\"3\" cellspacing=\"0\" border=\"1\">
                                       <tr>
                                        <td><table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Zwischensumme</b></td><td align=\"right\"><b>".number_format($maindata['NSUMME'], 2, ",", ".")." &euro;</b></td></tr><tr><td align=\"left\"><b>zzgl. MwSt</b></td><td align=\"right\"><b>".number_format($maindata['MSUMME'], 2, ",", ".")." &euro;</b></td></tr></table></td></tr></tr>
                                        <td><table width=\"100%\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\"><tr><td align=\"left\"><b>Endbetrag</b></td><td align=\"right\"><b>".number_format($maindata['BSUMME'], 2, ",", ".")." &euro;</b></td></tr></table></td>
                                       </tr></table></td></tr></table>";

                    // Bericht zusammenstellen:

						$b_bericht = "<table width=\"100%\" cellpadding=\"2\" cellspacing=\"0\" border=\"0\">
                                   <tr>
                                    <td align=\"center\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Position
                                    </td>
                                    <td align=\"left\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Artikelnr.
                                    </td>
                                    <td align=\"left\" width=\"50%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                     Artikelbezeichnung
                                    </td>
                                    <td align=\"left\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Menge
                                    </td>
                                    <td align=\"right\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Einzelpreis
                                    </td>
                                    <td align=\"right\" width=\"10%\" style=\"background: #000000; color: #ffffff; font-weight: bold\">
                                    Gesamtpreis
                                    </td>
                                   </tr>";

						foreach($posdata as $row) {
							$b_bericht .= "<tr>
                                        <td align=\"center\" valign=\"top\">
                                         ".$row['POSITION']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                         ".$row['ARTNUM']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                         ".$row['BEZEICHNUNG']."
                                        </td>
                                        <td align=\"left\" valign=\"top\">
                                        ".number_format($row['MENGE'], 2, ',', '')."
                                        </td>
                                        <td align=\"right\" valign=\"top\">
                                        ".number_format($row['EPREIS'], 2, ',', '.')." &euro;
                                        </td>
                                        <td align=\"right\" valign=\"top\">
                                        ".number_format($row['GPREIS'], 2, ',', '.')." &euro;
                                        </td>
                                       </tr>
                                       <tr>
                                        <td colspan=\"6\">
                                         <hr align=\"center\" size=\"1\" noshade>
                                        </td>
                                       </tr>";
						}

						$b_bericht .= "</table>";

						$b_vorgang = $maindata['VRENUM'];

					} else {
						echo "FEHLER: Keine Belegnummer angegeben!";
					}
				} else {
					echo "FEHLER: Unbekanntes Ursprungsmodul!";
				}

// ------------------------------------------------------------------------------------------------
//	Template einlesen, Spacer ersetzen und Ausgabe:
				$output = file_get_contents("reports/".$_GET['module'].".html");
				$output = str_replace("@@kunde@@", $b_kunde, $output);		// ggf. Kundendaten
				$output = str_replace("@@bericht@@", $b_bericht, $output);		// Berichtsdaten
				$output = str_replace("@@kopfdaten@@", $b_kopfdaten, $output);		// Berichtsdaten
				$output = str_replace("@@info@@", $b_info, $output);		// Berichtsdaten
				$output = str_replace("@@fussdaten@@", $b_fussdaten, $output);		// Berichtsdaten
				$output = str_replace("@@vorgang@@", $b_vorgang, $output);		// Vorgangsnummer
				$output = str_replace("@@datum@@", $b_datum, $output);		// Datum
				$output = str_replace("@@bearbeiter@@", $b_name, $output);		// Sachbearbeiter
				print $output;
// ------------------------------------------------------------------------------------------------

// Datenbank / Errorhandling:
			} else {
				echo "FEHLER: Kein Zugriff auf die Datenbank!";
			}
		} else {
			echo "FEHLER: Kein Zugriff auf den Datenbankserver!";
		}
		}
	}
?>