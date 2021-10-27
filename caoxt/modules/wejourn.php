<?php

$o_head = "Wareneingangsjournal";
$o_navi = "";

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=wejourn&action=details&id=xxxxxxx
        
        $res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, KUN_NUM, NSUMME, BSUMME, ORGNUM FROM JOURNAL WHERE REC_ID=".$_GET[id], $db_id);
        $maindata = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);
        $res_id = mysql_query("SELECT REC_ID, ARTIKEL_ID, POSITION, MENGE, ARTNUM FROM JOURNALPOS WHERE JOURNAL_ID=".$_GET[id]." ORDER BY POSITION ASC", $db_id);
        $posdata = array();
        $number = mysql_num_rows($res_id); 					// Detaildaten / Positionen abarbeiten
        for($j=0; $j<$number; $j++)
          {
            array_push($posdata, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }      
        mysql_free_result($res_id);
        
        // Grunddaten gesammelt, suche Lieferantennummern und gebe aus:
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" valign=\"middle\"><b>&nbsp;Allgemeine Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Beleg:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[VRENUM]."</td></tr></table></td><td>Lieferant:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[KUN_NAME1]." ".$maindata[KUN_NAME2]."</td></tr></table></td><td>EK-Netto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[NSUMME]." &euro;&nbsp;</td></tr></table></td></tr>";
        $o_cont .= "<tr><td>Datum:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[RDATUM]."</td></tr></table></td><td>ER-Nummer:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[ORGNUM]."</td></tr></table></td><td>EK-Brutto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[BSUMME]." &euro;&nbsp;</td></tr></table></td>";
        $o_cont .= "</tr></table></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" valign=\"middle\"><b>&nbsp;Positionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Pos.</td><td>&nbsp;Bestellnummer</td><td>&nbsp;Artikelnummer</td><td>&nbsp;Kurzname</td><td>&nbsp;Menge</td><td>&nbsp;Eigen-RMA</td></tr>";

        for($j=0; $j<$number; $j++)
          {
            $temp_id = mysql_query("SELECT ARTNUM, KURZNAME FROM ARTIKEL WHERE REC_ID=".$posdata[$j][ARTIKEL_ID], $db_id);
            $det_int = mysql_fetch_array($temp_id, MYSQL_ASSOC);
            mysql_free_result($temp_id);

            if($j%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;";
                if($posdata[$j][ARTNUM] == $det_int[ARTNUM]) $o_cont .= "-&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"; else $o_cont .= $posdata[$j][ARTNUM];
                $o_cont .= "</td><td><font color=\"FF0000\">&nbsp;".$det_int[ARTNUM]."</font></td><td>&nbsp;".$det_int[KURZNAME]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td>";
                $o_cont .= "<form name=\"form".$j."\" action=\"main.php?section=".$_GET['section']."&module=rma&action=create\" method=\"post\"><input type=\"hidden\" name=\"ARTNUM\" value=\"".$det_int[ARTNUM]."\"><input type=\"hidden\" name=\"LIEF_NR\" value=\"".$maindata[KUN_NUM]."\"><input type=\"hidden\" name=\"LIEF_RNR\" value=\"".$maindata[ORGNUM]."\"><input type=\"hidden\" name=\"JOURNALPOS_ID\" value=\"".$posdata[$j][REC_ID]."\"><input type=\"hidden\" name=\"method\" value=\"ERMA\"><td><a href=\"javascript:document.form".$j.".submit()\">&nbsp;erstellen</a></td></form></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;";
                if($posdata[$j][ARTNUM] == $det_int[ARTNUM]) $o_cont .= "-&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"; else $o_cont .= $posdata[$j][ARTNUM];
                $o_cont .= "</td><td><font color=\"FF0000\">&nbsp;".$det_int[ARTNUM]."</font></td><td>&nbsp;".$det_int[KURZNAME]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td>";               
                $o_cont .= "<form name=\"form".$j."\" action=\"main.php?section=".$_GET['section']."&module=rma&action=create\" method=\"post\"><input type=\"hidden\" name=\"ARTNUM\" value=\"".$det_int[ARTNUM]."\"><input type=\"hidden\" name=\"LIEF_NR\" value=\"".$maindata[KUN_NUM]."\"><input type=\"hidden\" name=\"LIEF_RNR\" value=\"".$maindata[ORGNUM]."\"><input type=\"hidden\" name=\"JOURNALPOS_ID\" value=\"".$posdata[$j][REC_ID]."\"><input type=\"hidden\" name=\"method\" value=\"ERMA\"><td><a href=\"javascript:document.form".$j.".submit()\">&nbsp;erstellen</a></td></form></tr>";
              }
          }
        $o_cont .= "</table>";
        
        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";
      }
    else
      {
        if(!$_GET['month'])
          {
            // Header: main.php?section=".$_GET['section']."&module=wejourn
            
            $month = date("n");
            $year = date("Y");
          }
        else
          {
            // Header: main.php?section=".$_GET['section']."&module=wejourn&month=xx&year=xxxx
            
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
           $o_navi = "<table width=\"300\" cellpadding=\"0\" cellspacing=\"0\"><tr><td class=\"head\" align=\"right\" valign=\"middle\">".$m_name."&nbsp;".$year."</td><td align=\"right\" valign=\"middle\"><table width=\"16\" height=\"16\" cellpadding=\"0\" cellspacing=\"2\"><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=list&month=".$next_month."&year=".$next_year."\"><img src=\"images/p_up.gif\" border=\"0\"></a></td></tr><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=list&month=".$last_month."&year=".$last_year."\"><img src=\"images/p_down.gif\" border=\"0\"></a></td></tr></table></td></tr></table>";
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
	  
        $res_id = mysql_query("SELECT REC_ID, VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, NSUMME, MSUMME, BSUMME, WAEHRUNG, ORGNUM FROM JOURNAL WHERE QUELLE=5 AND MONTH(RDATUM)=".$month." AND YEAR(RDATUM)=".$year." ORDER BY ".$sql_oname." ".$sql_otype, $db_id);   
        $res_num = mysql_numrows($res_id);
        $result = array();
    
        for($i=0; $i<$res_num; $i++)
          {
            array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
          }
 
        mysql_free_result($res_id);
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=rechnung&otype=".$otype."\">Beleg</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=datum&otype=".$otype."\">Datum</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=name&otype=".$otype."\">Name des Lieferanten</b></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=netto&otype=".$otype."\">Netto</a></td><td>&nbsp;MwSt</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=wejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=brutto>&otype=".$otype."\">Brutto</a></td><td>&nbsp;ER-Nummer</td></tr>";
        foreach($result as $row)
          {
            $color++;
            $a_anzahl += $row['Bestand'];
            $a_wert += $row['Gesamtwert'];
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=detail&id=".$row[REC_ID]."\">&nbsp;".$row[VRENUM]."</a></td><td>&nbsp;".$row[RDATUM]."</td><td>&nbsp;".$row[KUN_NAME1]." ".$row[KUN_NAME2]."</td><td align=\"right\">&nbsp;".number_format($row[NSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[MSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[BSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".$row[ORGNUM]."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=wejourn&action=detail&id=".$row[REC_ID]."\">&nbsp;".$row[VRENUM]."</a></td><td>&nbsp;".$row[RDATUM]."</td><td>&nbsp;".$row[KUN_NAME1]." ".$row[KUN_NAME2]."</td><td align=\"right\">&nbsp;".number_format($row[NSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[MSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[BSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".$row[ORGNUM]."</td></tr>";
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