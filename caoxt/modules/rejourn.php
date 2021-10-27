	<?php 
$o_head = "Rechnungsjournal";
$o_navi = "";

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=rejourn&action=details&id=xxxxxxx

        $res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, KUN_NUM, NSUMME, BSUMME FROM JOURNAL WHERE REC_ID=".$_GET[id], $db_id);
        $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);
        $res_id = mysql_query("SELECT REC_ID, ARTIKEL_ID, POSITION, MENGE, ARTNUM, BEZEICHNUNG, BARCODE, EPREIS, GPREIS, STEUER_CODE, ARTIKELTYP FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
        $posdata = array();
        $number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
        for($j=0; $j<$number; $j++)
          {
            array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);

        // Grunddaten gesammelt, suche Kurzname und gebe aus:

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"10\" valign=\"middle\"><b>&nbsp;Allgemeine Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"10\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Beleg:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[VRENUM]."</td></tr></table></td><td>Kunde:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[KUN_NAME1]." ".$maindata[KUN_NAME2]."</td></tr></table></td><td>VK-Netto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[NSUMME]." &euro;&nbsp;</td></tr></table></td></tr>";
        $o_cont .= "<tr><td>Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[RDATUM]."</td></tr></table></td><td>Kundenr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[KUN_NUM]."</td></tr></table></td><td>VK-Brutto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[BSUMME]." &euro;&nbsp;</td></tr></table></td>";
        $o_cont .= "</tr></table></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"10\" valign=\"middle\"><b>&nbsp;Positionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Pos.</td><td>&nbsp;Typ</td><td>&nbsp;Artikelnummer</td><td>&nbsp;Barcode</td><td>&nbsp;Kurzname</td><td>&nbsp;Menge</td><td>&nbsp;E-Preis</td><td>&nbsp;G-Preis</td><td>&nbsp;SteuerCode</td></tr>";

        for($j=0; $j<$number; $j++)
          {
            if($j%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;".$posdata[$j][ARTIKELTYP]."</td><td>&nbsp;".$posdata[$j][ARTNUM]."</td><td>&nbsp;".$posdata[$j][BARCODE]."</td><td>&nbsp;".$posdata[$j][BEZEICHNUNG]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td><td>&nbsp;".$posdata[$j][EPREIS]."</td><td>&nbsp;".$posdata[$j][GPREIS]."</td><td>&nbsp;".$posdata[$j][STEUER_CODE]."</td>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;".$posdata[$j][ARTIKELTYP]."</td><td>&nbsp;".$posdata[$j][ARTNUM]."</td><td>&nbsp;".$posdata[$j][BARCODE]."</td><td>&nbsp;".$posdata[$j][BEZEICHNUNG]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td><td>&nbsp;".$posdata[$j][EPREIS]."</td><td>&nbsp;".$posdata[$j][GPREIS]."</td><td>&nbsp;".$posdata[$j][STEUER_CODE]."</td>";
              }
          }
        $o_cont .= "</table>";

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Zurück zur Auswahl&nbsp;</a></td></tr></table>";
      }
    elseif($_GET['action']=="create")
      {
        // Header: main.php?section=".$_GET['section']."&module=rejourn&action=create&type=xxxxxxx&id=xxxxxxx

        $res_id = mysql_query("SELECT * FROM JOURNAL WHERE REC_ID=".$_GET[id], $db_id);
        $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);
        $res_id = mysql_query("SELECT * FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
        $posdata = array();
        $number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
        for($j=0; $j<$number; $j++)
          {
            array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);
        $res_id = mysql_query("SELECT REC_ID FROM JOURNAL WHERE 1 ORDER BY REC_ID DESC LIMIT 1", $db_id);
        $tmp_id = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        $maindata['REC_ID'] = $tmp_id['REC_ID']+1;

        // VRENUM bauen ----------

        $rec_id = mysql_query("SELECT VAL_INT2, VAL_INT3 FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='EDIT'", $db_id);
        $rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
        mysql_free_result($rec_id);

        $l_template = $rec_tmp['VAL_INT3'];				// Wieviele Stellen hat die Belegnummer?
        $l_current = strlen($rec_tmp['VAL_INT2']);
        $l_diff = $l_template - $l_current;

        $maindata['VRENUM'] = "";					// String mit führenden Nullen bauen

        while($l_diff)
          {
            $maindata['VRENUM'] .= "0";
            $l_diff--;
          }

        $maindata['VRENUM'] .= $rec_tmp['VAL_INT2'];		// String komplett, neue NEXT_EDIT in REGISTRY eintragen

        $rec_tmp['VAL_INT2']++;

        $rec_id = mysql_query("UPDATE REGISTRY SET VAL_INT2='".$rec_tmp['VAL_INT2']."' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='EDIT'", $db_id);

        // -----------------------

        $poscnt = 0;

        // Quelle setzen (Angebots- oder Rechnungsformular)

        if($_GET['type']=="angebot")
          {
            $maindata['QUELLE'] = "11";
            $b_type = "ein Angebot";
            $b_link = "angebot";
          }
        else
          {
            $maindata['QUELLE'] = "13";
            $b_type = "eine Rechnung";
            $b_link = "rechnung";
          }

        // Datensatz in Journal erstellen

        if(mysql_query("INSERT INTO JOURNAL (REC_ID, QUELLE, QUELLE_SUB, KM_STAND, ADDR_ID, VRENUM, RDATUM, PR_EBENE, LIEFART, ZAHLART, GEWICHT, KOST_NETTO, WERT_NETTO, LOHN, WARE, TKOST, ROHGEWINN, MWST_0, MWST_1, MWST_2, MWST_3, NSUMME_0, NSUMME_1, NSUMME_2, NSUMME_3, NSUMME, MSUMME_0, MSUMME_1, MSUMME_2, MSUMME_3, MSUMME, BSUMME_0, BSUMME_1, BSUMME_2, BSUMME_3, BSUMME, ATSUMME, ATMSUMME, PROVIS_WERT, WAEHRUNG, KURS, GEGENKONTO, STADIUM, ERSTELLT, ERST_NAME, KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3, KUN_ABTEILUNG, KUN_STRASSE, KUN_LAND, KUN_PLZ, KUN_ORT, PROJEKT, INFO, BRUTTO_FLAG, MWST_FREI_FLAG, PROVIS_BERECHNET) VALUES (\"".$maindata['REC_ID']."\", \"".$maindata['QUELLE']."\", \"0\", \"-1\", \"".$maindata['ADDR_ID']."\", \"".$maindata['VRENUM']."\", \"".$maindata['RDATUM']."\", \"".$maindata['PR_EBENE']."\", \"".$maindata['LIEFART']."\", \"".$maindata['ZAHLART']."\", \"".$maindata['GEWICHT']."\", \"".$maindata['KOST_NETTO']."\", \"".$maindata['WERT_NETTO']."\", \"".$maindata['LOHN']."\", \"".$maindata['WARE']."\", \"".$maindata['TKOST']."\", \"".$maindata['ROHGEWINN']."\", \"".$maindata['MWST_0']."\", \"".$maindata['MWST_1']."\", \"".$maindata['MWST_2']."\", \"".$maindata['MWST_3']."\", \"".$maindata['NSUMME_0']."\", \"".$maindata['NSUMME_1']."\", \"".$maindata['NSUMME_2']."\", \"".$maindata['NSUMME_3']."\", \"".$maindata['NSUMME']."\", \"".$maindata['MSUMME_0']."\", \"".$maindata['MSUMME_1']."\", \"".$maindata['MSUMME_2']."\", \"".$maindata['MSUMME_3']."\", \"".$maindata['MSUMME']."\", \"".$maindata['BSUMME_0']."\", \"".$maindata['BSUMME_1']."\", \"".$maindata['BSUMME_2']."\", \"".$maindata['BSUMME_3']."\", \"".$maindata['BSUMME']."\", \"".$maindata['ATSUMME']."\", \"".$maindata['ATMSUMME']."\", \"".$maindata['PROVIS_WERT']."\", \"".$maindata['WAEHRUNG']."\", \"".$maindata['KURS']."\", \"".$maindata['GEGENKONTO']."\", \"".$maindata['STADIUM']."\", CURDATE(), \"".$usr_name."\", \"".$maindata['KUN_NUM']."\", \"".$maindata['KUN_ANREDE']."\", \"".$maindata['KUN_NAME1']."\", \"".$maindata['KUN_NAME2']."\", \"".$maindata['KUN_NAME3']."\", \"".$maindata['KUN_ABTEILUNG']."\", \"".$maindata['KUN_STRASSE']."\", \"".$maindata['KUN_LAND']."\", \"".$maindata['KUN_PLZ']."\", \"".$maindata['KUN_ORT']."\", \"".$maindata['PROJEKT']."\", \"".$maindata['INFO']."\", \"".$maindata['BRUTTO_FLAG']."\", \"".$maindata['MWST_FREI_FLAG']."\", \"".$maindata['PROVIS_BERECHNET']."\")", $db_id))
          {
            $b_id = mysql_insert_id($db_id);

            // Datensätze in Journalpos erstellen
            foreach($posdata as $pos)
              {
                mysql_query("INSERT INTO JOURNALPOS (QUELLE, QUELLE_SUB, QUELLE_SRC, JOURNAL_ID, ARTIKELTYP, ARTIKEL_ID, TOP_POS_ID, ADDR_ID, ATRNUM, VRENUM, VLSNUM, POSITION, VIEW_POS, MATCHCODE, ARTNUM, BARCODE, MENGE, LAENGE, BREITE, HOEHE, GROESSE, DIMENSION, GEWICHT, ME_EINHEIT, PR_EINHEIT, VPE, EK_PREIS, CALC_FAKTOR, EPREIS, GPREIS, E_RGEWINN, G_RGEWINN, RABATT, RABATT2, RABATT3, E_RABATT_BETRAG, G_RABATT_BETRAG, STEUER_CODE, ALTTEIL_PROZ, ALTTEIL_STCODE, PROVIS_PROZ, PROVIS_WERT, GEBUCHT, GEGENKTO, BEZEICHNUNG, SN_FLAG, ALTTEIL_FLAG, BEZ_FEST_FLAG, BRUTTO_FLAG, NO_RABATT_FLAG) VALUES (\"".$maindata['QUELLE']."\", \"0\", \"-1\", \"".$maindata['REC_ID']."\", \"".$pos['ARTIKELTYP']."\", \"".$pos['ARTIKEL_ID']."\", \"".$pos['TOP_POS_ID']."\", \"".$pos['ADDR_ID']."\", \"".$pos['ATRNUM']."\", \"".$maindata['VRENUM']."\", \"".$pos['VLSNUM']."\", \"".$pos['POSITION']."\", \"".$pos['VIEW_POS']."\", \"".addslashes($pos['MATCHCODE'])."\", \"".$pos['ARTNUM']."\", \"".$pos['BARCODE']."\", \"".$pos['MENGE']."\", \"".$pos['LAENGE']."\", \"".$pos['BREITE']."\", \"".$pos['HOEHE']."\", \"".$pos['GROESSE']."\", \"".$pos['DIMENSION']."\", \"".$pos['GEWICHT']."\", \"".$pos['ME_EINHEIT']."\", \"".$pos['PR_EINHEIT']."\", \"".$pos['VPE']."\", \"".$pos['EK_PREIS']."\", \"".$pos['CALC_FAKTOR']."\", \"".$pos['EPREIS']."\", \"".$pos['GPREIS']."\", \"".$pos['E_RGEWINN']."\", \"".$pos['G_RGEWINN']."\", \"".$pos['RABATT']."\", \"".$pos['RABATT2']."\", \"".$pos['RABATT3']."\", \"".$pos['E_RABATT_BETRAG']."\", \"".$pos['G_RABATT_BETRAG']."\", \"".$pos['STEUER_CODE']."\", \"".$pos['ALTTEIL_PROZ']."\", \"".$pos['ALTTEIL_STCODE']."\", \"".$pos['PROVIS_PROZ']."\", \"".$pos['PROVIS_WERT']."\", \"N\", \"".$pos['GEGENKTO']."\", \"".addslashes($pos['BEZEICHNUNG'])."\", \"".$pos['SN_FLAG']."\", \"".$pos['ALTTEIL_FLAG']."\", \"".$pos['BEZ_FEST_FLAG']."\", \"".$pos['BRUTTO_FLAG']."\", \"".$pos['NO_RABATT_FLAG']."\")", $db_id);
                $poscnt++;
              }

            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         Es wurde ".$b_type." mit ".$poscnt." Positionen erstellt.<br><br>
                        <br>
                         <button name=\"back\" type=\"button\" value=\"Bearbeiten\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=".$b_link."&action=pos&id=".$b_id."'\">Bearbeiten</button>&nbsp;&nbsp;&nbsp;&nbsp;<button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
          }
        else
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                        <tr><td align=\"center\" bgcolor=\"#d4d0c8\" valign=\"middle\">
                        <br><br><br><br>
                         <b>Fehler:</b> ".mysql_error()."<br><br>
                        <br>
                         <button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>
                        <br><br><br><br>
                        </td></tr>
                        </table>";
          }
      }
    else
      {
        if(!$_GET['month'])
          {
            // Header: main.php?section=".$_GET['section']."&module=rejourn

            $month = date("n");
            $year = date("Y");
          }
        else
          {
            // Header: main.php?section=".$_GET['section']."&module=rejourn&month=xx&year=xxxx

            $month = $_GET['month'];
            $year = $_GET['year'];
          }

	if($ini_navstyle == "classic")
	  {
            switch($month)
              {
                case 1: $last_month = 12; $last_year = $year-1; $next_month = 2; $next_year = $year; $m_name = "Januar"; break;
                case 2: $last_month = 1; $last_year = $year; $next_month = 3; $next_year = $year; $m_name = "Februar"; break;
                case 3: $last_month = 2; $last_year = $year; $next_month = 4; $next_year = $year; $m_name = "M&auml;rz"; break;
                case 4: $last_month = 3; $last_year = $year; $next_month = 5; $next_year = $year; $m_name = "April"; break;
                case 5: $last_month = 4; $last_year = $year; $next_month = 6; $next_year = $year; $m_name = "Mai"; break;
                case 6: $last_month = 5; $last_year = $year; $next_month = 7; $next_year = $year; $m_name = "Juni"; break;
                case 7: $last_month = 6; $last_year = $year; $next_month = 8; $next_year = $year; $m_name = "Juli"; break;
                case 8: $last_month = 7; $last_year = $year; $next_month = 9; $next_year = $year; $m_name = "August"; break;
                case 9: $last_month = 8; $last_year = $year; $next_month = 10; $next_year = $year; $m_name = "September"; break;
                case 10: $last_month = 9; $last_year = $year; $next_month = 11; $next_year = $year; $m_name = "Oktober"; break;
                case 11: $last_month = 10; $last_year = $year; $next_month = 12; $next_year = $year; $m_name = "November"; break;
                case 12: $last_month = 11; $last_year = $year; $next_month = 1; $next_year = $year+1; $m_name = "Dezember"; break;
              }
           $o_navi = "<table width=\"300\" cellpadding=\"0\" cellspacing=\"0\"><tr><td class=\"head\" align=\"right\" valign=\"middle\">".$m_name."&nbsp;".$year."</td><td align=\"right\" valign=\"middle\"><table width=\"16\" height=\"16\" cellpadding=\"0\" cellspacing=\"2\"><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=list&month=".$next_month."&year=".$next_year."\"><img src=\"images/p_up.gif\" border=\"0\"></a></td></tr><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=list&month=".$last_month."&year=".$last_year."\"><img src=\"images/p_down.gif\" border=\"0\"></a></td></tr></table></td></tr></table>";
	  }
	else
	  {
            $o_navi = "<table width=\"150\" cellpadding=\"0\" cellspacing=\"0\"><form action=\"main.php\" method=\"GET\" enctype=\"text/plain\"><tr><td align=\"right\"><input type=\"hidden\" name=\"section\" value=\"".$_GET['section']."\"><input type=\"hidden\" name=\"module\" value=\"".$_GET['module']."\"><select name=\"month\" size=\"1\" class=\"snav\">";
              if($month==1) $o_navi .= "<option value=\"1\" selected>Januar</option>"; else $o_navi .= "<option value=\"1\">Januar</option>";
              if($month==2) $o_navi .= "<option value=\"2\" selected>Februar</option>"; else $o_navi .= "<option value=\"2\">Februar</option>";
              if($month==3) $o_navi .= "<option value=\"3\" selected>M&auml;rz</option>"; else $o_navi .= "<option value=\"3\">M&auml;rz</option>";
              if($month==4) $o_navi .= "<option value=\"4\" selected>April</option>"; else $o_navi .= "<option value=\"4\">April</option>";
              if($month==5) $o_navi .= "<option value=\"5\" selected>Mai</option>"; else $o_navi .= "<option value=\"5\">Mai</option>";
              if($month==6) $o_navi .= "<option value=\"6\" selected>Juni</option>"; else $o_navi .= "<option value=\"6\">Juni</option>";
              if($month==7) $o_navi .= "<option value=\"7\" selected>Juli</option>"; else $o_navi .= "<option value=\"7\">Juli</option>";
              if($month==8) $o_navi .= "<option value=\"8\" selected>August</option>"; else $o_navi .= "<option value=\"8\">August</option>";
              if($month==9) $o_navi .= "<option value=\"9\" selected>September</option>"; else $o_navi .= "<option value=\"9\">September</option>";
              if($month==10) $o_navi .= "<option value=\"10\" selected>Oktober</option>"; else $o_navi .= "<option value=\"10\">Oktober</option>";
              if($month==11) $o_navi .= "<option value=\"11\" selected>November</option>"; else $o_navi .= "<option value=\"11\">November</option>";
              if($month==12) $o_navi .= "<option value=\"12\" selected>Dezember</option>"; else $o_navi .= "<option value=\"12\">Dezember</option>";
            $o_navi .= "</select></td><td align=\"right\"><select name=\"year\" size=\"1\" class=\"snav\">";
            $o_navi .= "<option>".($year-2)."</option>";
            $o_navi .= "<option>".($year-1)."</option>";
            $o_navi .= "<option selected>".$year."</option>";
            $o_navi .= "<option>".($year+1)."</option>";
            $o_navi .= "<option>".($year+2)."</option>";
            $o_navi .= "</select></td><td align=\"right\"><input type=\"submit\" value=\" OK \" class=\"bnav\"></td></tr></form></table>";
	  }

        if($_GET['otype'] == "desc")			// Sortierung der Positionen: Aufsteigend / Absteigend
          {
            $sql_otype = "DESC";
            $otype = "asc";
          }
        else
          {
            $sql_otype = "ASC";
            $otype = "desc";
          }

        if($_GET['oname'] == "datum")			// Merkmal, nach dem die Belegliste sortiert werden soll.
          {
            $sql_oname = "RDATUM";
          }
        elseif($_GET['oname'] == "name")
          {
            $sql_oname = "KUN_NAME1";
          }
        elseif($_GET['oname'] == "netto")
          {
            $sql_oname = "NSUMME";
          }
        elseif($_GET['oname'] == "brutto")
          {
            $sql_oname = "BSUMME";
          }
        else
          {
            $sql_oname = "VRENUM";
          }

        $res_id = mysql_query("SELECT REC_ID, VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, NSUMME, MSUMME, BSUMME, WAEHRUNG FROM JOURNAL WHERE QUELLE=3 AND QUELLE_SUB=1 AND MONTH(RDATUM)=".$month." AND YEAR(RDATUM)=".$year." ORDER BY ".$sql_oname." ".$sql_otype, $db_id);
        $res_num = mysql_numrows($res_id);
        $result = array();

        for($i=0; $i<$res_num; $i++)
          {
            array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
          }

        mysql_free_result($res_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=rechnung&otype=".$otype."\">Beleg</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=datum&otype=".$otype."\">Datum</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=name&otype=".$otype."\">Name des Kunden</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=netto&otype=".$otype."\">Netto</a></td><td>&nbsp;MwSt</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=brutto>&otype=".$otype."\">Brutto</a></td><td colspan=\"2\">&nbsp;Belegkopie</td><td>&nbsp;Belegdruck</td></tr>";
        foreach($result as $row)
          {
            $color++;
            $a_anzahl += $row['Bestand'];
            $a_wert += $row['Gesamtwert'];
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['VRENUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['RDATUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['KUN_NAME1']." ".$row['KUN_NAME2']."</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['NSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['MSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['BSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=create&type=angebot&id=".$row['REC_ID']."\">&nbsp;Angebot</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=create&type=rechnung&id=".$row['REC_ID']."\">&nbsp;Rechnung</a></td><td align=\"center\"><a href=\"report.php?module=rechnung&id=".$row['REC_ID']."\" target=\"_blank\">&nbsp;Formular</a></td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['VRENUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['RDATUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".$row['KUN_NAME1']." ".$row['KUN_NAME2']."</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['NSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['MSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=detail&id=".$row['REC_ID']."\">&nbsp;".number_format($row['BSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=create&type=angebot&id=".$row['REC_ID']."\">&nbsp;Angebot</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rejourn&action=create&type=rechnung&id=".$row['REC_ID']."\">&nbsp;Rechnung</a></td><td align=\"center\"><a href=\"report.php?module=rechnung&id=".$row['REC_ID']."\" target=\"_blank\">&nbsp;Formular</a></td></tr>";
              }

          }

        $o_cont .= "</table>";

      }
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>