<?php

$o_head = "RMA";
$o_navi = "";
$now = time();


if (!function_exists("str_split"))			// Abwärtskompatibilität zu PHP4
  {
    function str_split($str, $nr)
      {
         return array_slice(split("-l-", chunk_split($str, $nr, '-l-')), 0, -1);
      }
  }

function get_status($status_code)
  {
    switch($status_code)
      {
        case -1: $result = "Ersatzteile bearbeitet"; break;
        case 0: $result = "Kommentar"; break;
        case 1: $result = "Warte auf defekte Ware"; break;
        case 2: $result = "Defekte Ware eingetroffen"; break;
        case 3: $result = "Defekte Ware eingeschickt"; break;
        case 4: $result = "Ausgetauschte Ware eingetroffen"; break;
        case 5: $result = "Gutschrift eingetroffen"; break;
        case 6: $result = "Austausch abgelehnt"; break;
        case 7: $result = "Kein Fehler feststellbar"; break;
        case 8: $result = "Reparierte Ware eingetroffen"; break;
        case 9: $result = "Ware selbst repariert"; break;
      }
    return $result;
  }

function get_icon($status_code, $last_change, $now)
  {
    $lc_data = explode("-", $last_change);
    $lc_time = mktime(0, 0, 0, $lc_data[1], $lc_data[2], $lc_data[0]);

    if(($status_code == 1) && (($lc_time+1209600)>=$now)) $data[ICON]="p_bl.gif";
    elseif(($status_code == 1) && (($lc_time+1209600)<$now)) $data[ICON]="p_li.gif";
    elseif(($status_code == 2) && (($lc_time+259200)>=$now)) $data[ICON]="p_bl.gif";
    elseif(($status_code == 2) && (($lc_time+259200)<$now)) $data[ICON]="p_re.gif";
    elseif(($status_code == 3) && (($lc_time+1814400)>=$now)) $data[ICON]="p_ye.gif";
    elseif(($status_code == 3) && (($lc_time+1814400)<$now) && (($lc_time+3628800)>=$now)) $data[ICON]="p_or.gif";
    elseif(($status_code == 3) && (($lc_time+3628800)<$now)) $data[ICON]="p_re.gif";
    elseif($status_code == 4) $data[ICON]="p_gr.gif";
    elseif($status_code == 5) $data[ICON]="p_gr.gif";
    elseif($status_code == 6) $data[ICON]="p_gr.gif";
    elseif($status_code == 7) $data[ICON]="p_gr.gif";
    elseif($status_code == 8) $data[ICON]="p_gr.gif";
    elseif($status_code == 9) $data[ICON]="p_gr.gif";

    return $data[ICON];
  }

function get_mwst($db_id)
  {
    $res_id = mysql_query("SELECT * FROM REGISTRY WHERE MAINKEY='MAIN\\\\MWST' ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function set_journal($journal_id, $db_id)			// aktualisiert den Journaleintrag mit den aktuellen Werten der Positionen.
  {
    $res_id = mysql_query("SELECT ARTIKELTYP, STEUER_CODE, MENGE, EPREIS, G_RGEWINN, RABATT FROM JOURNALPOS WHERE JOURNAL_ID=".$journal_id, $db_id);
    $res_num = mysql_numrows($res_id);
    $posdata = array();
    for($i=0; $i<$res_num; $i++)
     {
       array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
     }
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT BRUTTO_FLAG FROM JOURNAL WHERE REC_ID=".$journal_id, $db_id);
    $flag = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $mwst = get_mwst($db_id);

    $maindata['LOHN'] = 0.00;
    $maindata['WARE'] = 0.00;
    $maindata['TKOST'] = 0.00;
    $maindata['ROHGEWINN'] = 0.00;
    $maindata['NSUMME_0'] = 0.00;
    $maindata['NSUMME_1'] = 0.00;
    $maindata['NSUMME_2'] = 0.00;
    $maindata['NSUMME_3'] = 0.00;
    $maindata['NSUMME'] = 0.00;
    $maindata['MSUMME_0'] = 0.00;
    $maindata['MSUMME_1'] = 0.00;
    $maindata['MSUMME_2'] = 0.00;
    $maindata['MSUMME_3'] = 0.00;
    $maindata['MSUMME'] = 0.00;
    $maindata['BSUMME_0'] = 0.00;
    $maindata['BSUMME_1'] = 0.00;
    $maindata['BSUMME_2'] = 0.00;
    $maindata['BSUMME_3'] = 0.00;
    $maindata['BSUMME'] = 0.00;

    foreach($posdata as $row)
      {
        foreach($mwst as $rtemp)							// Mehrwertsteuersatz
          {
            if($rtemp['NAME']==$row['STEUER_CODE'])
              {
                $mwst_set = ($rtemp['VAL_DOUBLE'] + 100) / 100;
              }
          }

        if($flag['BRUTTO_FLAG']=="Y")							// Brutto-Einzelpreis, umrechnen:
          {
            $maindata['NSUMME'] = $maindata['NSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) / $mwst_set * $row['MENGE']);
            $maindata['BSUMME'] = $maindata['BSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']);
            $maindata['MSUMME'] = $maindata['BSUMME'] - $maindata['NSUMME'];

            $maindata['NSUMME_'.$row['STEUER_CODE']] = $maindata['NSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) / $mwst_set * $row['MENGE']);
            $maindata['BSUMME_'.$row['STEUER_CODE']] = $maindata['BSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']);
            $maindata['MSUMME_'.$row['STEUER_CODE']] = $maindata['BSUMME_'.$row['STEUER_CODE']] - $maindata['NSUMME_'.$row['STEUER_CODE']];

            if($row['ARTIKELTYP']=="N")
              {
                $maindata['WARE'] = $maindata['WARE'] + ($row['EPREIS'] / $mwst_set);
              }
            elseif($row['ARTIKELTYP']=="L")
              {
                $maindata['LOHN'] = $maindata['LOHN'] + ($row['EPREIS'] / $mwst_set);
              }
            elseif($row['ARTIKELTYP']=="K")
              {
                $maindata['TKOST'] = $maindata['TKOST'] + ($row['EPREIS'] / $mwst_set);
              }
          }
        else										// Netto-Einzelpreis:
          {
            $maindata['NSUMME'] = $maindata['NSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']);
            $maindata['BSUMME'] = $maindata['BSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $mwst_set * $row['MENGE']);
            $maindata['MSUMME'] = $maindata['BSUMME'] - $maindata['NSUMME'];

            $maindata['NSUMME_'.$row['STEUER_CODE']] = $maindata['NSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']);
            $maindata['BSUMME_'.$row['STEUER_CODE']] = $maindata['BSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $mwst_set * $row['MENGE']);
            $maindata['MSUMME_'.$row['STEUER_CODE']] = $maindata['BSUMME_'.$row['STEUER_CODE']] - $maindata['NSUMME_'.$row['STEUER_CODE']];

            if($row['ARTIKELTYP']=="N")
              {
                $maindata['WARE'] = $maindata['WARE'] + ($row['EPREIS'] * $row['MENGE']);
              }
            elseif($row['ARTIKELTYP']=="L")
              {
                $maindata['LOHN'] = $maindata['LOHN'] + ($row['EPREIS'] * $row['MENGE']);
              }
            elseif($row['ARTIKELTYP']=="K")
              {
                $maindata['TKOST'] = $maindata['TKOST'] + ($row['EPREIS'] * $row['MENGE']);
              }
          }
        $maindata['ROHGEWINN'] = $maindata['ROHGEWINN'] + $row['G_RGEWINN'];
      }

    // Alle Daten aktualisiert, senden an Datenbank

    $query = "UPDATE JOURNAL SET
                LOHN='".$maindata['LOHN']."',
                WARE='".$maindata['WARE']."',
                TKOST='".$maindata['TKOST']."',
                ROHGEWINN='".$maindata['ROHGEWINN']."',
                NSUMME_0='".$maindata['NSUMME_0']."',
                NSUMME_1='".$maindata['NSUMME_1']."',
                NSUMME_2='".$maindata['NSUMME_2']."',
                NSUMME_3='".$maindata['NSUMME_3']."',
                NSUMME='".$maindata['NSUMME']."',
                MSUMME_0='".$maindata['MSUMME_0']."',
                MSUMME_1='".$maindata['MSUMME_1']."',
                MSUMME_2='".$maindata['MSUMME_2']."',
                MSUMME_3='".$maindata['MSUMME_3']."',
                MSUMME='".$maindata['MSUMME']."',
                BSUMME_0='".$maindata['BSUMME_0']."',
                BSUMME_1='".$maindata['BSUMME_1']."',
                BSUMME_2='".$maindata['BSUMME_2']."',
                BSUMME_3='".$maindata['BSUMME_3']."',
                BSUMME='".$maindata['BSUMME']."',
                RDATUM=CURDATE()
                WHERE REC_ID=".$journal_id;

    //echo $query."<br><br>";

    if(!mysql_query($query, $db_id))
      {
        echo mysql_error($db_id)."<br>";
      }
  }


function set_snr_status($db_id, $id, $db_pref)
  {
    $res_id = mysql_query("SELECT ART_ID, ART_SNR, EIGEN_RMA FROM ".$db_pref."RMA WHERE ID=".$id, $db_id);
    $d_rma = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT SNUM_ID FROM ARTIKEL_SERNUM WHERE ARTIKEL_ID='".$d_rma['ART_ID']."' AND SERNUMMER='".$d_rma['ART_SNR']."'", $db_id);
    $d_snr = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    if($d_snr['SNUM_ID']) // Seriennummer gefunden -> aktuellen RMA-Status suchen und SNR-Status setzen:
      {
        $res_id = mysql_query("SELECT STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$id." AND STATUS NOT IN (0,1) ORDER BY ID DESC LIMIT 1", $db_id);
        $d_sta = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        if(!$d_rma['EIGEN_RMA'])  // Kunden-RMA
          {
            switch($d_sta['STATUS'])
              {
                case 2: $status = "RMA_IH"; break;
                case 3: $status = "RMA_AH"; break;
                case 4: $status = "RMA_AT"; break;
                case 5: $status = "RMA_AT"; break;
                case 6: $status = "VK_RECH"; break;
                case 7: $status = "VK_RECH"; break;
                case 8: $status = "VK_RECH"; break;
                case 9: $status = "VK_RECH"; break;
              }
            mysql_query("UPDATE ARTIKEL_SERNUM SET STATUS='".$status."' WHERE SNUM_ID=".$d_snr['SNUM_ID'],$db_id);
            return 1;
          }
        elseif($d_rma['EIGEN_RMA']==1)  // Eigen-RMA
          {
            switch($d_sta['STATUS'])
              {
                case 2: $status = "RMA_IH"; break;
                case 3: $status = "RMA_AH"; break;
                case 4: $status = "RMA_AT"; break;
                case 5: $status = "RMA_AT"; break;
                case 6: $status = "LAGER"; break;
                case 7: $status = "LAGER"; break;
                case 8: $status = "LAGER"; break;
                case 9: $status = "LAGER"; break;
              }
            mysql_query("UPDATE ARTIKEL_SERNUM SET STATUS='".$status."' WHERE SNUM_ID=".$d_snr['SNUM_ID'],$db_id);
            return 1;
          }
        else  // Fremd-RMA, Seriennummer kann per Definition nicht in CAO sein, aber vorsichtshalber...
          {
            return 1;
          }
      }
    else
      {
        return 0;
      }
  }

function get_data($db_id, $id, $db_pref)
  {
    $res_id = mysql_query("SELECT * FROM ".$db_pref."RMA WHERE ID=".$id, $db_id);
    $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $temp_id1 = mysql_query("SELECT DATUM FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[ID]." AND STATUS>0 ORDER BY ID ASC LIMIT 1", $db_id);
    $temp_id2 = mysql_query("SELECT DATUM, STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[ID]." AND STATUS>0 ORDER BY ID DESC LIMIT 1", $db_id);

    $temp1 = mysql_fetch_array($temp_id1, MYSQL_ASSOC);
    $temp2 = mysql_fetch_array($temp_id2, MYSQL_ASSOC);

    $data[FEHLER] = str_replace("\r\n", "<br>", $data[FEHLER]);
    $data[FEHLER] = str_replace("\r", "<br>", $data[FEHLER]);
    $data[FEHLER] = str_replace("\n", "<br>", $data[FEHLER]);
    $data[FEHLER] = stripslashes($data[FEHLER]);
    $data[KOMMENTAR] = stripslashes($data[KOMMENTAR]);
    $data[CREATED] = $temp1[DATUM];
    $data[LAST_CHANGE] = $temp2[DATUM];
    $data[STATUS] = $temp2[STATUS];

    mysql_free_result($temp_id1);
    mysql_free_result($temp_id2);

    $ts_data = explode("-", $data[CREATED]);
    $data[CREATED_TS] = mktime(0, 0, 0, $ts_data[1], $ts_data[2], $ts_data[0]);

    if($data[EIGEN_RMA]==1)
      {
        $data[KUN_NR] = " - ";
        $data[KUN_RNR] = " - ";
        $data[KUN_NAME] = " - ";
        $data[KUN_RDAT] = " - ";
        $data[RMA_VALID] = 1;
      }
    elseif($data[EIGEN_RMA]==0)
      {
        $temp_id = mysql_query("SELECT NAME1, NAME2, KUNNUM1 FROM ADRESSEN WHERE REC_ID=".$data[KUN_ID], $db_id);
        $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
        $data[KUN_NR] = $temp[KUNNUM1];
        $data[KUN_NAME] = $temp[NAME1]." ".$temp[NAME2];
        mysql_free_result($temp_id);

        $temp_id = mysql_query("SELECT VRENUM, RDATUM FROM JOURNAL WHERE REC_ID=".$data[KUN_RID], $db_id);
        $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
        $data[KUN_RNR] = $temp[VRENUM];
        $data[KUN_RDAT] = $temp[RDATUM];
        $ts_data = explode("-", $data[KUN_RDAT]);
        $data[KUN_RDAT_TS] = mktime(0, 0, 0, $ts_data[1], $ts_data[2], $ts_data[0]);
        if($data[CREATED_TS] > ($data[KUN_RDAT_TS]+63072000)) $data[RMA_VALID] = 0; else $data[RMA_VALID] = 1; // Noch Gewährleistung für Kunden?
        mysql_free_result($temp_id);
      }
    else
      {
        $temp_id = mysql_query("SELECT NAME1, NAME2, KUNNUM1 FROM ADRESSEN WHERE REC_ID=".$data[KUN_ID], $db_id);
        $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
        $data[KUN_NR] = $temp[KUNNUM1];
        $data[KUN_NAME] = $temp[NAME1]." ".$temp[NAME2];
        mysql_free_result($temp_id);

        $data[KUN_RDAT] = " - ";
        $data[KUN_RNR] = " - ";
        $data[RMA_VALID] = 1;
      }

    $temp_id = mysql_query("SELECT ARTNUM, KURZNAME FROM ARTIKEL WHERE REC_ID=".$data[ART_ID], $db_id);
    $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
    $data[ARTNUM] = $temp[ARTNUM];
    $data[ART_NAME] = $temp[KURZNAME];
    mysql_free_result($temp_id);

    $temp_id = mysql_query("SELECT NAME1, NAME2, KUNNUM2 FROM ADRESSEN WHERE REC_ID=".$data[LIEF_ID], $db_id);
    $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
    $data[LIEF_NR] = $temp[KUNNUM2];
    $data[LIEF_NAME] = $temp[NAME1]." ".$temp[NAME2];
    mysql_free_result($temp_id);

    if($data[EIGEN_RMA]==2)
      {
        $data[LIEF_RNR] = " - ";
      }
    else
      {
        $temp_id = mysql_query("SELECT ORGNUM FROM JOURNAL WHERE REC_ID=".$data[LIEF_RID], $db_id);
        $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
        $data[LIEF_RNR] = $temp[ORGNUM];
        mysql_free_result($temp_id);
      }

    if(!$data[LIEF_RMA])
      {
        $data[LIEF_RMA] = " - ";
      }
    if(!$data[ART_SNR])
      {
        $data[ART_SNR] = " - ";
      }

    return $data;
  }

function print_sn_field($db_id, $journalpos_id, $serial, $db_pref)
  {
    if($serial && (!$journalpos_id))
      {
        $result = "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><input type=\"text\" name=\"SERIAL\" size=\"30\" value=\"".$serial."\"></td></tr>";
      }
    elseif($journalpos_id)
      {
        $res_id = mysql_query("SELECT SNUM_ID FROM JOURNALPOS_SERNUM WHERE JOURNALPOS_ID=".$journalpos_id, $db_id);
        $data = array();
        $number = mysql_num_rows($res_id);

        for($i=0; $i<$number; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);

        $result = "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><select name=\"SERIAL\" size=\"1\">";

        for($i=0; $i<$number; $i++)
          {
            $res_id = mysql_query("SELECT SERNUMMER FROM ARTIKEL_SERNUM WHERE SNUM_ID=".$data[$i]['SNUM_ID'], $db_id);
            $temp = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $result .= "<option>".$temp['SERNUMMER']."</option>";
          }

        $result .= "</select></td></tr>";
      }
    else
      {
        $result = "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><input type=\"text\" name=\"SERIAL\" size=\"30\"></td></tr>";
      }

    return $result;
  }

function print_head($data, $section)
  {
    $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferant</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Artikel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr. bei Lief.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_NR]."</td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Lieferant:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_NAME]."</td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">ER-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;<a href=\"main.php?section=".$section."&module=wejourn&action=detail&id=".$data[LIEF_RID]."\">".$data[LIEF_RNR]."</a></td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_RMA]."</td></tr></table></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "<br><br>";
    $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"3\">";
    $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[RMANUM]."</td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ARTNUM]."</td></tr></table></td><td></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ART_NAME]."</td></tr></table></td><td></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ANZAHL]."</td></tr></table></td><td></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ART_SNR]."</td></tr></table></td><td></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"top\" width=\"100\">Fehlerbeschr.:</td><td><table width=\"80%\" height=\"100\" cellpadding=\"2\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" valign=\"top\">".$data[FEHLER]."</td></tr></table></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Kunde</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_NR]."</td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunde:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_NAME]."</td></tr></table></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_RNR]."</td></tr></table></td></tr>";

    if($data[RMA_VALID])
      {
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_RDAT]."</td></tr></table></td></tr>";
      }
    else
      {
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#ff0000\">&nbsp;".$data[KUN_RDAT]."</td></tr></table></td></tr>";
      }
    $o_cont .= "</table><br><br>";
    $o_cont .= "</td></tr>";

    return $o_cont;
  }

function print_navi($id, $section)
  {
    $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rma&action=detail&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Allgemein&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rma&action=events&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Vorg&auml;nge&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rma&action=report&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Bericht&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rma&action=finalise&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Fertigstellen&nbsp;</a></td>
               </tr></table>";

    return $o_navi;
  }

// HAUPTPROGRAMM

if($usr_rights)
  {
    if((!$_GET['action']) || ($_GET['action']=="list"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=list


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
            $sql_oname = "ERSTDAT";
          }
        elseif($_GET['oname'] == "lieferant")
          {
            $sql_oname = "LIEF_ID";
          }
        elseif($_GET['oname'] == "rmanum")
          {
            $sql_oname = "LIEF_RMA";
          }
        elseif($_GET['oname'] == "kunde")
          {
            $sql_oname = "KUN_ID";
          }
        elseif($_GET['oname'] == "bearbeiter")
          {
            $sql_oname = "ERSTELLT";
          }
        else
          {
            $sql_oname = "ID";
          }

        if($res_id = mysql_query("SELECT * FROM ".$db_pref."RMA WHERE FINAL IS NULL ORDER BY ".$sql_oname." ".$sql_otype, $db_id))
          {
            $number = mysql_num_rows($res_id);
          }
        else
          {
            $number = 0;
          }

        $data = array();
        $number = mysql_num_rows($res_id);
        for($i=0; $i<$number; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));

            $temp_id1 = mysql_query("SELECT DATUM FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[$i][ID]." AND STATUS>0 ORDER BY ID ASC LIMIT 1", $db_id);
            $temp_id2 = mysql_query("SELECT DATUM, STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[$i][ID]." AND STATUS>0 ORDER BY ID DESC LIMIT 1", $db_id);
            $temp_id4 = mysql_query("SELECT NAME1, NAME2 FROM ADRESSEN WHERE REC_ID=".$data[$i][LIEF_ID], $db_id);
            $temp_id5 = mysql_query("SELECT KURZNAME FROM ARTIKEL WHERE REC_ID=".$data[$i][ART_ID], $db_id);

            $temp1 = mysql_fetch_array($temp_id1, MYSQL_ASSOC);
            $temp2 = mysql_fetch_array($temp_id2, MYSQL_ASSOC);
            $temp4 = mysql_fetch_array($temp_id4, MYSQL_ASSOC);
            $temp5 = mysql_fetch_array($temp_id5, MYSQL_ASSOC);

            $data[$i][CREATED] = $temp1[DATUM];
            $data[$i][LAST_CHANGE] = $temp2[DATUM];
            $data[$i][STATUS] = $temp2[STATUS];
            $data[$i][LIEF_NAME] = $temp4[NAME1]." ".$temp4[NAME2];
            $data[$i][KURZNAME] = $temp5[KURZNAME];

            mysql_free_result($temp_id1);
            mysql_free_result($temp_id2);
            mysql_free_result($temp_id4);
            mysql_free_result($temp_id5);

            if($data[$i][EIGEN_RMA]!=1)
              {
                $temp_id3 = mysql_query("SELECT NAME1 FROM ADRESSEN WHERE REC_ID=".$data[$i][KUN_ID], $db_id);
                $temp3 = mysql_fetch_array($temp_id3, MYSQL_ASSOC);
                $data[$i][KUN_NAME] = $temp3[NAME1];
                mysql_free_result($temp_id3);
              }
            else
              {
                $data[$i][KUN_NAME] = "-";
              }

            if(!$data[$i][LIEF_RMA])
              {
                $data[$i][LIEF_RMA] = "-";
              }
          }
        mysql_free_result($res_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=id&otype=".$otype."\">RMA-Nummer</a></td><td>&nbsp;Artikel</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=kunde&otype=".$otype."\">Kunde</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=lieferant&otype=".$otype."\">Lieferant</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=rmanum&otype=".$otype."\">Lief.-RMA</a></td><td>&nbsp;Status</td><td>&nbsp;le.&Auml;nderung</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=datum&otype=".$otype."\">erstellt am</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&month=".$_GET['month']."&year=".$_GET['year']."&oname=bearbeiter&otype=".$otype."\">erstellt von</a></td></tr>";
        foreach($data as $row)
          {
            $data[STATUS_TEXT] = get_status($row[STATUS]);
            $data[ICON] = get_icon($row[STATUS], $row[LAST_CHANGE], $now);

            if(strlen($row[KURZNAME])>30)
              {
                $tmp = str_split($row[KURZNAME], 30);
                $row[KURZNAME] = $tmp[0]."...";
              }

            if(strlen($row[KUN_NAME])>20)
              {
                $tmp = str_split($row[KUN_NAME], 20);
                $row[KUN_NAME] = $tmp[0]."...";
              }

            if(strlen($row[LIEF_NAME])>20)
              {
                $tmp = str_split($row[LIEF_NAME], 20);
                $row[LIEF_NAME] = $tmp[0]."...";
              }

            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td width=\"16\"><img src=\"images/".$data[ICON]."\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$row[ID]."\">&nbsp;".$row[RMANUM]."</a></td><td>&nbsp;".$row[KURZNAME]."</td><td>&nbsp;".$row[KUN_NAME]."</td><td>&nbsp;".$row[LIEF_NAME]."</td><td>&nbsp;".$row[LIEF_RMA]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td align=\"right\">".$row[LAST_CHANGE]."</td><td align=\"right\">".$row[CREATED]."</td><td align=\"right\">".$row[ERSTELLT]."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td width=\"16\"><img src=\"images/".$data[ICON]."\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$row[ID]."\">&nbsp;".$row[RMANUM]."</a></td><td>&nbsp;".$row[KURZNAME]."</td><td>&nbsp;".$row[KUN_NAME]."</td><td>&nbsp;".$row[LIEF_NAME]."</td><td>&nbsp;".$row[LIEF_RMA]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td align=\"right\">".$row[LAST_CHANGE]."</td><td align=\"right\">".$row[CREATED]."</td><td align=\"right\">".$row[ERSTELLT]."</td></tr>";
              }

          }

        $o_cont .= "</table>";

        $o_navi = "<table width=\"100\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"100\" align=\"right\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=init\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Neuen Beleg&nbsp;</a></td></tr></table>";
      }
    elseif($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=detail&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $data = get_data($db_id, $_GET['id'], $db_pref);
        $data[STATUS_TEXT] = get_status($data[STATUS]);
	$data[ICON] = get_icon($data[STATUS], $data[LAST_CHANGE], $now);


        $o_cont = print_head($data, $_GET['section']);
        $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rma&action=update&id=".$data[ID]."\" method=\"post\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferadresse</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Info</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        if($data[EIGEN_RMA]==1)
          {
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Name1:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Name2:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Strasse:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">PLZ/Ort:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"2\">&nbsp;</td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">E-Mail:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Telefon:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;-</td></tr></table></td></tr>";
          }
        else
          {
            $temp_id = mysql_query("SELECT NAME1, NAME2, PLZ, ORT, STRASSE, TELE1, EMAIL FROM ADRESSEN WHERE REC_ID=".$data[KUN_ID], $db_id);
            $temp = mysql_fetch_array($temp_id, MYSQL_ASSOC);
            mysql_free_result($temp_id);

            if(!$data[RS_NAME1]) $data[RS_NAME1] = $temp[NAME1];
            if(!$data[RS_NAME2]) $data[RS_NAME2] = $temp[NAME2];
            if(!$data[RS_STRASSE]) $data[RS_STRASSE] = $temp[STRASSE];
            if(!$data[RS_PLZ]) $data[RS_PLZ] = $temp[PLZ];
            if(!$data[RS_ORT]) $data[RS_ORT] = $temp[ORT];
            if(!$data[RS_TELEFON]) $data[RS_TELEFON] = $temp[TELE1];
            if(!$data[RS_EMAIL]) $data[RS_EMAIL] = $temp[EMAIL];

            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Name1:</td><td><input type=\"text\" name=\"RS_NAME1\" size=\"30\" value=\"".$data[RS_NAME1]."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Name2:</td><td><input type=\"text\" name=\"RS_NAME2\" size=\"30\" value=\"".$data[RS_NAME2]."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Strasse:</td><td><input type=\"text\" name=\"RS_STRASSE\" size=\"30\" value=\"".$data[RS_STRASSE]."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">PLZ/Ort:</td><td><input type=\"text\" name=\"RS_PLZ\" size=\"5\" value=\"".$data[RS_PLZ]."\">&nbsp;&nbsp;<input type=\"text\" name=\"RS_ORT\" size=\"20\" value=\"".$data[RS_ORT]."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"2\">&nbsp;</td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">E-Mail:</td><td><input type=\"text\" name=\"RS_EMAIL\" size=\"30\" value=\"".$data[RS_EMAIL]."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Telefon:</td><td><input type=\"text\" name=\"RS_TELEFON\" size=\"30\" value=\"".$data[RS_TELEFON]."\"></td></tr>";
          }
        $o_cont .= "</table>";
        $o_cont .= "<br><br>";
        $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"top\" width=\"100\">Lief.-RMA &auml;ndern:</td><td><input type=\"text\" name=\"LIEF_RMA\" size=\"48\" value=\"".$data[LIEF_RMA]."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"top\" width=\"100\">Kommentar:</td><td><textarea name=\"KOMMENTAR\" cols=\"36\" rows=\"5\">".$data[KOMMENTAR]."</textarea></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Infos</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Einstellungen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Status:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#ffffdd\" width=\"20\"><img src=\"images/".$data[ICON]."\"></td><td bgcolor=\"#d4d0c8\">&nbsp;".$data[STATUS_TEXT]."</td></tr></table></td></tr></table></td>";
        $o_cont .= "<td bgcolor=\"#ffffdd\"><table width=\"500\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\"><td width=\"200\">";
        $o_cont .= "<table width=\"130\" cellpadding=\"0\" cellspacing=\"2\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" width=\"20\"><input type=\"radio\" name=\"EIGEN_RMA\" value=\"1\""; if($data[EIGEN_RMA]==1) $o_cont .= " checked>"; else $o_cont .= ">";
        $o_cont .= "</td><td bgcolor=\"#d4d0c8\">&nbsp;Eigene RMA</td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" width=\"20\"><input type=\"radio\" name=\"EIGEN_RMA\" value=\"0\""; if($data[EIGEN_RMA]==0) $o_cont .= " checked>"; else $o_cont .= ">";
        $o_cont .= "</td><td bgcolor=\"#d4d0c8\">&nbsp;Kunden-RMA</td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" width=\"20\"><input type=\"radio\" name=\"EIGEN_RMA\" value=\"2\""; if($data[EIGEN_RMA]==2) $o_cont .= " checked>"; else $o_cont .= ">";
        $o_cont .= "</td><td bgcolor=\"#d4d0c8\">&nbsp;Fremd-RMA</td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td><td><input type=\"submit\" value=\" Sichern \">&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"button\" value=\"L&ouml;schen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=rma&action=delete&id=".$data[ID]."'\"></td></tr></table></td></tr>";
        $o_cont .= "</form></table>";
      }
    elseif($_GET['action']=="report")
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=report&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $data = get_data($db_id, $_GET['id'], $db_pref);

        $o_cont = print_head($data, $_GET['section']);

        // Ausgabe weiter formatieren!

        if($data[EIGEN_RMA]==1)
          {
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" align=\"center\" colspan=\"2\"><br><br>Kein Belegdruck m&ouml;glich, da es sich um Eigen-RMA handelt!<br><br></td></tr></table>";
          }
        else
          {
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"2\"><b>&nbsp;Optionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" align=\"center\" colspan=\"2\">";
            $o_cont .= "<form action=\"report.php?module=rma&id=".$data[ID]."\" method=\"post\" target=\"_blank\">";
            $o_cont .= "<table width=\"350\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr><td align=\"left\" valign=\"top\">Kommentar ausgeben:</td><td><input type=\"checkbox\" name=\"notes\" value=\"1\" checked=\"checked\"></td></tr>";
            $o_cont .= "<tr><td align=\"left\" valign=\"top\">Anmerkungen ausgeben:</td><td><textarea name=\"info\" cols=\"20\" rows=\"5\"></textarea></td></tr>";
            $o_cont .= "<tr><td colspan=\"2\" align=\"center\"><input type=\"hidden\" name=\"user\" value=\"".$usr_name."\"><input type=\"submit\" value=\" Erstellen \"></td></tr>";
            $o_cont .= "</table></form>";
            $o_cont .= "<br><br></td></tr></table>";
          }
      }
    elseif(($_GET['action']=="delete") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=delete&id=xxxxxxx

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr>
                   <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td>
                   <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Allgemein&nbsp;</a></td>
                   <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=events&id=".$_GET['id']."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Vorg&auml;nge&nbsp;</a></td>
                   <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=finalise&id=".$_GET['id']."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Fertigstellen&nbsp;</a></td>
                   </tr></table>";

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
        $o_cont .= "<br><br><br><br><br><br><br><br>Wollen Sie den Datensatz wirklich l&ouml;schen?<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=delete&type=submit&id=".$_GET['id']."\">JA</a>&nbsp;&nbsp;&nbsp;&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">NEIN</a><br><br><br><br><br><br><br><br>";
        $o_cont .= "</td></tr></table>";
      }
    elseif(($_GET['action']=="delete") && ($_GET['type']=="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=delete&type=submit&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $res_id = mysql_query("SELECT EIGEN_RMA, ART_ID, ANZAHL FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
        $num = mysql_num_rows($res_id);

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        if($num)
          {
            $data = mysql_fetch_array($res_id, MYSQL_ASSOC);

            if($data['EIGEN_RMA']==1) // Bestände anpassen!
              {
                 $tmp_id = mysql_query("SELECT MENGE_AKT FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                 $tmp2_id = mysql_query("SELECT RMA_BEST FROM ".$db_pref."BEST WHERE ART_ID=".$data['ART_ID'], $db_id);
                 $tmp = mysql_fetch_array($tmp_id, MYSQL_ASSOC);
                 $tmp2 = mysql_fetch_array($tmp2_id, MYSQL_ASSOC);
                 mysql_free_result($tmp_id);
                 mysql_free_result($tmp2_id);
                 mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($tmp['MENGE_AKT']+$data['ANZAHL'])." WHERE REC_ID=".$data['ART_ID'], $db_id);
                 mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($tmp2['RMA_BEST']-$data['ANZAHL'])." WHERE ART_ID=".$data['ART_ID'], $db_id);
              }

            mysql_query("DELETE FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
            mysql_query("DELETE FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$_GET['id'], $db_id);

            $o_cont .= "<br><br><br><br><br><br><br><br>Datensatz erfolgreich gel&ouml;scht!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
          }
        else
          {
            $o_cont .= "<br><br><br><br><br><br><br><br>FEHLER: Datensatz nicht gefunden!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
          }

        $o_cont .= "</td></tr></table>";
        mysql_free_result($res_id);
      }
    elseif($_GET['action']=="update")
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=update&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $res_id = mysql_query("SELECT EIGEN_RMA, ART_ID, ANZAHL FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
        $num = mysql_num_rows($res_id);

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        $_POST['KOMMENTAR'] = addslashes($_POST['KOMMENTAR']);

        if($num)
          {
            $data = mysql_fetch_array($res_id, MYSQL_ASSOC);

            if($data['EIGEN_RMA']==0 && $_POST['EIGEN_RMA']==1)
              {
                 $tmp_id = mysql_query("SELECT MENGE_AKT FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                 $tmp2_id = mysql_query("SELECT RMA_BEST FROM ".$db_pref."BEST WHERE ART_ID=".$data['ART_ID'], $db_id);
                 $tmp = mysql_fetch_array($tmp_id, MYSQL_ASSOC);
                 $tmp2 = mysql_fetch_array($tmp2_id, MYSQL_ASSOC);
                 mysql_free_result($tmp_id);
                 mysql_free_result($tmp2_id);
                 mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($tmp['MENGE_AKT']-$data['ANZAHL'])." WHERE REC_ID=".$data['ART_ID'], $db_id);
                 mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($tmp2['RMA_BEST']+$data['ANZAHL'])." WHERE ART_ID=".$data['ART_ID'], $db_id);
                 mysql_query("UPDATE ".$db_pref."RMA SET EIGEN_RMA='1', KOMMENTAR='".$_POST['KOMMENTAR']."' WHERE ID=".$_GET['id'], $db_id);
                 mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$_GET['id']."', '0', 'Stammdaten geändert. In interne RMA gewandelt.', CURDATE(), '".$usr_name."')", $db_id);
                 $o_cont .= "<br><br><br><br><br><br><br><br>Datensatz erfolgreich bearbeitet, Reparaturbestand angepasst!<br>Bitte umgehend eine Gutschrift an den Kunden erstellen!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\">Zum Datensatz</a><br><br><br><br><br><br><br><br>";
              }
            elseif($data['EIGEN_RMA']==1 && $_POST['EIGEN_RMA']==0)
              {
                 $o_cont .= "<br><br><br><br><br><br><br><br>Wandlung von interner RMA in Kunden-RMA nicht m&ouml;glich!!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\">Zum Datensatz</a><br><br><br><br><br><br><br><br>";
              }
            elseif($data['EIGEN_RMA']==2 && $_POST['EIGEN_RMA']!=2)
              {
                 $o_cont .= "<br><br><br><br><br><br><br><br>Wandlung von Fremd-RMA nicht m&ouml;glich!!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\">Zum Datensatz</a><br><br><br><br><br><br><br><br>";
              }
            elseif($data['EIGEN_RMA']!=2 && $_POST['EIGEN_RMA']==2)
              {
                 $o_cont .= "<br><br><br><br><br><br><br><br>Wandlung in Fremd-RMA nicht m&ouml;glich!!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\">Zum Datensatz</a><br><br><br><br><br><br><br><br>";
              }
            else
              {
                 if($data['EIGEN_RMA']==1)
                   {
                     mysql_query("UPDATE ".$db_pref."RMA SET KOMMENTAR='".$_POST['KOMMENTAR']."', LIEF_RMA='".$_POST['LIEF_RMA']."' WHERE ID=".$_GET['id'], $db_id);
                   }
                 else
                   {
                     mysql_query("UPDATE ".$db_pref."RMA SET KOMMENTAR='".$_POST['KOMMENTAR']."', LIEF_RMA='".$_POST['LIEF_RMA']."', RS_EMAIL='".$_POST['RS_EMAIL']."', RS_NAME1='".$_POST['RS_NAME1']."', RS_NAME2='".$_POST['RS_NAME2']."', RS_STRASSE='".$_POST['RS_STRASSE']."', RS_ORT='".$_POST['RS_ORT']."', RS_PLZ='".$_POST['RS_PLZ']."', RS_EMAIL='".$_POST['RS_EMAIL']."', RS_TELEFON='".$_POST['RS_TELEFON']."' WHERE ID=".$_GET['id'], $db_id);
                   }
                 mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$_GET['id']."', '0', 'Stammdaten geändert.', CURDATE(), '".$usr_name."')", $db_id);
                 $o_cont .= "<br><br><br><br><br><br><br><br>Datensatz erfolgreich bearbeitet!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=detail&id=".$_GET['id']."\">Zum Datensatz</a><br><br><br><br><br><br><br><br>";
              }
          }
        else
          {
            $o_cont .= "<br><br><br><br><br><br><br><br>FEHLER: Datensatz nicht gefunden!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
          }

        $o_cont .= "</td></tr></table>";
        mysql_free_result($res_id);
      }
    elseif($_GET['action']=="events")
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=events&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        if($_POST['STATUS'])
          {
            if($_POST['ARTNUM'] && $_POST['ANZAHL'])
              {
                $data[STATUS_TEXT] = -1;

                $res_id = mysql_query("SELECT REC_ID, KURZNAME FROM ARTIKEL WHERE ARTNUM='".$_POST['ARTNUM']."'", $db_id);
                $temp = mysql_fetch_assoc($res_id);
                mysql_free_result($res_id);
                $res_id = mysql_query("SELECT ID, ANZAHL FROM ".$db_pref."RMA_TEILE WHERE ARTIKEL_ID=".$temp['REC_ID']." AND RMA_ID=".$_GET['id'], $db_id);
                if(mysql_num_rows($res_id))
                 {
                   $teile = mysql_fetch_assoc($res_id);
                   mysql_query("UPDATE ".$db_pref."RMA_TEILE SET ANZAHL=".($_POST['ANZAHL'] + $teile['ANZAHL'])." WHERE ID=".$teile['ID'], $db_id);
                   $_POST['KOMMENTAR'] = "Anzahl des Ersatzteils ".$temp['KURZNAME']." (".$_POST['ARTNUM'].") von ".$teile['ANZAHL']." auf ".($_POST['ANZAHL'] + $teile['ANZAHL'])." ge&auml;ndert\r\n".$_POST['KOMMENTAR'];
                 }
                else
                 {
                   mysql_query("INSERT INTO ".$db_pref."RMA_TEILE SET ANZAHL=".$_POST['ANZAHL'].", ARTIKEL_ID=".$temp['REC_ID'].", RMA_ID=".$_GET['id'], $db_id);
                   $_POST['KOMMENTAR'] = "Ersatzteil ".$temp['KURZNAME']." (".$_POST['ARTNUM'].") ".$_POST['ANZAHL']." mal hinzugef&uuml;gt\r\n".$_POST['KOMMENTAR'];
                 }
              }
            else
              {
                if($_POST['STATUS']=="Nur Kommentar") $data[STATUS_TEXT] = 0;
                elseif($_POST['STATUS']=="Warte auf defekte Ware") $data[STATUS_TEXT] = 1;
                elseif($_POST['STATUS']=="Defekte Ware eingetroffen") $data[STATUS_TEXT] = 2;
                elseif($_POST['STATUS']=="Defekte Ware eingeschickt") $data[STATUS_TEXT] = 3;
                elseif($_POST['STATUS']=="Ausgetauschte Ware eingetroffen") $data[STATUS_TEXT] = 4;
                elseif($_POST['STATUS']=="Gutschrift eingetroffen") $data[STATUS_TEXT] = 5;
                elseif($_POST['STATUS']=="Austausch abgelehnt") $data[STATUS_TEXT] = 6;
                elseif($_POST['STATUS']=="Kein Fehler feststellbar") $data[STATUS_TEXT] = 7;
                elseif($_POST['STATUS']=="Reparierte Ware eingetroffen") $data[STATUS_TEXT] = 8;
                elseif($_POST['STATUS']=="Ware selbst repariert") $data[STATUS_TEXT] = 9;
                else $data[STATUS_TEXT] = 0;
              }
            $_POST['KOMMENTAR'] = addslashes($_POST['KOMMENTAR']);
            mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$_GET['id']."', '".$data[STATUS_TEXT]."', '".$_POST['KOMMENTAR']."', CURDATE(), '".$usr_name."')", $db_id);
            if($ini_editsn) // Seriennummerstatus in ARTIKEL_SERNUM manipulieren?
              {
                set_snr_status($db_id, $_GET['id'], $db_pref);
              }
          }

        $data = get_data($db_id, $_GET['id'], $db_pref);

        $datalist_id = mysql_query("SELECT * FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[ID]." ORDER BY ID ASC", $db_id);
        $datalist = array();
        $datanumber = mysql_num_rows($datalist_id);
        for($i=0; $i<$datanumber; $i++)
          {
            array_push($datalist, mysql_fetch_array($datalist_id, MYSQL_ASSOC));
          }
        mysql_free_result($datalist_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"4\"><b>&nbsp;Lieferant</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Artikel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" colspan=\"4\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr. bei Lief.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_NR]."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Lieferant:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_NAME]."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">ER-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=detail&id=".$data[LIEF_RID]."\">".$data[LIEF_RNR]."</a></td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[LIEF_RMA]."</td></tr></table></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "<br><br>";
        $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"3\">";
        $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[RMANUM]."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ARTNUM]."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ART_NAME]."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[ART_SNR]."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"top\" width=\"100\">Fehlerbeschr.:</td><td><table width=\"80%\" height=\"112\" cellpadding=\"2\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" valign=\"top\">".$data[FEHLER]."</td></tr></table></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"4\"><b>&nbsp;Kunde</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" colspan=\"4\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_NR]."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunde:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_NAME]."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_RNR]."</td></tr></table></td></tr>";
        if($data[RMA_VALID])
          {
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data[KUN_RDAT]."</td></tr></table></td></tr>";
          }
        else
          {
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#ff0000\">&nbsp;".$data[KUN_RDAT]."</td></tr></table></td></tr>";
          }
        $o_cont .= "</table><br><br>";
        $o_cont .= "</td></tr>";
        $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rma&action=events&id=".$data[ID]."\" method=\"post\" name=\"TARGET\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"4\"><b>&nbsp;Status setzen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Einstellungen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" colspan=\"4\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Status-Typ:</td><td><select name=\"STATUS\" size=\"1\">";
        $o_cont .= "<option selected>Nur Kommentar</option>";
        $o_cont .= "<option>Warte auf defekte Ware</option>";
        $o_cont .= "<option>Defekte Ware eingetroffen</option>";
        $o_cont .= "<option>Defekte Ware eingeschickt</option>";
        $o_cont .= "<option>Ausgetauschte Ware eingetroffen</option>";
        $o_cont .= "<option>Reparierte Ware eingetroffen</option>";
        $o_cont .= "<option>Ware selbst repariert</option>";
        $o_cont .= "<option>Gutschrift eingetroffen</option>";
        $o_cont .= "<option>Austausch abgelehnt</option>";
        $o_cont .= "<option>Kein Fehler feststellbar</option>";
        $o_cont .= "</select></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\" valign=\"top\"><td width=\"100\">Ersatzteil:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"15\" value=\"\"><button name=\"address\" onclick=\"open_artnum(); return false\"><b>...</b></button> Anz.: <input type=\"text\" name=\"ANZAHL\" size=\"4\" value=\"0\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\" valign=\"top\"><td width=\"100\">Kommentar:</td><td><textarea name=\"KOMMENTAR\" cols=\"35\" rows=\"4\"></textarea></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td><td bgcolor=\"#ffffdd\">";
        $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" align=\"center\"><input type=\"submit\" value=\" Eintragen \">&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"reset\" value=\" Zur&uuml;cksetzen \"></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr><tr><td bgcolor=\"#ffffdd\" colspan=\"5\" valign=\"middle\"><b>&nbsp;Vorg&auml;nge</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "</form>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Datum</td><td>&nbsp;Status</td><td>&nbsp;erstellt von</td><td>&nbsp;Kommentar</td></tr>";
        foreach($datalist as $row)
          {
            $data[STATUS_TEXT] = get_status($row[STATUS]);
            $row[KOMMENTAR] = str_replace("\r\n", "<br>", $row[KOMMENTAR]);
            $row[KOMMENTAR] = str_replace("\r", "<br>", $row[KOMMENTAR]);
            $row[KOMMENTAR] = str_replace("\n", "<br>", $row[KOMMENTAR]);
            $row[KOMMENTAR] = stripslashes($row[KOMMENTAR]);

            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\" valign=\"top\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td></td><td>&nbsp;".$row[DATUM]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td>&nbsp;".$row[ERSTELLT]."</td><td>&nbsp;".$row[KOMMENTAR]."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\" valign=\"top\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td></td><td>&nbsp;".$row[DATUM]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td>&nbsp;".$row[ERSTELLT]."</td><td>&nbsp;".$row[KOMMENTAR]."</td></tr>";
              }

          }

        $o_cont .= "</table>";
        $o_cont .= "</table>";
      }

    elseif(($_GET['action']=="finalise") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=finalise&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $data = get_data($db_id, $_GET['id'], $db_pref);

        $o_cont = print_head($data, $_GET['section']);
        $o_cont .= "</td></tr><tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\"><b>&nbsp;Festgestellte Fehler</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "</td></tr><tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\" align=\"center\">";

        $test_id = mysql_query("SELECT STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$_GET['id']." AND STATUS>0 ORDER BY ID DESC LIMIT 1", $db_id);
        $result = mysql_fetch_array($test_id, MYSQL_ASSOC);
        mysql_free_result($test_id);

        if($result['STATUS']<4)
          {
            $o_cont .= "<div style=\"color: #ff0000; font-weight: bold;\"><br><br><br><br><br><br><br><br>Die eingeschickte Ware ist noch nicht wieder eingetroffen.<br><br>Bitte setzen Sie gegebenenfalls den korrekten Status!<br><br><br><br><br><br><br><br></div>";
          }
        else
          {
            $o_cont .= "<div style=\"font-weight: bold;\"><br><br><br><br><br><br><br><br>keine<br><br><br><br><br><br><br><br></div></td></tr><tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\" align=\"center\"><br><form action=\"main.php?section=".$_GET['section']."&module=rma&action=finalise&type=submit&id=".$_GET['id']."\" method=\"post\"><select name=\"rechnung\"><option selected>Keine Kundenrechnung erstellen</option><option>Kostenfreie Garantieleistung</option><option>Kostenpflichtige Serviceleistung</option></select>&nbsp;&nbsp;&nbsp;<input type=\"submit\" value=\"Speichern\"></form><br><br>";
          }

        $o_cont .= "</td></tr></table>";
      }
    elseif(($_GET['action']=="finalise") && ($_GET['type']=="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=finalise&type=submit&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        $test_id = mysql_query("SELECT STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$_GET['id']." AND STATUS>0 ORDER BY ID DESC LIMIT 1", $db_id);
        $result1 = mysql_fetch_array($test_id, MYSQL_ASSOC);
        mysql_free_result($test_id);

        if($result1['STATUS']<4)
          {
            $o_cont .= "<div style=\"color: #ff0000; font-weight: bold;\"><br><br><br><br><br><br><br><br>Die eingeschickte Ware ist noch nicht wieder eingetroffen.<br><br>Bitte setzen Sie gegebenenfalls den korrekten Status!<br><br><br><br><br><br><br><br></div>";
          }
        else
          {
            mysql_query("UPDATE ".$db_pref."RMA SET FINAL='1' WHERE ID=".$_GET['id'], $db_id);

            $test_id = mysql_query("SELECT EIGEN_RMA, ANZAHL FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
            $result2 = mysql_fetch_array($test_id, MYSQL_ASSOC);
            mysql_free_result($test_id);

            if($result2['EIGEN_RMA']==1)
              {
                $res_id = mysql_query("SELECT ART_ID FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
                $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
                mysql_free_result($res_id);

                $tmp_id = mysql_query("SELECT MENGE_AKT FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                $tmp2_id = mysql_query("SELECT RMA_BEST FROM ".$db_pref."BEST WHERE ART_ID=".$data['ART_ID'], $db_id);
                $tmp = mysql_fetch_array($tmp_id, MYSQL_ASSOC);
                $tmp2 = mysql_fetch_array($tmp2_id, MYSQL_ASSOC);
                mysql_free_result($tmp_id);
                mysql_free_result($tmp2_id);
                mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($tmp['MENGE_AKT']+$result2['ANZAHL'])." WHERE REC_ID=".$data['ART_ID'], $db_id);
                mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($tmp2['RMA_BEST']-$result2['ANZAHL'])." WHERE ART_ID=".$data['ART_ID'], $db_id);

                if($_POST['rechnung']=="Keine Kundenrechnung erstellen")
                  {
                    $o_cont .= "<br><br><br><br><br><br><br><br>RMA-Vorgang abgeschlossen, Best&auml;nde angepasst.<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
                  }
                else
                  {
                      $o_cont .= "<br><br><br><br><br><br><br><br>RMA-Vorgang abgeschlossen, Best&auml;nde angepasst.<br>Da es sich um eine Eigen-RMA handelt, wurde keine Kundenrechnung erstellt!<br><br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
                  }
              }
            else
              {
                $res_id = mysql_query("SELECT * FROM ".$db_pref."RMA WHERE ID=".$_GET['id'], $db_id);
		        $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
                mysql_free_result($res_id);

                if($_POST['rechnung']=="Keine Kundenrechnung erstellen")
                  {
                    $o_cont .= "<br><br><br><br><br><br><br><br>RMA-Vorgang abgeschlossen.<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
                  }
                elseif(($_POST['rechnung']=="Kostenfreie Garantieleistung")||($_POST['rechnung']=="Kostenpflichtige Serviceleistung"))
                  {
                    $res_id = mysql_query("SELECT ANZAHL, ARTIKEL_ID FROM ".$db_pref."RMA_TEILE WHERE ANZAHL IS NOT NULL AND RMA_ID=".$_GET['id'] ,$db_id);
                    $teile = array();
                    $t_num = mysql_num_rows($res_id);
                    for($i=0; $i<$t_num; $i++)
                      {
                        array_push($teile, mysql_fetch_array($res_id, MYSQL_ASSOC));
                      }
                    mysql_free_result($res_id);

                    // Rechnung erstellen:

                    $mwst = get_mwst($db_id);
                    $maindata = array();

                    foreach($mwst as $temp)
                      {
                        if($temp['NAME']=="0")
                          {
                            $maindata['MWST_0'] = $temp['VAL_DOUBLE'];
                          }
                        elseif($temp['NAME']=="1")
                          {
                            $maindata['MWST_1'] = $temp['VAL_DOUBLE'];
                          }
                        elseif($temp['NAME']=="2")
                          {
                            $maindata['MWST_2'] = $temp['VAL_DOUBLE'];
                          }
                        elseif($temp['NAME']=="3")
                          {
                            $maindata['MWST_3'] = $temp['VAL_DOUBLE'];
                          }
                      }

                    // Dummywerte:

                    $maindata['LIEFART'] = -1;
                    $maindata['ZAHLART'] = -1;
                    $maindata['VERTRETER_ID'] = 0;
                    $maindata['ADDR_ID'] = 0;
                    $maindata['LIEF_ADDR_ID'] = -1;
                    $maindata['SOLL_RATINTERVALL'] = 1;
                    $maindata['QUELLE_SUB'] = 0;
                    $maindata['KM_STAND'] = -1;
                    $maindata['PR_EBENE'] = 5;
                    $maindata['ADATUM'] = "1899-12-30";
                    $maindata['LDATUM'] = "1899-12-30";
                    $maindata['TERMIN'] = "1899-12-30";
                    $maindata['WAEHRUNG'] = "€";

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

                    $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, ABTEILUNG, STRASSE, LAND, PLZ, ORT, NET_TAGE, NET_SKONTO, BRT_TAGE, PR_EBENE, KUN_LIEFART, KUN_ZAHLART, BRUTTO_FLAG, DEB_NUM FROM ADRESSEN WHERE REC_ID='".$data['KUN_ID']."'", $db_id);
                    $kundata = mysql_fetch_array($res_id, MYSQL_ASSOC);
                    mysql_free_result($res_id);

                    $query = "INSERT INTO JOURNAL SET
                               VRENUM='".$maindata['VRENUM']."',
                               VERTRETER_ID='".$maindata['VERTRETER_ID']."',
                               ADDR_ID='".$data['KUN_ID']."',
                               LIEF_ADDR_ID='".$maindata['LIEF_ADDR_ID']."',
                               SOLL_RATINTERVALL='".$maindata['SOLL_RATINTERVALL']."',
                               QUELLE_SUB='".$maindata['QUELLE_SUB']."',
                               KM_STAND='".$maindata['KM_STAND']."',
                               ADATUM='".$maindata['ADATUM']."',
                               LDATUM='".$maindata['LDATUM']."',
                               TERMIN='".$maindata['TERMIN']."',
                               WAEHRUNG='".$maindata['WAEHRUNG']."',
                               MWST_0='".$maindata['MWST_0']."',
                               MWST_1='".$maindata['MWST_1']."',
                               MWST_2='".$maindata['MWST_2']."',
                               MWST_3='".$maindata['MWST_3']."',
                               RDATUM=CURDATE(),
                               ERSTELLT=CURDATE(),
                               ERST_NAME='".$usr_name."',
                               KUN_NUM='".$kundata['KUNNUM1']."',
                               KUN_ANREDE='".$kundata['ANREDE']."',
                               KUN_NAME1='".$kundata['NAME1']."',
                               KUN_NAME2='".$kundata['NAME2']."',
                               KUN_NAME3='".$kundata['NAME3']."',
                               KUN_ABTEILUNG='".$kundata['ABTEILUNG']."',
                               KUN_STRASSE='".$kundata['STRASSE']."',
                               KUN_LAND='".$kundata['LAND']."',
                               KUN_PLZ='".$kundata['PLZ']."',
                               KUN_ORT='".$kundata['ORT']."',
                               SOLL_STAGE='".$kundata['NET_TAGE']."',
                               SOLL_SKONTO='".$kundata['NET_SKONTO']."',
                               SOLL_NTAGE='".$kundata['BRT_TAGE']."',
                               BRUTTO_FLAG='".$kundata['BRUTTO_FLAG']."',
                               PR_EBENE='".$kundata['PR_EBENE']."',
                               LIEFART='".$kundata['KUN_LIEFART']."',
                               ZAHLART='".$kundata['KUN_ZAHLART']."',
                               GEGENKONTO='".$kundata['DEB_NUM']."',
                               QUELLE='13'";

                    if(!mysql_query($query, $db_id))
                      {
                        echo mysql_error($db_id)."<br>";
                      }
                    else
                      {
                        $insert_id = mysql_insert_id($db_id);
                      }

                    $position = 1;

                    if($result1['STATUS']==4)					// Austauschpositionen für Seriennummern
                      {
                        if($data['ART_SNR'])
                          {
                            $rec_id = mysql_query("SELECT * FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                            $artikel = mysql_fetch_assoc($rec_id);
                            mysql_free_result($rec_id);

                            mysql_query("INSERT INTO JOURNALPOS SET
                                          QUELLE=13,
                                          MATCHCODE='".$artikel['MATCHCODE']."',
                                          VRENUM='".$maindata['VRENUM']."',
                                          BARCODE='".$artikel['BARCODE']."',
                                          LAENGE='".$artikel['LAENGE']."',
                                          BREITE='".$artikel['BREITE']."',
                                          HOEHE='".$artikel['HOEHE']."',
                                          GROESSE='".$artikel['GROESSE']."',
                                          DIMENSION='".$artikel['DIMENSION']."',
                                          GEWICHT='".$artikel['GEWICHT']."',
                                          PR_EINHEIT='".$artikel['PR_EINHEIT']."',
                                          BEZEICHNUNG='".$artikel['LANGNAME']."',
                                          JOURNAL_ID=".$insert_id.",
                                          ADDR_ID=".$data['KUN_ID'].",
                                          ARTIKEL_ID=".$data['ART_ID'].",
                                          ARTNUM='".$artikel['ARTNUM']."',
                                          EK_PREIS='".$artikel['EK_PREIS']."',
                                          EPREIS='".$artikel['VK5']."',
                                          GPREIS='".($artikel['VK5'] * $data['ANZAHL'])."',
                                          SN_FLAG='".$artikel['SN_FLAG']."',
                                          ME_EINHEIT='".$artikel['ME_EINHEIT']."',
                                          ARTIKELTYP='".$artikel['ARTIKELTYP']."',
                                          STEUER_CODE=2,
                                          POSITION='".$position."',
                                          MENGE=".$data['ANZAHL'], $db_id);
                            $position++;

                            mysql_query("INSERT INTO JOURNALPOS SET
                                          QUELLE=13,
					  MATCHCODE='".$artikel['MATCHCODE']."',
					  VRENUM='".$maindata['VRENUM']."',
					  BARCODE='".$artikel['BARCODE']."',
					  LAENGE='".$artikel['LAENGE']."',
					  BREITE='".$artikel['BREITE']."',
					  HOEHE='".$artikel['HOEHE']."',
					  GROESSE='".$artikel['GROESSE']."',
					  DIMENSION='".$artikel['DIMENSION']."',
					  GEWICHT='".$artikel['GEWICHT']."',
					  PR_EINHEIT='".$artikel['PR_EINHEIT']."',
					  BEZEICHNUNG='".$artikel['LANGNAME']."',
					  JOURNAL_ID=".$insert_id.",
					  ADDR_ID=".$data['KUN_ID'].",
					  ARTIKEL_ID=".$data['ART_ID'].",
					  ARTNUM='".$artikel['ARTNUM']."',
					  EK_PREIS='".$artikel['EK_PREIS']."',
					  EPREIS='".$artikel['VK5']."',
					  GPREIS='".($artikel['VK5'] * $data['ANZAHL'] * -1)."',
					  SN_FLAG='N',
					  ME_EINHEIT='".$artikel['ME_EINHEIT']."',
					  ARTIKELTYP='".$artikel['ARTIKELTYP']."',
					  STEUER_CODE=2,
					  POSITION='".$position."',
                                          MENGE=".($data['ANZAHL'] * -1), $db_id);
                            $position++;

                            echo  mysql_error($db_id);
                          }
                      }
                    elseif($result1['STATUS']==5)				// Gutschrift
                      {
                        $rec_id = mysql_query("SELECT * FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                        $artikel = mysql_fetch_assoc($rec_id);
                        mysql_free_result($rec_id);

                        mysql_query("INSERT INTO JOURNALPOS SET
                                          QUELLE=13,
                                          MATCHCODE='".$artikel['MATCHCODE']."',
                                          VRENUM='".$maindata['VRENUM']."',
                                          BARCODE='".$artikel['BARCODE']."',
                                          LAENGE='".$artikel['LAENGE']."',
                                          BREITE='".$artikel['BREITE']."',
                                          HOEHE='".$artikel['HOEHE']."',
                                          GROESSE='".$artikel['GROESSE']."',
                                          DIMENSION='".$artikel['DIMENSION']."',
                                          GEWICHT='".$artikel['GEWICHT']."',
                                          PR_EINHEIT='".$artikel['PR_EINHEIT']."',
                                          BEZEICHNUNG='".$artikel['LANGNAME']."',
                                          JOURNAL_ID=".$insert_id.",
                                          ADDR_ID=".$data['KUN_ID'].",
                                          ARTIKEL_ID=".$data['ART_ID'].",
                                          ARTNUM='".$artikel['ARTNUM']."',
                                          EK_PREIS='".$artikel['EK_PREIS']."',
                                          EPREIS='".$artikel['VK5']."',
                                          GPREIS='".($artikel['VK5'] * $data['ANZAHL'] * -1)."',
                                          SN_FLAG='N',
                                          ME_EINHEIT='".$artikel['ME_EINHEIT']."',
                                          ARTIKELTYP='".$artikel['ARTIKELTYP']."',
                                          STEUER_CODE=2,
                                          POSITION='".$position."',
                                          MENGE=".($data['ANZAHL'] * -1), $db_id);
                        $position++;

                        echo  mysql_error($db_id);
                      }

                    if(count($teile))						// Ersatzteile hinzufügen
                      {
                        foreach($teile as $dataset)
                          {
                            $rec_id = mysql_query("SELECT * FROM ARTIKEL WHERE REC_ID=".$dataset['ARTIKEL_ID'], $db_id);
                            $artikel = mysql_fetch_assoc($rec_id);
                            mysql_free_result($rec_id);

                            mysql_query("INSERT INTO JOURNALPOS SET
                                          QUELLE=13,
                                          MATCHCODE='".$artikel['MATCHCODE']."',
                                          VRENUM='".$maindata['VRENUM']."',
                                          BARCODE='".$artikel['BARCODE']."',
                                          LAENGE='".$artikel['LAENGE']."',
                                          BREITE='".$artikel['BREITE']."',
                                          HOEHE='".$artikel['HOEHE']."',
                                          GROESSE='".$artikel['GROESSE']."',
                                          DIMENSION='".$artikel['DIMENSION']."',
                                          GEWICHT='".$artikel['GEWICHT']."',
                                          PR_EINHEIT='".$artikel['PR_EINHEIT']."',
                                          BEZEICHNUNG='".$artikel['LANGNAME']."',
                                          JOURNAL_ID=".$insert_id.",
                                          ADDR_ID=".$data['KUN_ID'].",
                                          ARTIKEL_ID=".$data['ART_ID'].",
                                          ARTNUM='".$artikel['ARTNUM']."',
                                          EK_PREIS='".$artikel['EK_PREIS']."',
                                          EPREIS='".$artikel['VK5']."',
                                          GPREIS='".($artikel['VK5'] * $data['ANZAHL'])."',
                                          SN_FLAG='".$artikel['SN_FLAG']."',
                                          ME_EINHEIT='".$artikel['ME_EINHEIT']."',
                                          ARTIKELTYP='".$artikel['ARTIKELTYP']."',
                                          STEUER_CODE=2,
                                          POSITION='".$position."',
                                          MENGE=".$data['ANZAHL'], $db_id);
                            $position++;

                            echo  mysql_error($db_id);
                          }
                      }

                    if($_POST['rechnung']=="Kostenfreie Garantieleistung")
                      {
                        if(!mysql_query("UPDATE JOURNALPOS SET EPREIS=0, GPREIS=0 WHERE JOURNAL_ID=".$insert_id, $db_id))
                          {
			    echo mysql_error($db_id)."<br>";
                          }
                      }

                    set_journal($insert_id, $db_id);		// Alle Werte richten

                    $o_cont .= "<br><br><br><br><br><br><br><br>RMA-Vorgang abgeschlossen.<br>Kundenbeleg wurde erstellt: <a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=".$insert_id."\">Rechnung bearbeiten</a><br><br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
                  }
                else
                  {
                    $o_cont .= "<br><br><br><br><br><br><br><br>RMA-Vorgang abgeschlossen.<br>Erstellen einer Kundenrechnung nicht m&ouml;glich!<br><br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
                  }
              }
          }

        $o_cont .= "</td></tr></table>";

      }
    elseif(($_GET['action']=="init") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=init

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
        $o_cont .= "<br><br><br><br><br>";
        $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                <tr><td bgcolor=\"#808080\" align=\"center\"><h1>RMA-Art w&auml;hlen:</h1></td></tr>
                <tr><td bgcolor=\"#808080\" align=\"left\">
                <form action=\"main.php?section=".$_GET['section']."&module=rma&action=create\" method=\"post\"><br>
                 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"radio\" name=\"method\" value=\"ERMA\" checked>&nbsp;&nbsp;Eigene RMA<br>
                 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"radio\" name=\"method\" value=\"KRMA\">&nbsp;&nbsp;Kunden-RMA<br>
                 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"radio\" name=\"method\" value=\"FRMA\">&nbsp;&nbsp;Fremd-RMA<br><br>
                 <div align=\"center\"><input type=\"submit\" name=\"create\" value=\"Weiter\">
                </form>
                </td></tr></table>";
        $o_cont .= "<br><br><br><br>";
        $o_cont .= "Der Einfachheit halber sollte eine <b>Eigen-RMA</b> direkt aus dem <b>Wareneingangs-Journal</b>,<br>eine <b>Kunden-RMA</b> aus dem <b>Rechnungs-Journal</b> erstellt werden!<br><br><b>In den Belegdetails sind Links vorhanden, die entsprechend vorbereitete Belege automatisch erstellen.</b>";
        $o_cont .= "<br><br><br><br>";
        $o_cont .= "</td></tr></table>";
      }

    elseif($_GET['action']=="copy")
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=copy&id=xxxxxxx

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";

        if(!$_GET['id'])
          {
            $o_cont = "<br><br><br><br><br><br><br><br>FEHLER: Keine ID angegeben!<br><a href=\"javascript:history.back()\">Zur&uuml;ck</a><br><br><br><br><br><br><br><br>";
          }
        else
          {
            $data = get_data($db_id, $_GET['id'], $db_pref);

            switch($data['EIGEN_RMA'])
              {
                case 0: $method = "KRMA"; break;
                case 1: $method = "ERMA"; break;
                case 2: $method = "FRMA"; break;
              }

            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>RMA ".$data['RMANUM']." kopieren:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?module=rma&action=create\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"method\" value=\"".$method."\">
                         <input type=\"hidden\" name=\"ART_ID\" value=\"".$data['ART_ID']."\">
                         <input type=\"hidden\" name=\"ART_SNR\" value=\"".$data['ART_SNR']."\">
                         <input type=\"hidden\" name=\"KUN_ID\" value=\"".$data['KUN_ID']."\">
                         <input type=\"hidden\" name=\"KUN_RID\" value=\"".$data['KUN_RID']."\">
                         <input type=\"hidden\" name=\"LIEF_ID\" value=\"".$data['LIEF_ID']."\">
                         <input type=\"hidden\" name=\"LIEF_RID\" value=\"".$data['LIEF_RID']."\">
                         <input type=\"hidden\" name=\"LIEF_RMA\" value=\"".$data['LIEF_RMA']."\">
                         <input type=\"hidden\" name=\"FEHLER\" value=\"".$data['FEHLER']."\">
                         <input type=\"hidden\" name=\"ANZAHL\" value=\"".$data['ANZAHL']."\">
                         <div align=\"center\"><input type=\"submit\" name=\"create\" value=\"Weiter\">
                        </form>
                        </td></tr></table>";
            $o_cont .= "<br><br><br><br><br><br><br><br>";
            $o_cont .= "</td></tr></table>";

          }

      }

    elseif(($_GET['action']=="create") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=create

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";


        // Daten aus anderen Modulen (WE-Journal, RE-Journal, etc.)

        if($_POST['LIEF_RNR']) $data['LIEF_RNR'] = $_POST['LIEF_RNR'];
        if($_POST['LIEF_NR']) $data['LIEF_NR'] = $_POST['LIEF_NR'];
        if($_POST['KUN_RNR']) $data['KUN_RNR'] = $_POST['KUN_RNR'];
        if($_POST['KUN_NR']) $data['KUN_NR'] = $_POST['KUN_NR'];
        if($_POST['ARTNUM']) $data['ARTNUM'] = $_POST['ARTNUM'];
        if($_POST['ART_SNR']) $data['ART_SNR'] = $_POST['ART_SNR'];
        if($_POST['JOURNALPOS_ID']) $data['JOURNALPOS_ID'] = $_POST['JOURNALPOS_ID'];

        // Daten aus fehlgeschlagenen Versuchen

        if($_POST['ANZAHL']) $data['ANZAHL'] = $_POST['ANZAHL']; else $data['ANZAHL'] = 1;
        if($_POST['FEHLER']) $data['FEHLER'] = $_POST['FEHLER'];
        if($_POST['LIEF_RMA']) $data['LIEF_RMA'] = $_POST['LIEF_RMA'];
        if($_POST['ART_ID'])
          {
            $res_id = mysql_query("SELECT ARTNUM FROM ARTIKEL WHERE REC_ID=".$_POST['ART_ID'], $db_id);
            $tp_res = mysql_fetch_array($res_id, MYSQL_ASSOC);
            $data['ARTNUM'] = $tp_res['ARTNUM'];
            mysql_free_result($res_id);
          }
        if($_POST['KUN_ID'])
          {
            $res_id = mysql_query("SELECT KUNNUM1 FROM ADRESSEN WHERE REC_ID=".$_POST['KUN_ID'], $db_id);
            $tp_res = mysql_fetch_array($res_id, MYSQL_ASSOC);
            $data['KUN_NR'] = $tp_res['KUNNUM1'];
            mysql_free_result($res_id);
          }
        if($_POST['LIEF_ID'])
          {
            $res_id = mysql_query("SELECT KUNNUM2 FROM ADRESSEN WHERE REC_ID=".$_POST['LIEF_ID'], $db_id);
            $tp_res = mysql_fetch_array($res_id, MYSQL_ASSOC);
            $data['LIEF_NR'] = $tp_res['KUNNUM2'];
            mysql_free_result($res_id);
          }
        if($_POST['KUN_RID'])
          {
            $res_id = mysql_query("SELECT VRENUM FROM JOURNAL WHERE REC_ID=".$_POST['KUN_RID'], $db_id);
            $tp_res = mysql_fetch_array($res_id, MYSQL_ASSOC);
            $data['KUN_RNR'] = $tp_res['VRENUM'];
            mysql_free_result($res_id);
          }
        if($_POST['LIEF_RID'])
          {
            $res_id = mysql_query("SELECT ORGNUM FROM JOURNAL WHERE REC_ID=".$_POST['LIEF_RID'], $db_id);
            $tp_res = mysql_fetch_array($res_id, MYSQL_ASSOC);
            $data['LIEF_RNR'] = $tp_res['ORGNUM'];
            mysql_free_result($res_id);
          }


        if($_POST['method']=="ERMA") // Formular für Eigene RMA
          {
            $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><form action=\"main.php?section=".$_GET['section']."&module=rma&action=create&type=submit\" method=\"post\" name=\"TARGET\">";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferant</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Artikel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr. bei Lief.:</td><td><input type=\"text\" name=\"LIEF_NR\" size=\"30\" value=\"".$data['LIEF_NR']."\"><button name=\"address\" onclick=\"open_lief(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">ER-Nummer:</td><td><input type=\"text\" name=\"LIEF_RNR\" size=\"30\" value=\"".$data['LIEF_RNR']."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><input type=\"text\" name=\"LIEF_RMA\" size=\"30\" value=\"".$data['LIEF_RMA']."\"></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"30\" value=\"".$data['ARTNUM']."\"><button name=\"address\" onclick=\"open_artnum(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><input type=\"text\" name=\"ANZAHL\" size=\"3\" value=\"".$data['ANZAHL']."\"></td></tr>";
            $o_cont .= print_sn_field($db_id, $data['JOURNALPOS_ID'], $data['ART_SNR'], $db_pref);
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\" valign=\"top\">Fehlerbeschr.:</td><td><textarea name=\"ERROR\" cols=\"50\" rows=\"5\">".$data['FEHLER']."</textarea></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"2\" align=\"center\"><br><input type=\"submit\" value=\" Erstellen \"><br><br></td></tr>";
            $o_cont .= "<input type=\"hidden\" name=\"method\" value=\"".$_POST['method']."\"><input type=\"hidden\" name=\"JOURNALPOS_ID\" value=\"".$data['JOURNALPOS_ID']."\">";
            $o_cont .= "</form></table>";
          }
        elseif($_POST['method']=="KRMA") // Formular für Kunden-RMA
          {
            $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><form action=\"main.php?section=".$_GET['section']."&module=rma&action=create&type=submit\" method=\"post\" name=\"TARGET\">";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferant</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Artikel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr. bei Lief.:</td><td><input type=\"text\" name=\"LIEF_NR\" size=\"30\" value=\"".$data['LIEF_NR']."\"><button name=\"address\" onclick=\"open_lief(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">ER-Nummer:</td><td><input type=\"text\" name=\"LIEF_RNR\" size=\"30\" value=\"".$data['LIEF_RNR']."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><input type=\"text\" name=\"LIEF_RMA\" size=\"30\" value=\"".$data['LIEF_RMA']."\"></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"3\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"30\" value=\"".$data['ARTNUM']."\"><button name=\"address\" onclick=\"open_artnum(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><input type=\"text\" name=\"ANZAHL\" size=\"3\" value=\"".$data['ANZAHL']."\"></td></tr>";
            $o_cont .= print_sn_field($db_id, $data['JOURNALPOS_ID'], $data['ART_SNR'], $db_pref);
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\" valign=\"top\">Fehlerbeschr.:</td><td><textarea name=\"ERROR\" cols=\"50\" rows=\"5\">".$data['FEHLER']."</textarea></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Kunde</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NR\" size=\"30\" value=\"".$data['KUN_NR']."\"><button name=\"address\" onclick=\"open_kunde(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Rechnungs-Nr.:</td><td><input type=\"text\" name=\"KUN_RNR\" size=\"30\" value=\"".$data['KUN_RNR']."\"></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"2\" align=\"center\"><br><input type=\"submit\" value=\" Erstellen \"><br><br></td></tr>";
            $o_cont .= "<input type=\"hidden\" name=\"method\" value=\"".$_POST['method']."\"><input type=\"hidden\" name=\"JOURNALPOS_ID\" value=\"".$data['JOURNALPOS_ID']."\">";
            $o_cont .= "</form></table>";
          }
        elseif($_POST['method']=="FRMA")  // Formular für Fremd-RMA
          {
            $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><form action=\"main.php?section=".$_GET['section']."&module=rma&action=create&type=submit\" method=\"post\" name=\"TARGET\">";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferant</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Artikel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr. bei Lief.:</td><td><input type=\"text\" name=\"LIEF_NR\" size=\"30\" value=\"".$data['LIEF_NR']."\"><button name=\"address\" onclick=\"open_lief(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">RMA-Nummer:</td><td><input type=\"text\" name=\"LIEF_RMA\" size=\"30\" value=\"".$data['LIEF_RMA']."\"></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"3\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"30\" value=\"".$data['ARTNUM']."\"><button name=\"address\" onclick=\"open_artnum(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><input type=\"text\" name=\"ANZAHL\" size=\"3\" value=\"".$data['ANZAHL']."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><input type=\"text\" name=\"SERIAL\" size=\"30\" value=\"".$data['ART_SNR']."\"></td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\" valign=\"top\">Fehlerbeschr.:</td><td><textarea name=\"ERROR\" cols=\"50\" rows=\"5\">".$data['FEHLER']."</textarea></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Kunde</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
            $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NR\" size=\"30\" value=\"".$data['KUN_NR']."\"><button name=\"address\" onclick=\"open_kunde(); return false\"><b>...</b></button></td></tr>";
            $o_cont .= "</table>";
            $o_cont .= "</td></tr>";
            $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"2\" align=\"center\"><br><input type=\"submit\" value=\" Erstellen \"><br><br></td></tr>";
            $o_cont .= "<input type=\"hidden\" name=\"method\" value=\"".$_POST['method']."\">";
            $o_cont .= "</form></table>";
          }
      }

    elseif(($_GET['action']=="create") && ($_GET['type']=="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rma&action=create&type=submit

        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        $error = "";


 // ---------------------------------------------------------------------------------------------------------------------------


        // Daten sammeln / Plausibilitätsprüfungen:

        if($_POST['LIEF_NR'])  // Lieferant
          {
            if($res_id = mysql_query("SELECT REC_ID FROM ADRESSEN WHERE KUNNUM2='".$_POST['LIEF_NR']."'", $db_id))
              {
                $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                mysql_free_result($res_id);
              }
            else
              {
                $tmp = 0;
              }

            if($tmp['REC_ID'])
              {
                $data['LIEF_ID'] = $tmp['REC_ID'];
              }
            else
              {
                $error .= "<b>FEHLER:</b> Kundennummer des Lieferanten nicht im System!<br>";
              }
          }
        else
          {
            $error .= "<b>FEHLER:</b> Keine Kundennummer vom Lieferanten angegeben!<br>";
          }


        if($_POST['ARTNUM'])  // Artikel
          {
            if($res_id = mysql_query("SELECT REC_ID FROM ARTIKEL WHERE ARTNUM='".$_POST['ARTNUM']."'", $db_id))
              {
                $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                mysql_free_result($res_id);
              }
            else
              {
                $tmp = 0;
              }

            if($tmp['REC_ID'])
              {
                $data['ART_ID'] = $tmp['REC_ID'];
              }
            else
              {
                $error .= "<b>FEHLER:</b> Artikelnummer nicht im System!<br>";
              }
          }
        else
          {
            $error .= "<b>FEHLER:</b> Keine Artikelnummer angegeben!<br>";
          }


        if($_POST['ERROR'])  // Fehlerbeschreibung
          {
            $data['FEHLER'] = addslashes($_POST['ERROR']);
          }
        else
          {
            $error .= "<b>FEHLER:</b> Keine Fehlerbeschreibung eingegeben!<br>";
          }

        if($_POST['ANZAHL'] > 0)  // Anzahl
          {
            $data['ANZAHL'] = $_POST['ANZAHL'];
          }
        else
          {
            $error .= "<b>FEHLER:</b> Anzahl der Artikel kleiner oder gleich null!<br>";
          }

        if($_POST['SERIAL']) $data['ART_SNR'] = $_POST['SERIAL']; else $data['ART_SNR'] = 0;
        if($_POST['LIEF_RMA']) $data['LIEF_RMA'] = $_POST['LIEF_RMA']; else $data['LIEF_RMA'] = 0;


// ---------------------------------------------------------------------------------------------------------------------------


        if($_POST[method]=="ERMA")  //  Eigene RMA
          {
            if($_POST['LIEF_RNR'])  // Wareneingang
              {
                if($res_id = mysql_query("SELECT REC_ID, ADDR_ID FROM JOURNAL WHERE ORGNUM='".$_POST['LIEF_RNR']."' AND QUELLE=5", $db_id))
                  {
                    $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $tmp = 0;
                  }

                if($tmp['REC_ID'])
                  {
                    $data['LIEF_RID'] = $tmp['REC_ID'];
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Rechnungsnummer des Lieferanten nicht im System!<br>";
                  }
                if($tmp['ADDR_ID'] != $data['LIEF_ID'])
                  {
                    $error .= "<b>FEHLER:</b> Rechnungsnummer geh&ouml;rt nicht zu angegebenem Lieferanten!<br>";
                  }
              }
            else
              {
                $error .= "<b>FEHLER:</b> Keine Rechnungsnummer vom Lieferanten angegeben!<br>";
              }

            if($data['ART_ID'] && $data['LIEF_RID'])  // Artikel in Wareneingang
              {
                if($res_id = mysql_query("SELECT REC_ID FROM JOURNALPOS WHERE ARTIKEL_ID=".$data['ART_ID']." AND JOURNAL_ID=".$data['LIEF_RID'], $db_id))
                  {
                    $tmp = mysql_num_rows($res_id);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Artikel nicht in Wareneingangsrechnung!<br>";
                  }
              }
          }


// ---------------------------------------------------------------------------------------------------------------------------


        if($_POST[method]=="KRMA")  // Kunden-RMA
          {

            if($_POST['KUN_NR'])
              {
                if($res_id = mysql_query("SELECT REC_ID FROM ADRESSEN WHERE KUNNUM1='".$_POST['KUN_NR']."'", $db_id))
                  {
                    $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $tmp = 0;
                  }

                if($tmp['REC_ID'])
                  {
                    $data['KUN_ID'] = $tmp['REC_ID'];

                    if($_POST['KUN_RNR'])
                      {
                        if($res_id = mysql_query("SELECT REC_ID FROM JOURNAL WHERE VRENUM='".$_POST['KUN_RNR']."' AND QUELLE=3", $db_id))
                          {
                            $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                            mysql_free_result($res_id);
                          }
                        else
                          {
                            $tmp = 0;
                          }

                        if($tmp['REC_ID'])
                          {
                            $data['KUN_RID'] = $tmp['REC_ID'];
                          }
                        else
                          {
                            $error .= "<b>FEHLER:</b> Kunden-Rechnungsnummer nicht im System!<br>";
                          }
                      }
                    else
                      {
                        $error .= "<b>FEHLER:</b> Keine Kunden-Rechnungsnummer angegeben!<br>";
                      }
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Keine Kunden-Nummer angegeben!<br>";
                  }
              }

            if($_POST['LIEF_RNR'])  // Wareneingang
              {
                if($res_id = mysql_query("SELECT REC_ID, ADDR_ID FROM JOURNAL WHERE ORGNUM='".$_POST['LIEF_RNR']."' AND QUELLE=5", $db_id))
                  {
                    $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $tmp = 0;
                  }

                if($tmp['REC_ID'])
                  {
                    $data['LIEF_RID'] = $tmp['REC_ID'];
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Rechnungsnummer des Lieferanten nicht im System!<br>";
                  }
                if($tmp['ADDR_ID'] != $data['LIEF_ID'])
                  {
                    $error .= "<b>FEHLER:</b> Rechnungsnummer geh&ouml;rt nicht zu angegebenem Lieferanten!<br>";
                  }
              }
            else
              {
                $error .= "<b>FEHLER:</b> Keine Rechnungsnummer vom Lieferanten angegeben!<br>";
              }

            if($data['ART_ID'] && $data['LIEF_RID'])  // Artikel in Wareneingang
              {
                if($res_id = mysql_query("SELECT REC_ID FROM JOURNALPOS WHERE ARTIKEL_ID=".$data['ART_ID']." AND JOURNAL_ID=".$data['LIEF_RID'], $db_id))
                  {
                    $tmp = mysql_num_rows($res_id);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Artikel nicht in Wareneingangsrechnung!<br>";
                  }
              }

            if($data['ART_ID'] && $data['KUN_RID'])  // Artikel in Kundenrechnung
              {
                if($res_id = mysql_query("SELECT REC_ID FROM JOURNALPOS WHERE ARTIKEL_ID=".$data['ART_ID']." AND JOURNAL_ID=".$data['KUN_RID'], $db_id))
                  {
                    $tmp = mysql_num_rows($res_id);
                    mysql_free_result($res_id);
                  }
                else
                  {
                    $error .= "<b>FEHLER:</b> Artikel nicht in Kundenrechnung!<br>";
                  }
              }
          }

// ---------------------------------------------------------------------------------------------------------------------------


        if($_POST[method]=="FRMA")  // Fremd-RMA
          {
            if($res_id = mysql_query("SELECT REC_ID FROM ADRESSEN WHERE KUNNUM1='".$_POST['KUN_NR']."'", $db_id))
              {
                $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
                mysql_free_result($res_id);
              }
            else
              {
                $tmp = 0;
                $error .= "<b>FEHLER:</b> Kunden-Nummer nicht im System!<br>";
              }

            if($tmp['REC_ID'])
              {
                $data['KUN_ID'] = $tmp['REC_ID'];
              }
            else
              {
                $error .= "<b>FEHLER:</b> Keine Kunden-Rechnungsnummer angegeben!<br>";
              }
          }

// ---------------------------------------------------------------------------------------------------------------------------


        if($error == "")
          {
            $res_id = mysql_query("SELECT RMANUM FROM ".$db_pref."RMA ORDER BY RMANUM DESC LIMIT 1", $db_id);
            $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            if($tmp['RMANUM']) // RMA Nummer generieren
              {
                $data['RMANUM'] = $tmp['RMANUM']+1;
              }
            else
              {
                $data['RMANUM'] = 930000;
              }

            // Eintrag in RMA-Bestand vorbereiten, falls nicht vorhanden:

            if($tmp2_id = mysql_query("SELECT RMA_BEST FROM ".$db_pref."BEST WHERE ART_ID=".$data['ART_ID'], $db_id))
              {
                $s_test = mysql_num_rows($tmp2_id);
                $tmp2 = mysql_fetch_array($tmp2_id, MYSQL_ASSOC);
                mysql_free_result($tmp2_id);

                if($s_test==0)
                  {
                    $tmp2['RMA_BEST'] = 0;
                    mysql_query("INSERT INTO ".$db_pref."BEST SET ART_ID=".$data['ART_ID'], $db_id);
                  }
              }
            else
              {
                $tmp2['RMA_BEST'] = 0;
                mysql_query("INSERT INTO ".$db_pref."BEST SET ART_ID=".$data['ART_ID'], $db_id);
              }

            // Alles OK, Daten in DB schreiben und Meldung ausgeben:

            if($_POST[method]=="ERMA" && mysql_query("INSERT INTO ".$db_pref."RMA SET RMANUM='".$data['RMANUM']."', ART_ID='".$data['ART_ID']."', ART_SNR='".$data['ART_SNR']."', LIEF_ID='".$data['LIEF_ID']."', LIEF_RID='".$data['LIEF_RID']."', LIEF_RMA='".$data['LIEF_RMA']."', ERSTELLT='".$usr_name."', FEHLER='".$data['FEHLER']."', EIGEN_RMA='1', ERSTDAT=CURDATE(), ANZAHL=".$data['ANZAHL'], $db_id))
              {
                $data['ID'] = mysql_insert_id();
                mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$data['ID']."', '1', 'RMA erstellt.', CURDATE(), '".$usr_name."')", $db_id);

                $tmp_id = mysql_query("SELECT MENGE_AKT FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
                $tmp = mysql_fetch_array($tmp_id, MYSQL_ASSOC);
                mysql_free_result($tmp_id);

                mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($tmp['MENGE_AKT']-$data['ANZAHL'])." WHERE REC_ID=".$data['ART_ID'], $db_id);
                mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($tmp2['RMA_BEST']+$data['ANZAHL'])." WHERE ART_ID=".$data['ART_ID'], $db_id);

                $o_cont .= "<br><br><br><br><br><br><br><br>RMA erfolgreich erstellt!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
              }
            elseif($_POST[method]=="KRMA" && mysql_query("INSERT INTO ".$db_pref."RMA SET RMANUM='".$data['RMANUM']."', ART_ID='".$data['ART_ID']."', ART_SNR='".$data['ART_SNR']."', KUN_ID='".$data['KUN_ID']."', KUN_RID='".$data['KUN_RID']."', LIEF_ID='".$data['LIEF_ID']."', LIEF_RID='".$data['LIEF_RID']."', LIEF_RMA='".$data['LIEF_RMA']."', ERSTELLT='".$usr_name."', FEHLER='".$data['FEHLER']."', EIGEN_RMA='0', ERSTDAT=CURDATE(), ANZAHL=".$data['ANZAHL'], $db_id))
              {
                $data['ID'] = mysql_insert_id();
                mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$data['ID']."', '1', 'RMA erstellt.', CURDATE(), '".$usr_name."')", $db_id);
                $o_cont .= "<br><br><br><br><br><br><br><br>RMA erfolgreich erstellt!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
              }
            elseif($_POST[method]=="FRMA" && mysql_query("INSERT INTO ".$db_pref."RMA SET RMANUM='".$data['RMANUM']."', ART_ID='".$data['ART_ID']."', ART_SNR='".$data['ART_SNR']."', KUN_ID='".$data['KUN_ID']."', LIEF_ID='".$data['LIEF_ID']."', LIEF_RMA='".$data['LIEF_RMA']."', ERSTELLT='".$usr_name."', FEHLER='".$data['FEHLER']."', EIGEN_RMA='2', ERSTDAT=CURDATE(), ANZAHL=".$data['ANZAHL'], $db_id))
              {
                $data['ID'] = mysql_insert_id();
                mysql_query("INSERT INTO ".$db_pref."RMA_STATUS (RMA_ID, STATUS, KOMMENTAR, DATUM, ERSTELLT) VALUES ('".$data['ID']."', '1', 'RMA erstellt.', CURDATE(), '".$usr_name."')", $db_id);
                $o_cont .= "<br><br><br><br><br><br><br><br>RMA erfolgreich erstellt!<br><a href=\"main.php?section=".$_GET['section']."&module=rma&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
              }
            else
              {
                $o_cont .= "<br><br><br><br><br><br><br><br>FEHLER: Eintrag in Datenbank fehlgeschlagen!<br><a href=\"javascript:history.back()\">Zur&uuml;ck</a><br><br><br><br><br><br><br><br>";
              }
          }
        else
          {
             // $error ausgeben, weiterleiten

            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aufgetretene Fehler:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">";
            $o_cont .= $error;
            $o_cont .= "</td></tr></table>";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Korrektur:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?module=rma&action=create\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"method\" value=\"".$_POST['method']."\">
                         <input type=\"hidden\" name=\"ART_ID\" value=\"".$data['ART_ID']."\">
                         <input type=\"hidden\" name=\"ART_SNR\" value=\"".$data['ART_SNR']."\">
                         <input type=\"hidden\" name=\"KUN_ID\" value=\"".$data['KUN_ID']."\">
                         <input type=\"hidden\" name=\"KUN_RID\" value=\"".$data['KUN_RID']."\">
                         <input type=\"hidden\" name=\"LIEF_ID\" value=\"".$data['LIEF_ID']."\">
                         <input type=\"hidden\" name=\"LIEF_RID\" value=\"".$data['LIEF_RID']."\">
                         <input type=\"hidden\" name=\"LIEF_RMA\" value=\"".$data['LIEF_RMA']."\">
                         <input type=\"hidden\" name=\"FEHLER\" value=\"".$data['FEHLER']."\">
                         <input type=\"hidden\" name=\"ANZAHL\" value=\"".$data['ANZAHL']."\">
                         <input type=\"hidden\" name=\"JOURNALPOS_ID\" value=\"".$_POST['JOURNALPOS_ID']."\">
                         <div align=\"center\"><input type=\"submit\" name=\"create\" value=\"Weiter\">
                        </form>
                        </td></tr></table>";
            $o_cont .= "<br><br><br><br><br><br><br><br>";
            $o_cont .= "</td></tr></table>";

          }
      }
    else
      {
        $o_cont = " ";
      }
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>