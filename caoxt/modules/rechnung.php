<?php

$o_head = "Rechnung bearbeiten ...";
$o_navi = "";

if (!function_exists("str_split"))			// Abwärtskompatibilität zu PHP4
  {
    function str_split($str, $nr)
      {
         return array_slice(split("-l-", chunk_split($str, $nr, '-l-')), 0, -1);
      }
  }

function print_navi($id, $section)
  {
    $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rechnung&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rechnung&action=all&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Allgemein&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rechnung&action=pos&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Positionen&nbsp;</a></td>
               <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rechnung&action=finalise&id=".$id."\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Fertigstellen&nbsp;</a></td>
               </tr></table>";

    return $o_navi;
  }

function format_date_db($date)
  {
    $ver1 = explode(".", $date);
    $ver2 = explode("-", $date);

    if((count($ver1)==3) && (strlen($ver1[2])==4))		// TT.MM.YYYY -> YYYY-MM-DD
      {
        $result = $ver1[2]."-".$ver1[1]."-".$ver1[0];
      }
    elseif((count($ver1)==3) && (strlen($ver1[2])==2))		// TT.MM.YY -> YYYY-MM-DD
      {
        $result = "20".$ver1[2]."-".$ver1[1]."-".$ver1[0];
      }
    elseif((count($ver2)==3) && (strlen($ver2[0])==4))		// YYYY-MM-DD -> YYYY-MM-DD
      {
        $result = $date;
      }
    elseif((count($ver2)==3) && (strlen($ver2[0])==2))		// YY-MM-DD -> YYYY-MM-DD
      {
        $result = "20".$ver2[0]."-".$ver2[1]."-".$ver2[2];
      }
    else							// ?)§uh2e89 -> 1899-12-30
      {
        $result = "1899-12-30";
      }

    return $result;
  }

function get_menge_akt($artikel_id, $db_id)
  {
    $res_id = mysql_query("SELECT MENGE_AKT, ARTIKELTYP FROM ARTIKEL WHERE REC_ID=".$artikel_id, $db_id);
    $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    return $data;
  }

function get_zahlart($db_id)
  {
    $res_id = mysql_query("SELECT NAME, REC_ID AS NUMMER FROM ZAHLUNGSARTEN WHERE AKTIV_FLAG='Y' ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    $data[0]['NAME'] = "";
    $data[0]['NUMMER'] = "";

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_liefart($db_id)
  {
    $res_id = mysql_query("SELECT NAME, VAL_INT AS NUMMER FROM REGISTRY WHERE MAINKEY='MAIN\\\\LIEFART' ORDER BY VAL_INT ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    $data[0]['NAME'] = "";
    $data[0]['NUMMER'] = "";

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_vertreter($db_id)
  {
    $res_id = mysql_query("SELECT VERTRETER_ID, NAME, VNAME FROM VERTRETER ORDER BY NAME", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
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

function brutto_flag($alt, $neu, $journal_id, $db_id)	// aktualisiert die Preise, wenn BRUTTO_FLAG geändert wurde
  {
    $res_id = mysql_query("SELECT REC_ID, STEUER_CODE, MENGE, EPREIS, BRUTTO_FLAG FROM JOURNALPOS WHERE JOURNAL_ID=".$journal_id, $db_id);
    $res_num = mysql_numrows($res_id);
    $posdata = array();
    for($i=0; $i<$res_num; $i++)
     {
       array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
     }
    mysql_free_result($res_id);

    $mwst = get_mwst($db_id);

    foreach($posdata as $row)
      {
        foreach($mwst as $rtemp)							// Mehrwertsteuersatz
          {
            if($rtemp['NAME']==$row['STEUER_CODE'])
              {
                $mwst_set = ($rtemp['VAL_DOUBLE'] + 100) / 100;
              }
          }

        if(($alt=="Y")&&($neu=="N")&&($row['BRUTTO_FLAG']=="Y"))			// Mehrwertsteuer abziehen
          {
            $row['GPREIS'] = $row['EPREIS'] / $mwst_set * $row['MENGE'];
            $row['EPREIS'] = $row['EPREIS'] / $mwst_set;
            $row['BRUTTO_FLAG'] = "N";
          }
        elseif(($alt=="N")&&($neu=="Y")&&($row['BRUTTO_FLAG']=="N"))			// Mehrwertsteuer aufrechnen
          {
            $row['GPREIS'] = $row['EPREIS'] * $mwst_set * $row['MENGE'];
            $row['EPREIS'] = $row['EPREIS'] * $mwst_set;
            $row['BRUTTO_FLAG'] = "Y";
          }

        if(!mysql_query("UPDATE JOURNALPOS SET EPREIS='".$row['EPREIS']."', GPREIS='".$row['GPREIS']."', BRUTTO_FLAG='".$row['BRUTTO_FLAG']."' WHERE REC_ID=".$row['REC_ID'], $db_id))
          {
            echo mysql_error($db_id)."<br>";
          }
      }
  }

function set_kunnum($addr_id, $kunnum, $db_id)
  {
    if(!$kunnum)							// Kundennummer & Konto zuweisen
      {
        $rec_id = mysql_query("SELECT VAL_INT2, VAL_CHAR FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='KUNNUM'", $db_id);
        $rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
        mysql_free_result($rec_id);

        $l_template = strlen($rec_tmp['VAL_CHAR']);
        $l_current = strlen($rec_tmp['VAL_INT2']);
        $l_diff = $l_template - $l_current;

        $kunnum = "";						// String mit führenden Nullen bauen

        while($l_diff)
          {
            $kunnum .= "0";
            $l_diff--;
          }

        $kunnum .= $rec_tmp['VAL_INT2'];			// String komplett, neue NEXT_KUNNUM in REGISTRY eintragen

        $rec_tmp['VAL_INT2']++;

        $query = "UPDATE REGISTRY SET VAL_INT2='".$rec_tmp['VAL_INT2']."' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='KUNNUM'";
        //echo $query."<br>";
        if(!mysql_query($query, $db_id))
          {
            echo mysql_error($db_id)."<br>";
          }

        // FiBu-Konto:

        $rec_id = mysql_query("SELECT VAL_INT2, VAL_CHAR FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='DEB-NUM'", $db_id);
        $rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
        mysql_free_result($rec_id);

        $l_template = strlen($rec_tmp['VAL_CHAR']);
        $l_current = strlen($rec_tmp['VAL_INT2']);
        $l_diff = $l_template - $l_current;

        $deb_num = "";						// String mit führenden Nullen bauen

        while($l_diff)
          {
            $deb_num .= "0";
            $l_diff--;
          }

        $deb_num .= $rec_tmp['VAL_INT2'];			// String komplett, neue NEXT_DEB_NUM in REGISTRY eintragen

        $rec_tmp['VAL_INT2']++;

        $query = "UPDATE REGISTRY SET VAL_INT2='".$rec_tmp['VAL_INT2']."' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='DEB-NUM'";
        //echo $query."<br>";
        if(!mysql_query($query, $db_id))
          {
            echo mysql_error($db_id)."<br>";
          }

        $query = "UPDATE ADRESSEN SET KUNNUM1='".$kunnum."', DEB_NUM='".$deb_num."', STATUS=1 WHERE REC_ID=".$addr_id;
        //echo $query."<br>";
        if(!mysql_query($query, $db_id))
          {
            echo mysql_error($db_id)."<br>";
          }
      }
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
            $maindata['BSUMME'] = round($maindata['BSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']),2);
            $maindata['MSUMME'] = round($maindata['BSUMME'] - $maindata['NSUMME'],2);

            $maindata['NSUMME_'.$row['STEUER_CODE']] = $maindata['NSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) / $mwst_set * $row['MENGE']);
            $maindata['BSUMME_'.$row['STEUER_CODE']] = round($maindata['BSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']),2);
            $maindata['MSUMME_'.$row['STEUER_CODE']] = round($maindata['BSUMME_'.$row['STEUER_CODE']] - $maindata['NSUMME_'.$row['STEUER_CODE']],2);

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
            $maindata['BSUMME'] = round($maindata['BSUMME'] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $mwst_set * $row['MENGE']),2);
            $maindata['MSUMME'] = round($maindata['BSUMME'] - $maindata['NSUMME'],2);

            $maindata['NSUMME_'.$row['STEUER_CODE']] = $maindata['NSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $row['MENGE']);
            $maindata['BSUMME_'.$row['STEUER_CODE']] = round($maindata['BSUMME_'.$row['STEUER_CODE']] + (($row['EPREIS'] - ($row['EPREIS'] * $row['RABATT'] / 100)) * $mwst_set * $row['MENGE']),2);
            $maindata['MSUMME_'.$row['STEUER_CODE']] = round($maindata['BSUMME_'.$row['STEUER_CODE']] - $maindata['NSUMME_'.$row['STEUER_CODE']],2);

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

function set_position($journalpos_id, $position, $db_id)		// ändert die Position eines Artikels im Beleg
  {
    $res_id = mysql_query("SELECT JOURNAL_ID FROM JOURNALPOS WHERE REC_ID=".$journalpos_id, $db_id);
    $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT REC_ID, POSITION FROM JOURNALPOS WHERE JOURNAL_ID=".$maindata['JOURNAL_ID']." ORDER BY POSITION DESC", $db_id);
    $res_num = mysql_numrows($res_id);
    $posdata = array();
    for($i=0; $i<$res_num; $i++)
     {
       array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
     }
    mysql_free_result($res_id);

    $change = 0;

    foreach($posdata as $row)						// Prüfen, ob eine Veränderung da war
      {
        if($row['REC_ID']==$journalpos_id)
          {
            if($row['POSITION']!=$position)
              {
                $change = 1;						// Veränderung der Position gefunden
                $oldpos = $row['POSITION'];
              }
          }
      }

    if($change)								// Änderungswunsch, durchführen:
      {
        $new = array();
        $temp = array();

        $i = $res_num - 2;
        $j = $res_num - 1;
        $k = $res_num;

        $new[0]['POSITION'] = $position;				// Position der Wunschposition im Array
        $new[0]['REC_ID'] = $journalpos_id;

        while($j>=0)							// Array ohne Wunschdaten
          {
            if($posdata[$j]['REC_ID'] != $journalpos_id)
              {
                array_push($temp, $posdata[$j]);
              }
            $j--;
          }

        while($i>=0)							// Positionen festlegen
          {
            if($position!=$k)
              {
                $temp[$i]['POSITION'] = $k;
                $k--;
              }
            else							// Wunschposition überspringen, ist bereits fest
              {
                $k--;
                $temp[$i]['POSITION'] = $k;
                $k--;
              }
            $i--;
          }

        foreach($temp as $row)						// Arrays zusammenfügen
          {
            array_push($new, $row);
          }

        foreach($new as $row)
          {
            //echo $row['POSITION']." : ".$row['REC_ID']."<br>";
            mysql_query("UPDATE JOURNALPOS SET POSITION='".$row['POSITION']."' WHERE REC_ID=".$row['REC_ID'], $db_id);
          }
      }
  }

function reset_positions($journal_id, $db_id)				// Bei Löschung einer Position restliche Positionen ordnen
  {
    $res_id = mysql_query("SELECT REC_ID, POSITION FROM JOURNALPOS WHERE JOURNAL_ID=".$journal_id." ORDER BY POSITION DESC", $db_id);
    $res_num = mysql_numrows($res_id);
    $posdata = array();
    for($i=0; $i<$res_num; $i++)
     {
       array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
     }
    mysql_free_result($res_id);

    if($res_num)
      {
        $i = $res_num;

        foreach($posdata as $row)
          {
            $new[$i-1]['REC_ID'] = $row['REC_ID'];
            $new[$i-1]['POSITION'] = $i;

            $i--;
          }

        foreach($new as $row)
          {
            //echo $row['POSITION']." : ".$row['REC_ID']."<br>";
            mysql_query("UPDATE JOURNALPOS SET POSITION='".$row['POSITION']."' WHERE REC_ID=".$row['REC_ID'], $db_id);
          }
      }
  }


// HAUPTPROGRAMM

if($usr_rights)
  {
    if($_GET['action']=="all")
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=all&id=xxxxxxx

        if($_POST['ADDR_ID'])				// Kundennummer geändert, Kunde ändern!
          {
            $res_id = mysql_query("SELECT BRUTTO_FLAG FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $tempdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $res_id = mysql_query("SELECT KUNNUM1 FROM ADRESSEN WHERE REC_ID='".$_POST['ADDR_ID']."'", $db_id);
            $tkundata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            set_kunnum($_POST['ADDR_ID'], $tkundata['KUNNUM1'], $db_id);

            $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, ABTEILUNG, STRASSE, LAND, PLZ, ORT, NET_TAGE, NET_SKONTO, BRT_TAGE, PR_EBENE, KUN_LIEFART, KUN_ZAHLART, BRUTTO_FLAG, DEB_NUM FROM ADRESSEN WHERE REC_ID='".$_POST['ADDR_ID']."'", $db_id);
            $kundata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $query = "UPDATE JOURNAL SET
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
                       BRUTTO_FLAG='".$kundata['BRUTTO_FLAG']."',
                       GEGENKONTO='".$kundata['DEB_NUM']."',
                       ADDR_ID='".$_POST['ADDR_ID']."'
                      WHERE REC_ID=".$_GET['id'];

            if(!mysql_query($query, $db_id))
              {
                echo mysql_error($db_id)."<br>";
              }
             else
              {
                // Prüfe, ob BRUTTO_FLAG geändert wurde. Wenn ja, Preise in JOURNALPOS anpassen!
                brutto_flag($tempdata['BRUTTO_FLAG'], $kundata['BRUTTO_FLAG'], $_GET['id'], $db_id);
              }
          }

        if($_POST['MAINDATA'])								// Stammdaten ändern!
          {
            $res_id = mysql_query("SELECT BRUTTO_FLAG FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $tempdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $_POST['PR_EBENE'] = str_replace("VK", "", $_POST['PR_EBENE_TXT']);		// Preisgruppe holen

            $_POST['SOLL_SKONTO'] = str_replace(",", ".", $_POST['SOLL_SKONTO']);	// Skonto formatieren
            $_POST['SOLL_SKONTO'] = str_replace("%", "", $_POST['SOLL_SKONTO']);

            $_POST['GLOBRABATT'] = str_replace(",", ".", $_POST['GLOBRABATT']);		// Rabatt formatieren
            $_POST['GLOBRABATT'] = str_replace("%", "", $_POST['GLOBRABATT']);

            $_POST['TERMIN'] = format_date_db($_POST['TERMIN']);			// Datumsformatierung
            $_POST['BEST_DATUM'] = format_date_db($_POST['BEST_DATUM']);

            $vi_temp1 = explode("[", $data['VERTRETER_ID_TXT']);			// Herausschälen der ID
            $vi_temp2 = explode("]", $vi_temp1[1]);

            $vertreter = get_vertreter($db_id);						// ID des Vertreters holen
            foreach($vertreter as $set)
              {
                if($vi_temp2[0]==$set['VERTRETER_ID'])
                  {
                    $_POST['VERTRETER_ID'] = $set['VERTRETER_ID'];
                  }
              }

            $zahlart = get_zahlart($db_id);						// ID der Zahlart holen
            foreach($zahlart as $set)
              {
                if($set['NAME']==$_POST['ZAHLART_TXT'])
                  {
                    $_POST['ZAHLART'] = $set['NUMMER'];
                  }
              }

            $liefart = get_liefart($db_id);						// ID der Versandart holen
            foreach($liefart as $set)
              {
                if($set['NAME']==$_POST['LIEFART_TXT'])
                  {
                    $_POST['LIEFART'] = $set['NUMMER'];
                  }
              }

            if($_POST['BRUTTO_TXT']=="brutto")
              {
                $_POST['BRUTTO_FLAG'] = "Y";
              }
            else
              {
                $_POST['BRUTTO_FLAG'] = "N";
              }

            if(!$_POST['VERTRETER_ID'])
              {
                $_POST['VERTRETER_ID'] = 0;
              }

            if(!$_POST['LIEF_ADDR_ID'])
              {
                $_POST['LIEF_ADDR_ID'] = -1;
              }

            $query = "UPDATE JOURNAL SET
                       VERTRETER_ID='".$_POST['VERTRETER_ID']."',
                       GLOBRABATT='".$_POST['GLOBRABATT']."',
                       RDATUM=CURDATE(),
                       TERMIN='".$_POST['TERMIN']."',
                       PR_EBENE='".$_POST['PR_EBENE']."',
                       LIEFART='".$_POST['LIEFART']."',
                       ZAHLART='".$_POST['ZAHLART']."',
                       USR1='".addslashes($_POST['USR1'])."',
                       USR2='".addslashes($_POST['USR2'])."',
                       PROJEKT='".addslashes($_POST['PROJEKT'])."',
                       ORGNUM='".addslashes($_POST['ORGNUM'])."',
                       BEST_NAME='".addslashes($_POST['BEST_NAME'])."',
                       BEST_DATUM='".$_POST['BEST_DATUM']."',
                       INFO='".addslashes($_POST['INFO'])."',
                       SOLL_STAGE='".$_POST['SOLL_STAGE']."',
                       SOLL_SKONTO='".$_POST['SOLL_SKONTO']."',
                       SOLL_NTAGE='".$_POST['SOLL_NTAGE']."',
                       BRUTTO_FLAG='".$_POST['BRUTTO_FLAG']."',
                       LIEF_ADDR_ID='".$_POST['LIEF_ADDR_ID']."'
                      WHERE REC_ID=".$_GET['id'];

           //echo $query."<br>";

            if(!mysql_query($query, $db_id))
              {
                echo mysql_error($db_id)."<br>";
              }
            else
              {
                // Prüfe, ob BRUTTO_FLAG geändert wurde. Wenn ja, Preise in JOURNALPOS anpassen!
                brutto_flag($tempdata['BRUTTO_FLAG'], $_POST['BRUTTO_FLAG'], $_GET['id'], $db_id);
              }
          }

        if($_GET['id']=="new")						// Neuer Kunde
          {
            // Mehrwertsteuersätze holen

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

            $query = "INSERT INTO JOURNAL SET
                       VRENUM='".$maindata['VRENUM']."',
                       LIEFART='".$maindata['LIEFART']."',
                       ZAHLART='".$maindata['ZAHLART']."',
                       VERTRETER_ID='".$maindata['VERTRETER_ID']."',
                       ADDR_ID='".$maindata['ADDR_ID']."',
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
                       PR_EBENE='".$maindata['PR_EBENE']."',
                       QUELLE='13'";

            //echo $query."<br>";

            if(!mysql_query($query, $db_id))
              {
                echo mysql_error($db_id)."<br>";
              }
            else
              {
                $_GET['id'] = mysql_insert_id($db_id);			// Von nun an bitte mit einer REC_ID statt "new"
              }
          }
        else								// Bekannter Kunde
          {
            // Hauptdatensatz zusammenstellen:

            $res_id = mysql_query("SELECT * FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            // Relevanten Kundendaten:

            $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, TELE1, TELE2, FAX, FUNK, LAND, PLZ, ORT FROM ADRESSEN WHERE REC_ID=".$maindata['ADDR_ID'], $db_id);
            $addrdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);
          }

        // Lieferanschrift

        if($maindata['LIEF_ADDR_ID'])
          {
            $res_id = mysql_query("SELECT ANREDE, NAME1, NAME2, NAME3, STRASSE, LAND, PLZ, ORT FROM ADRESSEN_LIEF WHERE REC_ID=".$maindata['LIEF_ADDR_ID'], $db_id);
            $liefdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);
          }
        else
          {
            $liefdata = array();
          }

        // Sonstige dynamische Daten:

        $zahlart = get_zahlart($db_id);
        $liefart = get_liefart($db_id);
        $vertreter = get_vertreter($db_id);

        if($maindata['BRUTTO_FLAG']=="Y")
          {
            $brutto_text = "<option>netto</option><option selected>brutto</option>";
          }
        else
          {
            $brutto_text = "<option selected>netto</option><option>brutto</option>";
          }

        // Datumsformatierung:

        if((!$maindata['BEST_DATUM']) || ($maindata['BEST_DATUM']=="1899-12-30"))
          {
            $maindata['BEST_DATUM'] = "";
          }
        else
          {
            $tmp = explode("-", $maindata['BEST_DATUM']);
            $maindata['BEST_DATUM'] = $tmp[2].".".$tmp[1].".".$tmp[0];
          }

        if((!$maindata['TERMIN']) || ($maindata['TERMIN']=="1899-12-30"))
          {
            $maindata['TERMIN'] = "";
          }
        else
          {
            $tmp = explode("-", $maindata['TERMIN']);
            $maindata['TERMIN'] = $tmp[2].".".$tmp[1].".".$tmp[0];
          }

	// Javascripte

        $o_cont =  "<script language=\"JavaScript1.1\">
                     <!--
                      s_sav_on = new Image(102,26);
                      s_sav_on.src = \"images/s_sav_on.gif\";
                      s_sav_off = new Image(102,26);
                      s_sav_off.src = \"images/s_sav_off.gif\";
                      s_new_on = new Image(97,26);
                      s_new_on.src = \"images/s_new_on.gif\";
                      s_new_off = new Image(97,26);
                      s_new_off.src = \"images/s_new_off.gif\";
                      s_del_on = new Image(102,26);
                      s_del_on.src = \"images/s_del_on.gif\";
                      s_del_off = new Image(102,26);
                      s_del_off.src = \"images/s_del_off.gif\";
                      y_delete_on = new Image(25,19);
                      y_delete_on.src = \"images/y_delete_on.gif\";
                      y_delete_off = new Image(25,19);
                      y_delete_off.src = \"images/y_delete_off.gif\";
                      y_search_on = new Image(25,19);
                      y_search_on.src = \"images/y_search_on.gif\";
                      y_search_off = new Image(25,19);
                      y_search_off.src = \"images/y_search_off.gif\";

                      function reset_kun_addr()
                      {
                       document.maindata.LIEF_ADDR_ID.value = -1;
                       document.maindata.submit();
                      }

                      function open_kun_addr()
                      {
                       window_kun_addr = window.open(\"windows/windows.php?module=liefaddr&target=".$maindata['ADDR_ID']."\", \"Adressbrowser\", \"width=640,height=300,left=50,top=50\");
                       window_kun_addr.focus();
                      }
                     //-->
                     </script>";

        // Erster Absatz

        $o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=".$_GET['id']."\" method=\"post\" name=\"TARGET\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\"><b>&nbsp;Kundendaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"2\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NUM\" style=\"width:40px;\" value=\"".$addrdata['KUNNUM1']."\"><button name=\"address\" onclick=\"open_kun_id(); return false\"><b>...</b></button></td><td>Kunde:</td><td colspan=\"3\" width=\"400\"><input type=\"text\" name=\"KUN_NAME\" style=\"width:400px;\" value=\"".$addrdata['ANREDE']." ".$addrdata['NAME1']." ".$addrdata['NAME2']." ".$addrdata['NAME3']."\" readonly></td><td>Telefon1:</td><td><input type=\"text\" name=\"KUN_TELE1\" style=\"width:100px;\" value=\"".$addrdata['TELE1']."\" readonly></td><td>Mobilfunk:</td><td><input type=\"text\" name=\"KUN_FUNK\" style=\"width:100px;\" value=\"".$addrdata['FUNK']."\" readonly></td></tr>";
        $o_cont .= "<tr><td>Intern-Nr.:</td><td><input type=\"text\" name=\"NUMMER\" style=\"width:72px;\" value=\"".$maindata['VRENUM']."\" readonly></td><td>Land/Plz/Ort:</td><td><input type=\"text\" name=\"KUN_LAND\" style=\"width:30px;\" value=\"".$addrdata['LAND']."\" readonly></td><td><input type=\"text\" name=\"KUN_PLZ\" style=\"width:60px;\" value=\"".$addrdata['PLZ']."\" readonly></td><td><input type=\"text\" name=\"KUN_ORT\" style=\"width:300px;\" value=\"".$addrdata['ORT']."\" readonly></td><td>Telefon2:</td><td><input type=\"text\" name=\"KUN_TELE2\" style=\"width:100px;\" value=\"".$addrdata['TELE2']."\" readonly></td><td>Fax:</td><td><input type=\"text\" name=\"KUN_FAX\" style=\"width:100px;\" value=\"".$addrdata['FAX']."\" readonly></td>";
        $o_cont .= "</tr></table></td></tr><input type=\"hidden\" name=\"ADDR_ID\" value=\"".$maindata['ADDR_ID']."\"></form>";

        // Bestelldaten / Texte

        $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=".$_GET['id']."\" method=\"post\" name=\"maindata\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"35%\"><b>&nbsp;Bestelldaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"65%\"><b>&nbsp;Texte</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Bestellt durch:</td><td align=\"right\"><input type=\"text\" name=\"BEST_NAME\" style=\"width:195px;\" value=\"".htmlspecialchars($maindata['BEST_NAME'])."\"></td><td width=\"20\">&nbsp;</td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Bestelldatum:</td><td align=\"right\"><input type=\"text\" name=\"BEST_DATUM\" style=\"width:195px;\" value=\"".htmlspecialchars($maindata['BEST_DATUM'])."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Referenznr.:</td><td align=\"right\"><input type=\"text\" name=\"ORGNUM\" style=\"width:195px;\" value=\"".htmlspecialchars($maindata['ORGNUM'])."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Termin:</td><td align=\"right\"><input type=\"text\" name=\"TERMIN\" style=\"width:195px;\" value=\"".htmlspecialchars($maindata['TERMIN'])."\"></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td>";
        $o_cont .= "<td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"600\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Projekt:</td><td align=\"right\"><input type=\"text\" name=\"PROJEKT\" style=\"width:490px;\" value=\"".htmlspecialchars($maindata['PROJEKT'])."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">&Uuml;berschrift 1:</td><td align=\"right\"><input type=\"text\" name=\"USR1\" style=\"width:490px;\" value=\"".htmlspecialchars($maindata['USR1'])."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">&Uuml;berschrift 2:</td><td align=\"right\"><input type=\"text\" name=\"USR2\" style=\"width:490px;\" value=\"".htmlspecialchars($maindata['USR2'])."\"></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr>";

        // Zuweisungen / Lieferanschrift

        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Zuweisungen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Lieferanschrift</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Versand:</td><td align=\"left\"><select name=\"LIEFART_TXT\" size=\"1\" style=\"width:215px;\">";
        foreach($liefart as $row)
          {
            if($maindata['LIEFART']==$row['NUMMER'])
              {
                $o_cont .= "<option selected>".$row['NAME']."</option>";
              }
            else
              {
                $o_cont .= "<option>".$row['NAME']."</option>";
              }
          }
        $o_cont .= "</select></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Vertreter:</td><td align=\"left\"><select name=\"VERTRETER_TXT\" size=\"1\" style=\"width:215px;\"><option></option>";
        if($vertreter)
          {
            foreach($vertreter as $row)
              {
                if($maindata['VERTRETER_ID']==$row['VERTRETER_ID'])
                  {
                    $o_cont .= "<option selected>".$row['NAME'].", ".$row['VNAME']." [".$row['VERTRETER_ID']."]</option>";
                  }
                else
                  {
                    $o_cont .= "<option>".$row['NAME'].", ".$row['VNAME']." [".$row['VERTRETER_ID']."]</option>";
                  }
              }
          }
        $o_cont .= "</select></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Zahlart:</td><td align=\"left\"><select name=\"ZAHLART_TXT\" size=\"1\" style=\"width:215px;\">";
        foreach($zahlart as $row)
          {
            if($maindata['ZAHLART']==$row['NUMMER'])
              {
                $o_cont .= "<option selected>".$row['NAME']."</option>";
              }
            else
              {
                $o_cont .= "<option>".$row['NAME']."</option>";
              }
          }
        $o_cont .= "</select></td></tr>";
        $o_cont .= "<tr><td colspan=\"2\">&nbsp;</td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Zahlungsziel: </td><td align=\"left\"><input type=\"text\" name=\"SOLL_STAGE\" style=\"width:30px;\" value=\"".$maindata['SOLL_STAGE']."\"> Tage <input type=\"text\" name=\"SOLL_SKONTO\" style=\"width:40px;\" value=\"".number_format($maindata['SOLL_SKONTO'], 2, ',', '')." %\"> Skonto: <input type=\"text\" name=\"SOLL_NTAGE\" style=\"width:30px;\" value=\"".$maindata['SOLL_NTAGE']."\"> Tage Netto</td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Preisliste: </td><td align=\"left\"><select name=\"PR_EBENE_TXT\" size=\"1\">";
        for($i=1;$i<=5;$i++)
          {
            if($maindata['PR_EBENE']==$i)
              {
                $o_cont .= "<option selected>VK".$i."</option>";
              }
            else
              {
                $o_cont .= "<option>VK".$i."</option>";
              }
          }
        $o_cont .= "</select> Rabatt: <input type=\"text\" name=\"GLOBRABATT\" style=\"width:50px;\" value=\"".number_format($maindata['GLOBRABATT'], 2, ',', '')." %\"> N/B: <select name=\"BRUTTO_TXT\" size=\"1\">".$brutto_text."</select></td></tr>";
        $o_cont .= "</table></td>";
        $o_cont .= "<td bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"600\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Anrede:</td><td colspan=\"3\" align=\"right\"><table cellpadding=\"0\" cellspacing=\"0\"><tr><td><input type=\"text\" name=\"LIEF_ANREDE\" style=\"width:440px;\" value=\"".htmlspecialchars($liefdata['ANREDE'])."\" readonly></td><td width=\"25\"><a href=\"javascript:reset_kun_addr();\" onMouseOver=\"change('y_delete_', 'on')\"  onMouseOut=\"change('y_delete_', 'off')\"><img name=\"y_delete_\" src=\"images/y_delete_off.gif\" width=25 height=19 border=0 alt=\"\"></a></td><td width=\"25\"><a href=\"javascript:open_kun_addr();\"  onMouseOver=\"change('y_search_', 'on')\" onMouseOut=\"change('y_search_', 'off')\"><img name=\"y_search_\" src=\"images/y_search_off.gif\" width=25 height=19 border=0 alt=\"\"></a></td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name1:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"LIEF_NAME1\" style=\"width:490px;\" value=\"".htmlspecialchars($liefdata['NAME1'])."\" readonly></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name2:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"LIEF_NAME2\" style=\"width:490px;\" value=\"".htmlspecialchars($liefdata['NAME2'])."\" readonly></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name3:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"LIEF_NAME3\" style=\"width:490px;\" value=\"".htmlspecialchars($liefdata['NAME3'])."\" readonly></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Strasse:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"LIEF_STRASSE\" style=\"width:490px;\" value=\"".htmlspecialchars($liefdata['STRASSE'])."\" readonly></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Land/PLZ/Ort:</td><td align=\"right\"><input type=\"text\" name=\"LIEF_LAND\" style=\"width:20px;\" value=\"".htmlspecialchars($liefdata['LAND'])."\" readonly></td><td align=\"center\"><input type=\"text\" name=\"LIEF_PLZ\" style=\"width:50px;\" value=\"".htmlspecialchars($liefdata['PLZ'])."\" readonly></td><td align=\"right\"><input type=\"text\" name=\"LIEF_ORT\" style=\"width:405px;\" value=\"".htmlspecialchars($liefdata['ORT'])."\" readonly><input type=\"hidden\" name=\"LIEF_ADDR_ID\" value=\"".htmlspecialchars($maindata['LIEF_ADDR_ID'])."\"><input type=\"hidden\" name=\"MAINDATA\" value=\"1\"></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr>";

        // Info

        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\"><b>&nbsp;Info</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"top\">";
        $o_cont .= "<table width=\"100%\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"right\"><textarea name=\"INFO\" style=\"width: 100%;\" rows=\"7\">".htmlspecialchars($maindata['INFO'])."</textarea></td></tr>";
        $o_cont .= "</table>";
        $o_cont .= "</td></tr>";
        $o_cont .= "</form>";

        // Statistik

        if($_SESSION['hidden'] != "TRUE")
          {
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"2\" valign=\"middle\" align=\"center\"><b><br>Rohgewinn: ".number_format($maindata['ROHGEWINN'], 2, ',', '')." &euro;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Netto: ".number_format($maindata['NSUMME'], 2, ',', '')." &euro;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;MwSt.: ".number_format($maindata['MSUMME'], 2, ',', '')." &euro;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Brutto: ".number_format($maindata['BSUMME'], 2, ',', '')." &euro;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Gewicht: ".number_format($maindata['GEWICHT'], 2, ',', '')." &euro;</b><br><br></td></tr>";
          }

        $o_cont .= "<tr><td colspan=\"2\">";

        $o_cont .=  "<table width=\"100%\" cellpadding=\"6\" cellspacing=\"0\"><tr>
                      <td width=\"33%\" align=\"center\" valign=\"middle\" bgcolor=\"#d4d0c8\">
                       <a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=new\" onMouseOver=\"change('s_new_', 'on')\"  onMouseOut=\"change('s_new_', 'off')\"><img name=\"s_new_\" src=\"images/s_new_off.gif\" width=97 height=26 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"34%\" align=\"center\" valign=\"middle\" bgcolor=\"#d4d0c8\">
                       <a href=\"javascript:document.maindata.submit()\" onMouseOver=\"change('s_sav_', 'on')\"  onMouseOut=\"change('s_sav_', 'off')\"><img name=\"s_sav_\" src=\"images/s_sav_off.gif\" width=102 height=26 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"33%\" align=\"center\" valign=\"middle\" bgcolor=\"#d4d0c8\">
                       <a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=delete&id=".$_GET['id']."\" onMouseOver=\"change('s_del_', 'on')\"  onMouseOut=\"change('s_del_', 'off')\"><img name=\"s_del_\" src=\"images/s_del_off.gif\" width=102 height=26 border=0 alt=\"\"></a>
                      </td>
                     </tr></table>";

        $o_cont .= "</td></tr></table>";


        $o_navi = print_navi($_GET['id'], $_GET['section']);
      }
    elseif($_GET['action']=="pos")
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=xxxxxxx

        if($_GET['option']=="hide")
          {
            $_SESSION['hidden'] = "TRUE";
          }
        elseif($_GET['option']=="show")
          {
            $_SESSION['hidden'] = "FALSE";
          }

        $mwst = get_mwst($db_id);

        // Hauptdatensatz zusammenstellen:

        $res_id = mysql_query("SELECT VRENUM, ADDR_ID, BRUTTO_FLAG, GLOBRABATT FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
        $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        if($_GET['do']=="delete")		// Position löschen
          {
            $res_id = mysql_query("SELECT JOURNAL_ID, QUELLE FROM JOURNALPOS WHERE REC_ID=".$_GET['pos'], $db_id);
            $temp = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            if(($temp['JOURNAL_ID']==$_GET['id'])&&($temp['QUELLE']=="13"))	// Sicherheitsabfragen gegen Unfug
              {
                if(!mysql_query("DELETE FROM JOURNALPOS WHERE REC_ID=".$_GET['pos'], $db_id))
                  {
                    echo mysql_error($db_id)."<br>";
                  }
                else
                  {
                    // Zugewiesene Seriennummern löschen
                    mysql_query("DELETE FROM JOURNALPOS_SERNUM WHERE JOURNALPOS_ID=".$_GET['pos'], $db_id);

                    // Journalaktualisierung & Positions-Reihenfolge
                    set_journal($_GET['id'], $db_id);
                    reset_positions($_GET['id'], $db_id);
                  }
              }
          }

        if($_POST['REC_ID'])		// Artikel wurde geändert, verarbeiten:
          {
            $_POST['MENGE'] = str_replace(",", ".", $_POST['MENGE']);			// In DB-kompatible Werte formatieren
            $_POST['EPREIS'] = str_replace(",", ".", $_POST['EPREIS']);
            $_POST['EPREIS'] = str_replace("€", "", $_POST['EPREIS']);
            $_POST['RABATT'] = str_replace(",", ".", $_POST['RABATT']);
            $_POST['RABATT'] = str_replace("%", "", $_POST['RABATT']);
            $_POST['GEWICHT'] = str_replace(",", ".", $_POST['GEWICHT']);

            $_POST['GPREIS'] = ($_POST['EPREIS'] - ($_POST['EPREIS'] / 100 * $_POST['RABATT'])) * $_POST['MENGE'];

            foreach($mwst as $row)							// Mehrwertsteuersatz
              {
                if($row['NAME']==$_POST['STEUER_CODE'])
                  {
                    $mwst_set = ($row['VAL_DOUBLE'] + 100) / 100;
                  }
              }

            if($maindata['BRUTTO_FLAG']=='Y')
              {
                $_POST['E_RGEWINN'] = ($_POST['EPREIS'] / $mwst_set) - $_POST['EK_PREIS'];							// Rohgewinn
                $_POST['NSUMME'] = $_POST['EPREIS'] / $mwst_set * $_POST['MENGE'];								// Nettosumme
              }
            else
              {
                $_POST['E_RGEWINN'] = $_POST['EPREIS'] - $_POST['EK_PREIS'];									// Rohgewinn
                $_POST['NSUMME'] = $_POST['EPREIS'] * $_POST['MENGE'];										// Nettosumme
              }

            $_POST['G_RGEWINN'] = ($_POST['E_RGEWINN'] - ($_POST['EPREIS'] / 100 * $_POST['RABATT'])) * $_POST['MENGE'];			// Ges. Rohgewinn - Rabatt

            $query = "UPDATE JOURNALPOS SET
                        MENGE='".$_POST['MENGE']."',
                        ME_EINHEIT='".addslashes($_POST['ME_EINHEIT'])."',
                        EPREIS='".$_POST['EPREIS']."',
                        RABATT='".$_POST['RABATT']."',
                        GPREIS='".$_POST['GPREIS']."',
                        E_RGEWINN='".$_POST['E_RGEWINN']."',
                        G_RGEWINN='".$_POST['G_RGEWINN']."',
                        STEUER_CODE='".$_POST['STEUER_CODE']."',
                        GEWICHT='".$_POST['GEWICHT']."',
                        BEZEICHNUNG='".addslashes($_POST['BEZEICHNUNG'])."'
                        WHERE REC_ID=".$_POST['REC_ID'];

            //echo $query."<br><br>";

            if(!mysql_query($query, $db_id))
              {
                echo mysql_error($db_id)."<br>";
              }
            else
              {
                // Journalaktualisierung & Positions-Reihenfolge
                set_journal($_GET['id'], $db_id);
                set_position($_POST['REC_ID'], $_POST['POSITION'], $db_id);
              }
          }

        if($_POST['ARTIKEL_ID'])		// Ein neuer Artikel wurde übergeben, verarbeiten:
          {
            $res_id = mysql_query("SELECT A.*, ME.BEZEICHNUNG AS ME_EINHEIT FROM ARTIKEL AS A, MENGENEINHEIT AS ME WHERE A.REC_ID=".$_POST['ARTIKEL_ID']." AND A.ME_ID = ME.REC_ID", $db_id);
            $artdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $res_id = mysql_query("SELECT POSITION FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET['id']." ORDER BY POSITION DESC LIMIT 1", $db_id);
            $temp1 = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $artdata['POSITION'] = $temp1['POSITION'] + 1;

            $res_id = mysql_query("SELECT PR_EBENE FROM ADRESSEN WHERE REC_ID=".$maindata['ADDR_ID'], $db_id);
            $temp2 = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            if($maindata['BRUTTO_FLAG']=='Y')
              {
                $VK = "VK".$temp2['PR_EBENE']."B";
              }
            else
              {
                $VK = "VK".$temp2['PR_EBENE'];
              }

            $faktor = (100 - $maindata['GLOBRABATT']) / 100;				// Rabatt einrechnen

            $artdata['E_RGEWINN'] = ($artdata["VK".$temp2['PR_EBENE']]) - $artdata['EK_PREIS'];
            $artdata['G_RGEWINN'] = ($artdata["VK".$temp2['PR_EBENE']] * $faktor) - $artdata['EK_PREIS'];
            $artdata['EPREIS'] = $artdata[$VK];
            $artdata['GPREIS'] = $artdata['EPREIS'] * $faktor;
			$artdata['FAKTOR'] = $artdata['EPREIS'] / $artdata['EK_PREIS']; 

            $query = "INSERT INTO JOURNALPOS SET
                        QUELLE='13',
                        JOURNAL_ID='".$_GET['id']."',
						WARENGRUPPE='".$artdata['WARENGRUPPE']."',
                        ARTIKELTYP='".$artdata['ARTIKELTYP']."',
                        ARTIKEL_ID='".$artdata['REC_ID']."',
                        ADDR_ID='".$maindata['ADDR_ID']."',
                        VRENUM='".$maindata['VRENUM']."',
                        POSITION='".$artdata['POSITION']."',
                        MATCHCODE='".strtoupper($artdata['MATCHCODE'])."',
                        ARTNUM='".$artdata['ARTNUM']."',
                        BARCODE='".$artdata['BARCODE']."',
                        MENGE='1',
                        LAENGE='".$artdata['LAENGE']."',
                        BREITE='".$artdata['BREITE']."',
                        HOEHE='".$artdata['HOEHE']."',
                        GROESSE='".$artdata['GROESSE']."',
                        DIMENSION='".$artdata['DIMENSION']."',
                        GEWICHT='".$artdata['GEWICHT']."',
                        ME_EINHEIT='".$artdata['ME_EINHEIT']."',
                        PR_EINHEIT='".$artdata['PR_EINHEIT']."',
                        VPE='".$artdata['VPE']."',
                        EK_PREIS='".$artdata['EK_PREIS']."',
						CALC_FAKTOR='".$artdata['FAKTOR']."',
                        EPREIS='".$artdata['EPREIS']."',
                        GPREIS='".$artdata['GPREIS']."',
                        E_RGEWINN='".$artdata['E_RGEWINN']."',
                        G_RGEWINN='".$artdata['G_RGEWINN']."',
                        RABATT='".$maindata['GLOBRABATT']."',
                        STEUER_CODE='".$artdata['STEUER_CODE']."',
                        GEGENKTO='".$artdata['ERLOES_KTO']."',
                        BEZEICHNUNG='".$artdata['LANGNAME']."',
                        SN_FLAG='".$artdata['SN_FLAG']."',
                        BRUTTO_FLAG='".$maindata['BRUTTO_FLAG']."'";

            //echo $query."<br><br>";

            if(!mysql_query($query, $db_id))
              {
                echo mysql_error($db_id)."<br>";
              }
            else
              {
                // Journalaktualisierung
                set_journal($_GET['id'], $db_id);
              }
          }

        // Daten für die Ausgabe sammeln

        if($_SESSION['hidden']!="TRUE")
          {
            $res_id = mysql_query("SELECT NSUMME, MSUMME, BSUMME, ROHGEWINN FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $hiddendata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            if($hiddendata['NSUMME']!=0)
              {
                $hiddendata['MARGE'] = ($hiddendata['ROHGEWINN'] * 100) / $hiddendata['NSUMME'];
              }
            else
              {
                $hiddendata['MARGE'] = 0;
              }
          }

        $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, TELE1, TELE2, FAX, FUNK, LAND, PLZ, ORT FROM ADRESSEN WHERE REC_ID=".$maindata['ADDR_ID'], $db_id);
        $addrdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        $res_id = mysql_query("SELECT REC_ID, POSITION, ARTIKEL_ID, ARTIKELTYP, ARTNUM, BEZEICHNUNG, MENGE, ME_EINHEIT, EK_PREIS, EPREIS, GPREIS, RABATT, E_RGEWINN, G_RGEWINN, STEUER_CODE, GEWICHT, SN_FLAG FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
        $posdata = array();
        $number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
        for($j=0; $j<$number; $j++)
          {
            array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);

        // Grunddaten gesammelt, Ausgabe:

        if($maindata['BRUTTO_FLAG']=='Y')
          {
            $o_head = "Rechnung bearbeiten ... (BRUTTO)";
          }
        else
          {
            $o_head = "Rechnung bearbeiten ...";
          }

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Kundendaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NUM\" style=\"width:60px;\" value=\"".$addrdata['KUNNUM1']."\" readonly></td><td>Kunde:</td><td colspan=\"3\" width=\"400\"><input type=\"text\" name=\"KUN_NAME\" style=\"width:400px;\" value=\"".$addrdata['ANREDE']." ".$addrdata['NAME1']." ".$addrdata['NAME2']." ".$addrdata['NAME3']."\" readonly></td><td>Telefon1:</td><td><input type=\"text\" name=\"KUN_TELE1\" style=\"width:100px;\" value=\"".$addrdata['TELE1']."\" readonly></td><td>Mobilfunk:</td><td><input type=\"text\" name=\"KUN_FUNK\" style=\"width:100px;\" value=\"".$addrdata['FUNK']."\" readonly></td></tr>";
        $o_cont .= "<tr><td>Intern-Nr.:</td><td><input type=\"text\" name=\"NUMMER\" style=\"width:60px;\" value=\"".$maindata['VRENUM']."\" readonly></td><td>Land/Plz/Ort:</td><td><input type=\"text\" name=\"KUN_LAND\" style=\"width:30px;\" value=\"".$addrdata['LAND']."\" readonly></td><td><input type=\"text\" name=\"KUN_PLZ\" style=\"width:60px;\" value=\"".$addrdata['PLZ']."\" readonly></td><td><input type=\"text\" name=\"KUN_ORT\" style=\"width:300px;\" value=\"".$addrdata['ORT']."\" readonly></td><td>Telefon2:</td><td><input type=\"text\" name=\"KUN_TELE2\" style=\"width:100px;\" value=\"".$addrdata['TELE2']."\" readonly></td><td>Fax:</td><td><input type=\"text\" name=\"KUN_FAX\" style=\"width:100px;\" value=\"".$addrdata['FAX']."\" readonly></td>";
        $o_cont .= "</tr></table></td></tr>";
        if($_SESSION['hidden']=="TRUE")
          {
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"15\" valign=\"middle\"><b>&nbsp;Kalkulation</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\" align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&option=show&id=".$_GET['id']."\"><image src=\"images/checkbox_off.gif\" border=\"0\"></a></td></tr>";
          }
        else
          {
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"15\" valign=\"middle\"><b>&nbsp;Kalkulation</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\" align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&option=hide&id=".$_GET['id']."\"><image src=\"images/checkbox_on.gif\" border=\"0\"></a></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" align=\"center\">";
            $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
            $o_cont .= "<td>Netto:</td><td><input type=\"text\" name=\"NSUMME\" style=\"width:100px;\" value=\"".number_format($hiddendata['NSUMME'], 2, ',', '')." €\" readonly></td><td>MwSt.:</td><td><input type=\"text\" name=\"MSUMME\" style=\"width:80px;\" value=\"".number_format($hiddendata['MSUMME'], 2, ',', '')." €\" readonly></td><td>Brutto:</td><td><input type=\"text\" name=\"BSUMME\" style=\"width:100px;\" value=\"".number_format($hiddendata['BSUMME'], 2, ',', '')." €\" readonly></td><td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td><td>Rohgewinn:</td><td><input type=\"text\" name=\"ROHGEWINN\" style=\"width:80px;\" value=\"".number_format($hiddendata['ROHGEWINN'], 2, ',', '')." €\" readonly></td><td>Marge:</td><td><input type=\"text\" name=\"MARGE\" style=\"width:80px;\" value=\"".number_format($hiddendata['MARGE'], 2, ',', '')." %\" readonly></td>";
            $o_cont .= "</tr></table></td></tr>";
          }
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Positionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td width=\"38\">&nbsp;Pos.</td><td width=\"16\">&nbsp;T</td><td>&nbsp;Artikelnummer</td><td>&nbsp;Artikelbezeichnung</td><td>&nbsp;Menge</td><td>&nbsp;M.-Einheit</td><td>&nbsp;E-Preis (Roh-G.)</td><td>&nbsp;Rabatt</td><td>&nbsp;G-Preis (Roh-G.)</td><td width=\"16\">&nbsp;S</td><td>&nbsp;MwSt</td><td>&nbsp;Gewicht(Kg)</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>";

        for($j=0; $j<$number; $j++)
          {
            foreach($mwst as $row)							// Mehrwertsteuersatz
              {
                if($row['NAME']==$posdata[$j]['STEUER_CODE'])
                  {
                    $mwst_total = $row['VAL_DOUBLE'];
                  }
              }

            for($k=1;$k<=$number;$k++)							// Position ändern? -> <select>
              {
                if($k==$posdata[$j]['POSITION'])
                  {
                    $posdata[$j]['POS'] .= "<option selected>".$k."</option>";
                  }
                else
                  {
                    $posdata[$j]['POS'] .= "<option>".$k."</option>";
                  }
              }

            $m_data = get_menge_akt($posdata[$j]['ARTIKEL_ID'], $db_id);

            if(($posdata[$j]['MENGE']>$m_data['MENGE_AKT'])&&($m_data['ARTIKELTYP']=="N"))// Menge rot einblenden?
              {
                $m_style = "color:#ff0000;";
              }
            else
              {
                $m_style = "color:#000000;";
              }

            if($posdata[$j]['G_RGEWINN']<=0)						// Preis rot einblenden?
              {
                $p_style = "color:#ff0000;";
              }
            else
              {
                $p_style = "color:#000000;";
              }

            if($_SESSION['hidden']=="TRUE")
              {
                $epreis = "<input type=\"text\" name=\"EPREIS\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['EPREIS'], 2, ',', '.')." &euro;\">";
                $gpreis = "<input type=\"text\" name=\"GPREIS\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['GPREIS'], 2, ',', '.')." &euro;\" readonly>";
              }
            else
              {
                $epreis = "<input type=\"text\" name=\"EPREIS\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['EPREIS'], 2, ',', '.')." &euro;\"><br><br><input type=\"text\" name=\"E_RGEWINN\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['E_RGEWINN'], 2, ',', '.')." &euro;\" readonly>";
                $gpreis = "<input type=\"text\" name=\"GPREIS\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['GPREIS'], 2, ',', '.')." &euro;\" readonly><br><br><input type=\"text\" name=\"G_RGEWINN\" style=\"width:60px; ".$p_style."\" value=\"".number_format($posdata[$j]['G_RGEWINN'], 2, ',', '.')." &euro;\" readonly>";
              }


            if($j%2)
              {
                $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$_GET['id']."\" method=\"post\" name=\"".$posdata[$j]['REC_ID']."\"><tr bgcolor=\"#ffffdd\" valign=\"top\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><select size=\"1\" name=\"POSITION\" style=\"width:38px;\">".$posdata[$j]['POS']."\"</select></td><td><input type=\"text\" name=\"ARTIKELTYP\" style=\"width:16px;\" value=\"".$posdata[$j]['ARTIKELTYP']."\" readonly></td><td><input type=\"text\" name=\"ARTNUM\" style=\"width:60px;\" value=\"".$posdata[$j]['ARTNUM']."\" readonly></td><td><textarea name=\"BEZEICHNUNG\" cols=\"50\" rows=\"4\">".$posdata[$j]['BEZEICHNUNG']."</textarea></td><td><input type=\"text\" name=\"MENGE\" style=\"width:40px; ".$m_style."\" value=\"".number_format($posdata[$j]['MENGE'], 2, ',', '')."\"></td><td><input type=\"text\" name=\"ME_EINHEIT\" style=\"width:60px;\" value=\"".$posdata[$j]['ME_EINHEIT']."\"></td><td>".$epreis."</td><td><input type=\"text\" name=\"RABATT\" style=\"width:40px;\" value=\"".number_format($posdata[$j]['RABATT'], 2, ',', '')." %\"></td><td>".$gpreis."</td><td><input type=\"text\" name=\"STEUER_CODE\" style=\"width:16px;\" value=\"".$posdata[$j]['STEUER_CODE']."\"></td><td><input type=\"text\" name=\"MWST\" style=\"width:40px;\" value=\"".$mwst_total." %\" readonly></td><td><input type=\"text\" name=\"GEWICHT\" style=\"width:40px;\" value=\"".number_format($posdata[$j]['GEWICHT'], 2, ',', '')."\"></td><td width=\"16\"><input type=\"submit\" name=\"SUBMIT\" value=\"&Auml;ndern\"></td><td width=\"16\"><button name=\"delete\" type=\"button\" value=\"L&ouml;schen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=rechnung&action=pos&do=delete&pos=".$posdata[$j]['REC_ID']."&id=".$_GET['id']."'\">L&ouml;schen</button></td><td width=\"16\">";
                if($posdata[$j]['SN_FLAG']=='Y')
                  {
                    $o_cont .= "<button name=\"snum\" type=\"button\" value=\"S/N\" onClick=\"open_snum('".$posdata[$j]['REC_ID']."')\">S/N</button>";
                  }
                $o_cont .= "</td></tr><input type=\"hidden\" name=\"REC_ID\" value=\"".$posdata[$j]['REC_ID']."\"><input type=\"hidden\" name=\"EK_PREIS\" value=\"".$posdata[$j]['EK_PREIS']."\"></form>";
              }
            else
              {
                $o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$_GET['id']."\" method=\"post\" name=\"".$posdata[$j]['REC_ID']."\"><tr bgcolor=\"#ffffff\" valign=\"top\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><select size=\"1\" name=\"POSITION\" style=\"width:38px;\">".$posdata[$j]['POS']."\"</select></td><td><input type=\"text\" name=\"ARTIKELTYP\" style=\"width:16px;\" value=\"".$posdata[$j]['ARTIKELTYP']."\" readonly></td><td><input type=\"text\" name=\"ARTNUM\" style=\"width:60px;\" value=\"".$posdata[$j]['ARTNUM']."\" readonly></td><td><textarea name=\"BEZEICHNUNG\" cols=\"50\" rows=\"4\">".$posdata[$j]['BEZEICHNUNG']."</textarea></td><td><input type=\"text\" name=\"MENGE\" style=\"width:40px; ".$m_style."\" value=\"".number_format($posdata[$j]['MENGE'], 2, ',', '')."\"></td><td><input type=\"text\" name=\"ME_EINHEIT\" style=\"width:60px;\" value=\"".$posdata[$j]['ME_EINHEIT']."\"></td><td>".$epreis."</td><td><input type=\"text\" name=\"RABATT\" style=\"width:40px;\" value=\"".number_format($posdata[$j]['RABATT'], 2, ',', '')." %\"></td><td>".$gpreis."</td><td><input type=\"text\" name=\"STEUER_CODE\" style=\"width:16px;\" value=\"".$posdata[$j]['STEUER_CODE']."\"></td><td><input type=\"text\" name=\"MWST\" style=\"width:40px;\" value=\"".$mwst_total." %\" readonly></td><td><input type=\"text\" name=\"GEWICHT\" style=\"width:40px;\" value=\"".number_format($posdata[$j]['GEWICHT'], 2, ',', '')."\"></td><td width=\"16\"><input type=\"submit\" name=\"SUBMIT\" value=\"&Auml;ndern\"></td><td width=\"16\"><button name=\"delete\" type=\"button\" value=\"L&ouml;schen\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=rechnung&action=pos&do=delete&pos=".$posdata[$j]['REC_ID']."&id=".$_GET['id']."'\">L&ouml;schen</button></td><td width=\"16\">";
                if($posdata[$j]['SN_FLAG']=='Y')
                  {
                    $o_cont .= "<button name=\"sn\" type=\"button\" value=\"S/N\" onClick=\"open_snum('".$posdata[$j]['REC_ID']."')\">S/N</button>";
                  }
                $o_cont .= "</td></tr><input type=\"hidden\" name=\"REC_ID\" value=\"".$posdata[$j]['REC_ID']."\"><input type=\"hidden\" name=\"EK_PREIS\" value=\"".$posdata[$j]['EK_PREIS']."\"></form>";
              }
          }

        $o_cont .= "<tr bgcolor=\"#ffffff\"><td colspan=\"16\" align=\"center\"><br><br><button name=\"add_art\" onclick=\"open_artid(); return false\"><b>Artikel hinzuf&uuml;gen</b></button><br><br><br>
                    <form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$_GET['id']."\" method=\"post\" name=\"TARGET\"><input type=\"hidden\" name=\"ARTIKEL_ID\" value=\"\"></form>";

        $o_cont .= "</table>";

        $o_navi = print_navi($_GET['id'], $_GET['section']);
      }
    elseif(($_GET['action']=="delete") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=delete&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
        $o_cont .= "<br><br><br><br><br><br><br><br>Wollen Sie den Beleg wirklich l&ouml;schen?<br><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=delete&type=submit&id=".$_GET['id']."\">JA</a>&nbsp;&nbsp;&nbsp;&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=".$_GET['id']."\">NEIN</a><br><br><br><br><br><br><br><br>";
        $o_cont .= "</td></tr></table>";
      }
    elseif(($_GET['action']=="delete") && ($_GET['type']=="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=delete&type=submit&id=xxxxxxx

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        if(!mysql_query("DELETE FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id))
          {
            $o_cont .= "<br><br><br><br><br><br><br><br>FEHLER: ".mysql_error($db_id)."<br><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
          }
        else
          {
            // Positionen des Belegs ebenfalls löschen:
            mysql_query("DELETE FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET['id'], $db_id);
            mysql_query("DELETE FROM JOURNALPOS_SERNUM WHERE JOURNAL_ID=".$_GET['id'], $db_id);
            $o_cont .= "<br><br><br><br><br><br><br><br>Beleg erfolgreich gel&ouml;scht!<br><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=list\">Zur &Uuml;bersicht</a><br><br><br><br><br><br><br><br>";
          }

        $o_cont .= "</td></tr></table>";
      }
    elseif(($_GET['action']=="finalise") && ($_GET['type']!="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=finalize&id=xxxxxxx

        // Hauptdatensatz zusammenstellen:

        $res_id = mysql_query("SELECT * FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
        $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        // Daten für die Ausgabe sammeln:

        $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, TELE1, TELE2, FAX, FUNK, LAND, PLZ, ORT FROM ADRESSEN WHERE REC_ID=".$maindata['ADDR_ID'], $db_id);
        $addrdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        // Fehler finden, Seriennummer-Zuweisung:

        $error = "";
        $warning = "";
        $k=1;

        $res_id = mysql_query("SELECT MENGE, REC_ID, POSITION FROM JOURNALPOS WHERE SN_FLAG='Y' AND MENGE>0 AND JOURNAL_ID=".$_GET['id']." ORDER BY POSITION ASC", $db_id);
        $res_num = mysql_numrows($res_id);
        $result = array();

        for($i=0; $i<$res_num; $i++)
          {
            array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
          }
        mysql_free_result($res_id);

        $err_snum = array();
        foreach($result as $row)
          {
          	$tmp_id = mysql_query("SELECT ARTIKEL_ID FROM JOURNALPOS_SERNUM WHERE JOURNALPOS_ID=".$row['REC_ID'], $db_id);
          	$num_rows = mysql_num_rows($tmp_id);
          	mysql_free_result($tmp_id);

          	if($row['MENGE']!=$num_rows)
          	  {
          	  	array_push($err_snum, $row['POSITION']);
          	  }
          }

        if(count($err_snum))	// Fehlermeldung generieren
          {
          	$error .= "Bei Position ";

          	$last = array_pop($err_snum);
          	if(count($err_snum))
          	  {
              	foreach($err_snum as $position)
              	  {
              	  	$error .= $position.", ";
          	      }
          	  }
          	$error .= $last." ist die Anzahl der zugeteilten Seriennummern nicht korrekt!<br><br>";
          }

        // Fehler finden, Versandart und Zahlungsart:

        if($maindata['ZAHLART']<1)
          {
          	$error .= "Keine Zahlungsart zugewiesen!<br><br>";
          }
        if($maindata['LIEFART']<1)
          {
          	$error .= "Keine Lieferart zugewiesen!<br><br>";
          }


        // Grunddaten gesammelt, Ausgabe:

        $o_navi = print_navi($_GET['id'], $_GET['section']);

        if($maindata['BRUTTO_FLAG']=='Y')
          {
            $o_head = "Rechnung bearbeiten ... (BRUTTO)";
          }
        else
          {
            $o_head = "Rechnung bearbeiten ...";
          }

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Kundendaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NUM\" style=\"width:60px;\" value=\"".$addrdata['KUNNUM1']."\" readonly></td><td>Kunde:</td><td colspan=\"3\" width=\"400\"><input type=\"text\" name=\"KUN_NAME\" style=\"width:400px;\" value=\"".$addrdata['ANREDE']." ".$addrdata['NAME1']." ".$addrdata['NAME2']." ".$addrdata['NAME3']."\" readonly></td><td>Telefon1:</td><td><input type=\"text\" name=\"KUN_TELE1\" style=\"width:100px;\" value=\"".$addrdata['TELE1']."\" readonly></td><td>Mobilfunk:</td><td><input type=\"text\" name=\"KUN_FUNK\" style=\"width:100px;\" value=\"".$addrdata['FUNK']."\" readonly></td></tr>";
        $o_cont .= "<tr><td>Intern-Nr.:</td><td><input type=\"text\" name=\"NUMMER\" style=\"width:60px;\" value=\"".$maindata['VRENUM']."\" readonly></td><td>Land/Plz/Ort:</td><td><input type=\"text\" name=\"KUN_LAND\" style=\"width:30px;\" value=\"".$addrdata['LAND']."\" readonly></td><td><input type=\"text\" name=\"KUN_PLZ\" style=\"width:60px;\" value=\"".$addrdata['PLZ']."\" readonly></td><td><input type=\"text\" name=\"KUN_ORT\" style=\"width:300px;\" value=\"".$addrdata['ORT']."\" readonly></td><td>Telefon2:</td><td><input type=\"text\" name=\"KUN_TELE2\" style=\"width:100px;\" value=\"".$addrdata['TELE2']."\" readonly></td><td>Fax:</td><td><input type=\"text\" name=\"KUN_FAX\" style=\"width:100px;\" value=\"".$addrdata['FAX']."\" readonly></td>";
        $o_cont .= "</tr></table></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Festgestellte Fehler</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";

        if($error=="")
          {
            $o_cont .= "<div style=\"color: #000000; font-weight: bold;\"><br><br><br><br><br><br><br><br>Keine<br><br><br><br><br><br><br><br></div>";
            $o_cont .= "</td></tr><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffff;\">";
            $o_cont .= "<br><br><form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=finalise&type=submit&id=".$_GET['id']."\" method=\"post\"><input type=\"submit\" value=\"Speichern und Buchen\"><input type=\"hidden\" name=\"checked\" value=\"TRUE\"></form><br>";
          }
        else
          {
          	$o_cont .= "<div style=\"color: #ff0000; font-weight: bold;\"><br><br><br><br><br><br><br><br>".$error."<br><br><br><br><br><br><br><br></div>";
            $o_cont .= "</td></tr><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffff;\">";
            $o_cont .= "<br><br><form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$_GET['id']."\" method=\"post\"><input type=\"submit\" value=\"Positionen bearbeiten\"></form><br>";
          }
        $o_cont .= "</td></tr>";
        $o_cont .= "</table>";
      }
    elseif(($_GET['action']=="finalise") && ($_GET['type']=="submit"))
      {
        // Header: main.php?section=".$_GET['section']."&module=rechnung&action=finalize&type=submit&id=xxxxxxx

        if($_POST['checked']=="TRUE")
          {
          	// Buchungen durchführen und Belegbutton erstellen

            $res_id = mysql_query("SELECT JOURNALPOS.ARTIKEL_ID, JOURNALPOS.MENGE, ARTIKEL.MENGE_AKT FROM JOURNALPOS JOIN ARTIKEL ON ARTIKEL.REC_ID = JOURNALPOS.ARTIKEL_ID WHERE ARTIKEL.ARTIKELTYP='N' AND JOURNALPOS.JOURNAL_ID=".$_GET['id'], $db_id);
            $res_num = mysql_num_rows($res_id);
            $result = array();
            for($i=0; $i<$res_num; $i++)
              {
                array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));
              }
            mysql_free_result($res_id);

            foreach($result as $row)	// Menge im Artikelstamm anpassen
              {
              	$row['MENGE_AKT'] = $row['MENGE_AKT'] - $row['MENGE'];
              	if(!mysql_query("UPDATE ARTIKEL SET MENGE_AKT='".$row['MENGE_AKT']."' WHERE REC_ID=".$row['ARTIKEL_ID'], $db_id))
              	  {
              	  	echo mysql_error($db_id);
              	  }
              }

            // Journalpositionen & -Seriennummern buchen

            mysql_query("UPDATE JOURNALPOS SET QUELLE=3, QUELLE_SUB=1, VIEW_POS=1, GEBUCHT='Y' WHERE JOURNAL_ID=".$_GET['id'], $db_id);

            $res_id = mysql_query("SELECT SNUM_ID FROM JOURNALPOS_SERNUM WHERE JOURNAL_ID=".$_GET['id'], $db_id);
            $res_num = mysql_num_rows($res_id);
            $result = array();
            for($i=0; $i<$res_num; $i++)
              {
                array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));
              }
            mysql_free_result($res_id);

           foreach($result as $row)	// Seriennummer-Status setzen
              {
                mysql_query("UPDATE ARTIKEL_SERNUM SET STATUS='VK_RECH' WHERE SNUM_ID=".$row['SNUM_ID'], $db_id);
              }

            // Daten sammeln, Rechnungsnummer erstellen, Stadium

            $res_id = mysql_query("SELECT ADDR_ID, BSUMME, SOLL_SKONTO, ZAHLART, GEGENKONTO, KUN_NAME1, KUN_NAME2 FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $main = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, TELE1, TELE2, FAX, FUNK, LAND, PLZ, ORT FROM ADRESSEN WHERE REC_ID=".$main['ADDR_ID'], $db_id);
            $addrdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            switch($main['ZAHLART'])
              {
              	case 0: $stadium=2; break;
              	case 1:  
					if ($main['SOLL_SKONTO'] > 0) { $stadium=8; }	// Stadium = bezahlt mit Skonto
					else { $stadium=9; } 			// Zahlart = Bar, Stadium = bezahlt
					break;		
              	case 2: $stadium=2; break;		// Zahlart = Überweisung
              	case 3: $stadium=2; break;		// Zahlart = Nachnahme
              	case 4: $stadium=2; break;		// Zahlart = UPS Nachnahme
              	case 5: $stadium=2; break;		// Zahlart = Scheck
              	case 6: $stadium=2; break;		// Zahlart = EC-Karte
              	case 7: $stadium=2; break;		// Zahlart = Kreditkarte
              	case 8: $stadium=2; break;		// Zahlart = Paypal
              	case 9: $stadium=2; break;		// Zahlart = Lastschrift
              	default: $stadium=2; break;		// Stadium = offen
              }

/*
            switch($main['ZAHLART'])
              {
              	case 0: $stadium=20; break;
              	case 1: $stadium=91; break;
              	case 2: $stadium=22; break;
              	case 3: $stadium=23; break;
              	case 4: $stadium=24; break;
              	case 5: $stadium=95; break;
              	case 6: $stadium=26; break;
              	case 7: $stadium=27; break;
              	case 8: $stadium=28; break;
              	case 9: $stadium=29; break;
              	default: $stadium=22; break;
              }
*/
            $rec_id = mysql_query("SELECT VAL_INT2, VAL_INT3, VAL_CHAR FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='VK-RECH'", $db_id);
            $rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
            mysql_free_result($rec_id);

            $l_template = $rec_tmp['VAL_INT3'];				// Wieviele Stellen hat die Belegnummer?
            $l_current = strlen($rec_tmp['VAL_INT2']);
            $l_diff = $l_template - $l_current;

            $vrmask = "";					// Maske für alphanumerische Belegnummer
            $vrcnt = $rec_tmp['VAL_INT3'];
            $vrenum = "";					// String mit führenden Nullen bauen

            while($vrcnt)
              {
              	$vrmask .= "0";
              	$vrcnt--;
              }

            while($l_diff)
              {
                $vrenum .= "0";
                $l_diff--;
              }

            $vrenum .= $rec_tmp['VAL_INT2'];									// String mit Nullen komplett
            $vrenum = str_replace($vrmask, $vrenum, $rec_tmp['VAL_CHAR']);		// Alphanumerische Zeichen dran
            $vrenum = str_replace("\"", "", $vrenum);							// Anführungsstriche raus und neue NEXT_VK-RECH in REGISTRY eintragen

            $rec_tmp['VAL_INT2']++;

            $rec_id = mysql_query("UPDATE REGISTRY SET VAL_INT2='".$rec_tmp['VAL_INT2']."' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='VK-RECH'", $db_id);

            // Journal und ggf. Kasse buchen:

            mysql_query("UPDATE JOURNAL SET VRENUM='".$vrenum."', RDATUM=CURDATE(), QUELLE=3, QUELLE_SUB=1, STADIUM=".$stadium." WHERE REC_ID=".$_GET['id'], $db_id);

			  if (($stadium == 8) or ($stadium == 9))  // Stadium = bezahlt
              {
              	$db_res = mysql_query("SELECT MA_ID FROM MITARBEITER WHERE LOGIN_NAME='".$_SESSION['user']."'", $db_id);
                $tmp_data = mysql_fetch_array($db_res, MYSQL_ASSOC);
                mysql_free_result($db_res);

                $betrag = $main['BSUMME'] - ($main['BSUMME'] * $main['SOLL_SKONTO'] / 100);
                
				mysql_query("INSERT INTO ZAHLUNGEN SET FIBU_KTO=1600, MA_ID=".$tmp_data['MA_ID'].", DATUM=CURDATE(), BELEGNUM='".$vrenum."', QUELLE=3, JOURNAL_ID=".$_GET['id'].", FIBU_GEGENKTO='".$main['GEGENKONTO']."', SKONTO_PROZ='".$main['SOLL_SKONTO']."', BETRAG='".$betrag."', VERW_ZWECK='ZE VK-RE ".$main['KUN_NAME1']." ".$main['KUN_NAME2']."', GEBUCHT='Y', ERSTELLT_NAME='".$usr_name."',  ERSTELLT_AM=NOW()", $db_id);
				
              }
            elseif($stadium == 2)  // Stadium = offen
              {
                $betrag = round($main['BSUMME'] - ($main['BSUMME'] * $main['SOLL_SKONTO'] / 100),2);
                
				mysql_query("INSERT INTO JOURNAL_OP SET QUELLE=3, ADDR_ID='".$main['GEGENKONTO']."', JOURNAL_ID=".$_GET['id'].", BSUMME='".$betrag."'", $db_id);

              }

/*            if($stadium == 9)
              {
              	$db_res = mysql_query("SELECT MA_ID FROM MITARBEITER WHERE LOGIN_NAME='".$_SESSION['user']."'", $db_id);
                $tmp_data = mysql_fetch_array($db_res, MYSQL_ASSOC);
                mysql_free_result($db_res);

                $betrag = $main['BSUMME'] - ($main['BSUMME'] * $main['SOLL_SKONTO'] / 100);

              	mysql_query("INSERT INTO FIBU_KASSE SET MA_ID=".$tmp_data['MA_ID'].", BDATUM=CURDATE(), BELEGNUM='".$vrenum."', QUELLE=3, JOURNAL_ID=".$_GET['id'].", GKONTO='".$main['GEGENKONTO']."', SKONTO='".$main['SOLL_SKONTO']."', ZU_ABGANG='".$betrag."', BTXT='ZE VK-RE ".$main['KUN_NAME1']." ".$main['KUN_NAME2']."', ERST_NAME='".$usr_name."', ERSTELLT=CURDATE()", $db_id);
				
				if($main['SOLL_SKONTO'])
                  {
                    mysql_query("UPDATE JOURNAL SET IST_ZAHLDAT=CURDATE(), IST_SKONTO='".$main['SOLL_SKONTO']."', IST_BETRAG='".$betrag."', STADIUM=81", $db_id);
                  }
                else
                  {
                  	mysql_query("UPDATE JOURNAL SET IST_ZAHLDAT=CURDATE(), IST_SKONTO='".$main['SOLL_SKONTO']."', IST_BETRAG='".$betrag."'", $db_id);
                  }
              }
            elseif($stadium == 95)
              {
                $betrag = $main['BSUMME'] - ($main['BSUMME'] * $main['SOLL_SKONTO'] / 100);

                if($main['SOLL_SKONTO'])
                  {
                    mysql_query("UPDATE JOURNAL SET IST_ZAHLDAT=CURDATE(), IST_SKONTO='".$main['SOLL_SKONTO']."', IST_BETRAG='".$betrag."', STADIUM=85", $db_id);
                  }
                else
                  {
                  	mysql_query("UPDATE JOURNAL SET IST_ZAHLDAT=CURDATE(), IST_SKONTO='".$main['SOLL_SKONTO']."', IST_BETRAG='".$betrag."'", $db_id);
                  }
              }
*/
            // Ausgabe

           $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr>
                       <td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$section."&module=rechnung&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td>
                       </tr></table>";

            $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Kundendaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" align=\"center\">";
            $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
            $o_cont .= "<td>Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NUM\" style=\"width:60px;\" value=\"".$addrdata['KUNNUM1']."\" readonly></td><td>Kunde:</td><td colspan=\"3\" width=\"400\"><input type=\"text\" name=\"KUN_NAME\" style=\"width:400px;\" value=\"".$addrdata['ANREDE']." ".$addrdata['NAME1']." ".$addrdata['NAME2']." ".$addrdata['NAME3']."\" readonly></td><td>Telefon1:</td><td><input type=\"text\" name=\"KUN_TELE1\" style=\"width:100px;\" value=\"".$addrdata['TELE1']."\" readonly></td><td>Mobilfunk:</td><td><input type=\"text\" name=\"KUN_FUNK\" style=\"width:100px;\" value=\"".$addrdata['FUNK']."\" readonly></td></tr>";
            $o_cont .= "<tr><td>Rechnungs-Nr.:</td><td><input type=\"text\" name=\"NUMMER\" style=\"width:60px;\" value=\"".$vrenum."\" readonly></td><td>Land/Plz/Ort:</td><td><input type=\"text\" name=\"KUN_LAND\" style=\"width:30px;\" value=\"".$addrdata['LAND']."\" readonly></td><td><input type=\"text\" name=\"KUN_PLZ\" style=\"width:60px;\" value=\"".$addrdata['PLZ']."\" readonly></td><td><input type=\"text\" name=\"KUN_ORT\" style=\"width:300px;\" value=\"".$addrdata['ORT']."\" readonly></td><td>Telefon2:</td><td><input type=\"text\" name=\"KUN_TELE2\" style=\"width:100px;\" value=\"".$addrdata['TELE2']."\" readonly></td><td>Fax:</td><td><input type=\"text\" name=\"KUN_FAX\" style=\"width:100px;\" value=\"".$addrdata['FAX']."\" readonly></td>";
            $o_cont .= "</tr></table></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Abschluss</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
          	$o_cont .= "<div style=\"color: #000000; font-weight: bold;\"><br><br><br><br><br><br><br><br>Buchung durchgef&uuml;hrt<br><br><br><br><br><br><br><br></div>";
            $o_cont .= "</td></tr><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffff;\">";
            $o_cont .= "<br><br><form action=\"report.php?module=rechnung&id=".$_GET['id']."\" method=\"post\" target=\"_blank\"><input type=\"submit\" value=\"Beleg anzeigen\"><input type=\"hidden\" name=\"user\" value=\"".$usr_name."\"></form><br>";
            $o_cont .= "</td></tr>";
            $o_cont .= "</table>";
          }
        else
          {
          	// Fehler - zurück und anzeigen

            $o_navi = print_navi($_GET['id'], $_GET['section']);

            $res_id = mysql_query("SELECT ADDR_ID, VRENUM FROM JOURNAL WHERE REC_ID=".$_GET['id'], $db_id);
            $main = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $res_id = mysql_query("SELECT KUNNUM1, ANREDE, NAME1, NAME2, NAME3, TELE1, TELE2, FAX, FUNK, LAND, PLZ, ORT FROM ADRESSEN WHERE REC_ID=".$main['ADDR_ID'], $db_id);
            $addrdata = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);

            $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Kundendaten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" align=\"center\">";
            $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
            $o_cont .= "<td>Kunden-Nr.:</td><td><input type=\"text\" name=\"KUN_NUM\" style=\"width:60px;\" value=\"".$addrdata['KUNNUM1']."\" readonly></td><td>Kunde:</td><td colspan=\"3\" width=\"400\"><input type=\"text\" name=\"KUN_NAME\" style=\"width:400px;\" value=\"".$addrdata['ANREDE']." ".$addrdata['NAME1']." ".$addrdata['NAME2']." ".$addrdata['NAME3']."\" readonly></td><td>Telefon1:</td><td><input type=\"text\" name=\"KUN_TELE1\" style=\"width:100px;\" value=\"".$addrdata['TELE1']."\" readonly></td><td>Mobilfunk:</td><td><input type=\"text\" name=\"KUN_FUNK\" style=\"width:100px;\" value=\"".$addrdata['FUNK']."\" readonly></td></tr>";
            $o_cont .= "<tr><td>Intern-Nr.:</td><td><input type=\"text\" name=\"NUMMER\" style=\"width:60px;\" value=\"".$main['VRENUM']."\" readonly></td><td>Land/Plz/Ort:</td><td><input type=\"text\" name=\"KUN_LAND\" style=\"width:30px;\" value=\"".$addrdata['LAND']."\" readonly></td><td><input type=\"text\" name=\"KUN_PLZ\" style=\"width:60px;\" value=\"".$addrdata['PLZ']."\" readonly></td><td><input type=\"text\" name=\"KUN_ORT\" style=\"width:300px;\" value=\"".$addrdata['ORT']."\" readonly></td><td>Telefon2:</td><td><input type=\"text\" name=\"KUN_TELE2\" style=\"width:100px;\" value=\"".$addrdata['TELE2']."\" readonly></td><td>Fax:</td><td><input type=\"text\" name=\"KUN_FAX\" style=\"width:100px;\" value=\"".$addrdata['FAX']."\" readonly></td>";
            $o_cont .= "</tr></table></td></tr>";
            $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"16\" valign=\"middle\"><b>&nbsp;Abschluss</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
            $o_cont .= "<tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
          	$o_cont .= "<div style=\"color: #ff0000; font-weight: bold;\"><br><br><br><br><br><br><br><br>Buchung nicht m&ouml;glich!<br><br><br><br><br><br><br><br></div>";
            $o_cont .= "</td></tr><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffff;\">";
            $o_cont .= "<br><br><form action=\"main.php?section=".$_GET['section']."&module=rechnung&action=finalise&id=".$_GET['id']."\" method=\"post\"><input type=\"submit\" value=\"Fehler anzeigen\"></form><br>";
            $o_cont .= "</td></tr>";
            $o_cont .= "</table>";
          }
      }
    else						// Belegliste
      {
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

        if($_GET['oname'] == "name")			// Merkmal, nach dem die Belegliste sortiert werden soll.
          {
            $sql_oname = "KUN_NAME1";
          }
        elseif($_GET['oname'] == "datum")
          {
            $sql_oname = "RDATUM";
          }
        elseif($_GET['oname'] == "kunnum")
          {
            $sql_oname = "KUN_NUM";
          }
        elseif($_GET['oname'] == "netto")
          {
            $sql_oname = "NSUMME";
          }
        elseif($_GET['oname'] == "projekt")
          {
            $sql_oname = "PROJEKT";
          }
        elseif($_GET['oname'] == "projekt")
          {
            $sql_oname = "PROJEKT";
          }
        elseif($_GET['oname'] == "termin")
          {
            $sql_oname = "TERMIN";
          }
        elseif($_GET['oname'] == "zahlart")
          {
            $sql_oname = "ZAHLART";
          }
        elseif($_GET['oname'] == "liefart")
          {
            $sql_oname = "LIEFART";
          }
        elseif($_GET['oname'] == "erstellt")
          {
            $sql_oname = "ERST_NAME";
          }
        else
          {
            $sql_oname = "VRENUM";
          }

        $res_id = mysql_query("SELECT REC_ID, VRENUM, KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3, PROJEKT, NSUMME, RDATUM, TERMIN, ZAHLART, LIEFART, STADIUM, ERST_NAME FROM JOURNAL WHERE QUELLE=13 ORDER BY ".$sql_oname." ".$sql_otype, $db_id);
        $res_num = mysql_numrows($res_id);
        $result = array();

        for($i=0; $i<$res_num; $i++)
          {
            array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
          }
        mysql_free_result($res_id);

        $color = 0;
        $zahlart = get_zahlart($db_id);
        $liefart = get_liefart($db_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=nummer&otype=".$otype."\">int. Nr.</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=kunnum&otype=".$otype."\">Ku.-Nr.</b></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=name&otype=".$otype."\">Kunde</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=projekt&otype=".$otype."\">Projekt / Beschreibung</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=netto&otype=".$otype."\">Summe Netto</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=datum&otype=".$otype."\">le.&Auml;nderung</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=termin&otype=".$otype."\">Termin</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=zahlart&otype=".$otype."\">Zahlart</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=liefart&otype=".$otype."\">Versand</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rechnung&oname=erstellt&otype=".$otype."\">Erstellt</a></td></tr>";
        foreach($result as $row)
          {
            if(!strstr($row['VRENUM'], "EDI"))
              {
                if($row['KUN_ANREDE'])
                  {
                    $temp_name = $row['KUN_ANREDE']." ".$row['KUN_NAME1']." ".$row['KUN_NAME2']." ".$row['KUN_NAME3'];
                  }
                else
                  {
                    $temp_name = $row['KUN_NAME1']." ".$row['KUN_NAME2']." ".$row['KUN_NAME3'];
                  }

                if(strlen($temp_name)>30)
                  {
                    $tmp = str_split($temp_name, 30);
                    $temp_name = $tmp[0]."...";
                  }

                if(strlen($row['PROJEKT'])>20)
                  {
                    $tmp = str_split($row['PROJEKT'], 20);
                    $row['PROJEKT'] = $tmp[0]."...";
                  }

                if(strstr($row['TERMIN'], "1899"))
                  {
                    $row['TERMIN'] = "";
                  }

                // Name der Zahlart holen
                if($row['ZAHLART']<0)
                  {
                    $row['ZAHLART'] = "nicht festgelegt";
                  }
                else
                  {
                    foreach($zahlart as $set)
                      {
                        if($set['NUMMER']==$row['ZAHLART'])
                          {
                            $row['ZAHLART'] = $set['NAME'];
                          }
                      }
                  }

                // Name der Versandart holen
                if($row['LIEFART']<0)
                  {
                    $row['LIEFART'] = "nicht festgelegt";
                  }
                else
                  {
                    foreach($liefart as $set)
                      {
                        if($set['NUMMER']==$row['LIEFART'])
                          {
                            $row['LIEFART'] = $set['NAME'];
                          }
                      }
                  }

                $color++;
                if($color%2)
                  {
                    $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['VRENUM']."</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['KUN_NUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$temp_name."</a></td><td align=\"left\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['PROJEKT']."</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".number_format($row['NSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['RDATUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['TERMIN']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['ZAHLART']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['LIEFART']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['ERST_NAME']."</a></td></tr></a>";

                  }
                else
                  {
                    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['VRENUM']."</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['KUN_NUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$temp_name."</a></td><td align=\"left\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['PROJEKT']."</a></td><td align=\"right\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".number_format($row['NSUMME'], 2, ",", ".")." &euro;</a></td><td align=\"center\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['RDATUM']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['TERMIN']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['ZAHLART']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['LIEFART']."</a></td><td><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=pos&id=".$row['REC_ID']."\">&nbsp;".$row['ERST_NAME']."</a></td></tr></a>";
                  }
              }
          }

        $o_cont .= "</table>";

        $o_navi = "<table width=\"100\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"100\" align=\"right\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rechnung&action=all&id=new\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Neuen Beleg&nbsp;</a></td></tr></table>";
      }
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>