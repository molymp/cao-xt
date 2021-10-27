<?php

$o_head = "RMA-Journal";
$o_navi = "";

function get_status($status_code)
  {
    switch($status_code)
      {
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

function get_data($db_id, $id, $db_pref)
  {
    $res_id = mysql_query("SELECT * FROM ".$db_pref."RMA WHERE ID=".$id, $db_id);
    $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $temp_id1 = mysql_query("SELECT DATUM FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[ID]." AND STATUS>0 ORDER BY ID ASC LIMIT 1", $db_id);        
    $temp_id2 = mysql_query("SELECT DATUM, STATUS FROM ".$db_pref."RMA_STATUS WHERE RMA_ID=".$data[ID]." AND STATUS>0 ORDER BY ID DESC LIMIT 1", $db_id);            
        
    $temp1 = mysql_fetch_array($temp_id1, MYSQL_ASSOC);
    $temp2 = mysql_fetch_array($temp_id2, MYSQL_ASSOC);
            
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

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=rmajourn&action=details&id=xxxxxxx
        
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
        $o_cont .= "</td></tr><tr><td bgcolor=\"#ffffdd\" colspan=\"5\" valign=\"middle\"><b>&nbsp;Vorg&auml;nge</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "</form>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Datum</td><td>&nbsp;Status</td><td>&nbsp;erstellt von</td><td>&nbsp;Kommentar</td></tr>";
        foreach($datalist as $row)
          {
            $data[STATUS_TEXT] = get_status($row[STATUS]);
            
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td></td><td>&nbsp;".$row[DATUM]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td>&nbsp;".$row[ERSTELLT]."</td><td>&nbsp;".$row[KOMMENTAR]."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td></td><td>&nbsp;".$row[DATUM]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td>&nbsp;".$row[ERSTELLT]."</td><td>&nbsp;".$row[KOMMENTAR]."</td></tr>";
              }

          }
  
        $o_cont .= "</table>";
        $o_cont .= "</table>";
        
        $o_navi = "<table width=\"100\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"100\" align=\"right\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=rmajourn&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";
      }
    else
      {
        if(!$_GET['month'])
          {
            // Header: main.php?section=".$_GET['section']."&module=rmajourn
            
            $month = date("n");
            $year = date("Y");
          }
        else
          {
            // Header: main.php?section=".$_GET['section']."&module=rmajourn&month=xx&year=xxxx
            
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
           $o_navi = "<table width=\"300\" cellpadding=\"0\" cellspacing=\"0\"><tr><td class=\"head\" align=\"right\" valign=\"middle\">".$m_name."&nbsp;".$year."</td><td align=\"right\" valign=\"middle\"><table width=\"16\" height=\"16\" cellpadding=\"0\" cellspacing=\"2\"><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=rmajourn&action=list&month=".$next_month."&year=".$next_year."\"><img src=\"images/p_up.gif\" border=\"0\"></a></td></tr><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=rmajourn&action=list&month=".$last_month."&year=".$last_year."\"><img src=\"images/p_down.gif\" border=\"0\"></a></td></tr></table></td></tr></table>";
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
            $sql_oname = "ERSTDAT";
          }
        elseif($_GET['oname'] == "lieferant")
          {
            $sql_oname = "LIEF_ID";
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
	  
        if($res_id = mysql_query("SELECT * FROM ".$db_pref."RMA WHERE FINAL IS NOT NULL AND MONTH(ERSTDAT)=".$month." AND YEAR(ERSTDAT)=".$year." ORDER BY ".$sql_oname." ".$sql_otype, $db_id))
          {
            $number = mysql_num_rows($res_id);
          }
        else
          {
            $number = 0;
          }
        $data = array();
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
            $data[$i][ART_NAME] = $temp5[KURZNAME];
            
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
        if($number)
          {
            mysql_free_result($res_id);
          }
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rmajourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=id&otype=".$otype."\">RMA-Nummer</a></td><td>&nbsp;Artikel</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rmajourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=kunde&otype=".$otype."\">Kunde</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rmajourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=lieferant&otype=".$otype."\">Lieferant</a></td><td>&nbsp;Lief.-RMA</td><td>&nbsp;Status</td><td>&nbsp;abgeschlossen am</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rmajourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=datum&otype=".$otype."\">erstellt am</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=rmajourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=bearbeiter&otype=".$otype."\">erstellt von</a></td><td>&nbsp;Kopie</td></tr>";
        foreach($data as $row)
          {
            $data[STATUS_TEXT] = get_status($row[STATUS]);
            
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rmajourn&action=detail&id=".$row[ID]."\">&nbsp;".$row[RMANUM]."</a></td><td>&nbsp;".$row[ART_NAME]."</a></td><td>&nbsp;".$row[KUN_NAME]."</td><td>&nbsp;".$row[LIEF_NAME]."</td><td>&nbsp;".$row[LIEF_RMA]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td align=\"right\">".$row[LAST_CHANGE]."</td><td align=\"right\">".$row[CREATED]."</td><td align=\"right\">".$row[ERSTELLT]."</td><td><a href=\"main.php?section=".$_GET['section']."&module=rma&action=copy&id=".$row[ID]."\">&nbsp;erstellen</a></td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=rmajourn&action=detail&id=".$row[ID]."\">&nbsp;".$row[RMANUM]."</a></td><td>&nbsp;".$row[ART_NAME]."</a></td><td>&nbsp;".$row[KUN_NAME]."</td><td>&nbsp;".$row[LIEF_NAME]."</td><td>&nbsp;".$row[LIEF_RMA]."</td><td>&nbsp;".$data[STATUS_TEXT]."</td><td align=\"right\">".$row[LAST_CHANGE]."</td><td align=\"right\">".$row[CREATED]."</td><td align=\"right\">".$row[ERSTELLT]."</td><td><a href=\"main.php?section=".$_GET['section']."&module=rma&action=copy&id=".$row[ID]."\">&nbsp;erstellen</a></td></tr>";
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