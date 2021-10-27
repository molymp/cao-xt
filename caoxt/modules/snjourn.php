<?php

$o_head = "Seriennummernjournal";
$o_navi = "";

function sn_get_data($db_id, $id, $db_pref)
  {
    $res_id = mysql_query("SELECT * FROM ".$db_pref."SN_AEND WHERE ID=".$id, $db_id);
    $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT ARTNUM, KURZNAME FROM ARTIKEL WHERE REC_ID=".$data['ART_ID'], $db_id);
    $tmp = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $res_id = mysql_query("SELECT SERNUMMER FROM ARTIKEL_SERNUM WHERE SNUM_ID=".$data['SNR_ID'], $db_id);
    $tmp2 = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    
    $data['ARTNUM'] = $tmp['ARTNUM'];
    $data['NAME'] = $tmp['KURZNAME'];
    $data['ART_SNR'] = $tmp2['SERNUMMER'];

    return $data;
  }

// HAUPTPROGRAMM

if($usr_rights)
  {
        if(!$_GET['month'])
          {
            // Header: main.php?section=".$_GET['section']."&module=snjourn
            
            $month = date("n");
            $year = date("Y");
          }
        else
          {
            // Header: main.php?section=".$_GET['section']."&module=snjourn&month=xx&year=xxxx
            
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
           $o_navi = "<table width=\"300\" cellpadding=\"0\" cellspacing=\"0\"><tr><td class=\"head\" align=\"right\" valign=\"middle\">".$m_name."&nbsp;".$year."</td><td align=\"right\" valign=\"middle\"><table width=\"16\" height=\"16\" cellpadding=\"0\" cellspacing=\"2\"><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=snjourn&action=list&month=".$next_month."&year=".$next_year."\"><img src=\"images/p_up.gif\" border=\"0\"></a></td></tr><tr><td bgcolor=\"#d4d0c8\" align=\"center\" valign=\"middle\"><a href=\"main.php?section=".$_GET['section']."&module=snjourn&action=list&month=".$last_month."&year=".$last_year."\"><img src=\"images/p_down.gif\" border=\"0\"></a></td></tr></table></td></tr></table>";
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
        elseif($_GET['oname'] == "ostatus")
          {
            $sql_oname = "O_STATUS";
          }
        elseif($_GET['oname'] == "nstatus")
          {
            $sql_oname = "N_STATUS";
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
	  
        $res_id = mysql_query("SELECT * FROM ".$db_pref."SN_AEND WHERE MONTH(DATUM)=".$month." AND YEAR(DATUM)=".$year." ORDER BY ".$sql_oname." ".$sql_otype, $db_id);
        $data = array();
        $d_num = mysql_num_rows($res_id);
        for($i=0; $i<$d_num; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        
        for($i=0; $i<$d_num; $i++)
          {
            $tmp = sn_get_data($db_id, $data[$i]['ID'], $db_pref);
            $data[$i]['ARTNUM'] = $tmp['ARTNUM'];
            $data[$i]['NAME'] = $tmp['NAME'];
            $data[$i]['ART_SNR'] = $tmp['ART_SNR'];
            $data[$i]['O_STATUS'] = $tmp['O_STATUS'];
            $data[$i]['N_STATUS'] = $tmp['N_STATUS'];
            $data[$i]['DATUM'] = $tmp['DATUM'];
            $data[$i]['ERSTELLT'] = $tmp['ERSTELLT'];
          }
        
        
        $color = 0;
        mysql_free_result($res_id);

        $o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=snjourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=artikel&otype=".$otype."\">Artikelnr.</a></td><td>&nbsp;Artikelname</td><td>&nbsp;Seriennummer</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=snjourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=ostatus&otype=".$otype."\">Status (alt)</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=snjourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=nstatus&otype=".$otype."\">Status (neu)</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=snjourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=id&otype=".$otype."\">Datum</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=snjourn&month=".$_GET['month']."&year=".$_GET['year']."&oname=bearbeiter&otype=".$otype."\">Erstellt</a></td></tr>";
        foreach($data as $row)
          {
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=snjourn&action=detail&id=".$row['ID']."\">&nbsp;".$row['ARTNUM']."</a></td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ART_SNR']."</td><td>&nbsp;".$row['O_STATUS']."</td><td>&nbsp;".$row['N_STATUS']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=snjourn&action=detail&id=".$row['ID']."\">&nbsp;".$row['ARTNUM']."</a></td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ART_SNR']."</td><td>&nbsp;".$row['O_STATUS']."</td><td>&nbsp;".$row['N_STATUS']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
              }

          }        
        $o_cont .= "</table>";
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>