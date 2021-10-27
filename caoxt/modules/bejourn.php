<?php

$o_head = "Bestandsjournal";
$o_navi = "";

function b_get_data($db_id, $id, $db_pref)
  {
    $res_id = mysql_query("SELECT * FROM ".$db_pref."BEST_AEND WHERE ID=".$id, $db_id);
    $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT ARTNUM, KURZNAME FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
    $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    
    $data['ARTNUM'] = $tmp['ARTNUM'];
    $data['NAME'] = $tmp['KURZNAME'];
    $data['KOMMENTAR'] = stripslashes($data['KOMMENTAR']);

    if($data['LAGER_QUELLE']=="LAGER")
      {
        $data['LAGER_QUELLE'] = "Lager";
      }
    elseif($data['LAGER_QUELLE']=="E_BEST")
      {
        $data['LAGER_QUELLE'] = "Eigenbestand";
      }    
    elseif($data['LAGER_QUELLE']=="E_BEST")
      {
        $data['LAGER_QUELLE'] = "Reparaturbestand";
      }    

    if($data['LAGER_ZIEL']=="LAGER")
      {
        $data['LAGER_ZIEL'] = "Lager";
      }
    elseif($data['LAGER_ZIEL']=="E_BEST")
      {
        $data['LAGER_ZIEL'] = "Eigenbestand";
      }    
    elseif($data['LAGER_ZIEL']=="E_BEST")
      {
        $data['LAGER_ZIEL'] = "Reparaturbestand";
      }
    else
      {
        $data['LAGER_ZIEL'] = "Verlust";
      }

    return $data;
  }

// HAUPTPROGRAMM

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=bejourn&action=details&id=xxxxxxx
        
        $data = b_get_data($db_id, $_GET['id'], $db_pref);
       
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"4\"><b>&nbsp;Quelle</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" colspan=\"4\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Bestand:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['LAGER_QUELLE']."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Konto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['KONTO']."</td></tr></table></td></tr>";
        $o_cont .= "</table>"; 
        $o_cont .= "<br><br>";
        $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"3\">";
        $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['ARTNUM']."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['NAME']."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['ANZAHL']."</td></tr></table></td><td></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"top\" width=\"100\">Kommentar:</td><td><table width=\"80%\" height=\"112\" cellpadding=\"2\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" valign=\"top\">".$data['KOMMENTAR']."</td></tr></table></td></tr>";
        $o_cont .= "</table><br>";        
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" colspan=\"4\"><b>&nbsp;Ziel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\" colspan=\"4\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Bestand:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['LAGER_ZIEL']."</td></tr></table></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Gegenkonto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$data['GKONTO']."</td></tr></table></td></tr>";        
        $o_cont .= "</table><br><br><br><br>";                
        $o_cont .= "</td></tr>";
        $o_cont .= "</table>";
        
        $o_navi = "<table width=\"100\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"100\" align=\"right\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=bejourn&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";
      }
    else
      {
        if(!$_GET['month'])
          {
            // Header: main.php?section=".$_GET['section']."&module=bejourn
            
            $month = date("n");
            $year = date("Y");
          }
        else
          {
            // Header: main.php?section=".$_GET['section']."&module=bejourn&month=xx&year=xxxx
            
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
           $o_navi = "<table width=\"300\" cellpadding=\"0\" cellspacing=\"0\"><tr><td class=\"head\" align=\"right\" valign=\"middle\">".$m_name."&nbsp;".$year."</td><td align=\"right\" valign=\"middle\"><table width=\"16\" height=\"16\" cellpadding=\"0\" cellspacing=\"2\"><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=bejourn&action=list&month=".$next_month."&year=".$next_year."\"><img src=\"images/p_up.gif\" border=\"0\"></a></td></tr><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=bejourn&action=list&month=".$last_month."&year=".$last_year."\"><img src=\"images/p_down.gif\" border=\"0\"></a></td></tr></table></td></tr></table>";
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

        if($_GET['oname'] == "artikel")		// Merkmal, nach dem die Belegliste sortiert werden soll.
          {
            $sql_oname = "ART_ID";
          }
        elseif($_GET['oname'] == "quelle")
          {
            $sql_oname = "LAGER_QUELLE";
          }
        elseif($_GET['oname'] == "ziel")
          {
            $sql_oname = "LAGER_ZIEL";
          }
        elseif($_GET['oname'] == "bearbeiter")
          {
            $sql_oname = "ERSTELLT";
          }
        elseif($_GET['oname'] == "anzahl")
          {
            $sql_oname = "ANZAHL";
          }
        else
          {
            $sql_oname = "ID";
          }
	  
        $res_id = mysql_query("SELECT * FROM ".$db_pref."BEST_AEND WHERE MONTH(DATUM)=".$month." AND YEAR(DATUM)=".$year." ORDER BY ".$sql_oname." ".$sql_otype, $db_id);
        $data = array();
        $d_num = mysql_num_rows($res_id);
        for($i=0; $i<$d_num; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        
        for($i=0; $i<$d_num; $i++)
          {
            $tmp = b_get_data($db_id, $data[$i]['ID'], $db_pref);
            $data[$i]['ARTNUM'] = $tmp['ARTNUM'];
            $data[$i]['NAME'] = $tmp['NAME'];
            $data[$i]['ANZAHL'] = $tmp['ANZAHL'];
            $data[$i]['LAGER_QUELLE'] = $tmp['LAGER_QUELLE'];
            $data[$i]['LAGER_ZIEL'] = $tmp['LAGER_ZIEL'];
            $data[$i]['DATUM'] = $tmp['DATUM'];
            $data[$i]['ERSTELLT'] = $tmp['ERSTELLT'];
          }
        
        
        $color = 0;
        mysql_free_result($res_id);

        $o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=artikel&otype=".$otype."\">Artikelnr.</a></td><td>&nbsp;Artikelname</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=anzahl&otype=".$otype."\">Anzahl</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=quelle&otype=".$otype."\">Quelle</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=ziel&otype=".$otype."\">Ziel</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=id&otype=".$otype."\">Datum</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=bejourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=bearbeiter&otype=".$otype."\">Erstellt</a></td></tr>";
        foreach($data as $row)
          {
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=bejourn&action=detail&id=".$row['ID']."\">&nbsp;".$row['ARTNUM']."</a></td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ANZAHL']."</td><td>&nbsp;".$row['LAGER_QUELLE']."</td><td>&nbsp;".$row['LAGER_ZIEL']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=bejourn&action=detail&id=".$row['ID']."\">&nbsp;".$row['ARTNUM']."</a></td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ANZAHL']."</td><td>&nbsp;".$row['LAGER_QUELLE']."</td><td>&nbsp;".$row['LAGER_ZIEL']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
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