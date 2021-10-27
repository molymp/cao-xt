<?php

$o_head = "Sammler";
$o_navi = "";

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        // Header: main.php?section=".$_GET['section']."&module=sammler&action=details&id=xxxxxxx
        
        $res_id = mysql_query("SELECT VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, KUN_NUM, NSUMME, BSUMME FROM JOURNAL WHERE REC_ID=".$_GET[id], $db_id);
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
        
        // Grunddaten gesammelt, suche Kurzname und gebe aus:
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" valign=\"middle\"><b>&nbsp;Allgemeine Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" align=\"center\">";
        $o_cont .= "<table width=\"98%\" cellpadding=\"2\" cellspacing=\"0\"><tr bgcolor=\"#ffffdd\">";
        $o_cont .= "<td>Beleg:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[VRENUM]."</td></tr></table></td><td>Kunde:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[KUN_NAME1]." ".$maindata[KUN_NAME2]."</td></tr></table></td><td>VK-Netto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[NSUMME]." &euro;&nbsp;</td></tr></table></td></tr>";
        $o_cont .= "<tr><td>Erstellt:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[RDATUM]."</td></tr></table></td><td>Kundenr.:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\">&nbsp;".$maindata[KUN_NUM]."</td></tr></table></td><td>VK-Brutto:</td><td><table width=\"80%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td bgcolor=\"#d4d0c8\" align=\"right\">".$maindata[BSUMME]." &euro;&nbsp;</td></tr></table></td>";
        $o_cont .= "</tr></table></td></tr>";
        $o_cont .= "<tr><td bgcolor=\"#ffffdd\" colspan=\"7\" valign=\"middle\"><b>&nbsp;Positionen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Pos.</td><td>&nbsp;Artikelnummer</td><td>&nbsp;Kurzname</td><td>&nbsp;Menge</td></tr>";

        for($j=0; $j<$number; $j++)
          {
            $temp_id = mysql_query("SELECT KURZNAME FROM ARTIKEL WHERE REC_ID=".$posdata[$j][ARTIKEL_ID], $db_id);
            $det_int = mysql_fetch_array($temp_id, MYSQL_ASSOC);
            mysql_free_result($temp_id);

            if($j%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;".$posdata[$j][ARTNUM]."</td><td>&nbsp;".$det_int[KURZNAME]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$posdata[$j][POSITION]."</td><td>&nbsp;".$posdata[$j][ARTNUM]."</td><td>&nbsp;".$det_int[KURZNAME]."</td><td align=\"right\">".number_format($posdata[$j][MENGE], 0)."&nbsp;</td></tr>";
              }
          }
        
        $o_cont .= "<tr bgcolor=\"#ffffff\"><td colspan=\"5\" align=\"center\"><br><br><form action=\"report.php?module=sammler&id=".$_GET[id]."\" method=\"post\" target=\"_blank\"><input type=\"hidden\" name=\"user\" value=\"".$usr_name."\"><input type=\"submit\" value=\" Erstellen \"></form<br><br>";
        
        $o_cont .= "</table>";
        
        $o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"main.php?section=".$_GET['section']."&module=sammler&action=list\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";
      }     
    else
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
        
        $res_id = mysql_query("SELECT REC_ID, PROJEKT, VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, NSUMME, MSUMME, BSUMME, WAEHRUNG FROM JOURNAL WHERE QUELLE=13 ORDER BY ".$sql_oname." ".$sql_otype, $db_id);   
        $res_num = mysql_numrows($res_id);
        $result = array();
    
        for($i=0; $i<$res_num; $i++)
          {
            array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
          }
 
        mysql_free_result($res_id);
        
        if($_GET['status'])  // Neuer Status zu setzen?
          {
            foreach($result as $row)
              {
                if($row['REC_ID'] == $_GET['id'])
                  {
                    $ptemp = explode(" ", $row['PROJEKT']);
                    if($ptemp[0] == "SA")
                      {
                        array_shift($ptemp);  // Evtl. alten Status killen                      
                      }
                    $project = implode(" ", $ptemp);
                    
                    mysql_query("UPDATE JOURNAL SET PROJEKT='".strtoupper($_GET['status'])." ".$project."' WHERE REC_ID=".$_GET['id'], $db_id);
                  }
              }

            // Falls neuer Status gesetzt wurde, ist ein Neuladen der Daten für eine korrekte Anzeige nötig
        
            $res_id = mysql_query("SELECT REC_ID, PROJEKT, VRENUM, RDATUM, KUN_NAME1, KUN_NAME2, NSUMME, MSUMME, BSUMME, WAEHRUNG FROM JOURNAL WHERE QUELLE=13 ORDER BY ".$sql_oname." ".$sql_otype, $db_id);   
            $res_num = mysql_numrows($res_id);
            $result = array();
        
            for($i=0; $i<$res_num; $i++)
              {
                array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC));	// Journaldatensätze in Array
              }
 
            mysql_free_result($res_id);

          }
                
        $color = 0;
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=sammler&oname=rechnung&otype=".$otype."\">Beleg</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=sammler&oname=datum&otype=".$otype."\">Erstellt</a></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=sammler&oname=name&otype=".$otype."\">Name des Kunden</b></td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=sammler&oname=netto&otype=".$otype."\">Netto</a></td><td>&nbsp;MwSt</td><td>&nbsp;<a href=\"main.php?section=".$_GET['section']."&module=sammler&oname=brutto>&otype=".$otype."\">Brutto</a></td><td>&nbsp;Status</td><td>&nbsp;Aktion</td></tr>";
        foreach($result as $row)
          {
            $status = explode(" ", $row['PROJEKT']);
            
            if($status[0] == "SA")
              {
                $link = "<a href=\"main.php?section=".$_GET['section']."&module=sammler&action=list&status=sf&id=".$row[REC_ID]."&oname=".$_GET['oname']."\">&nbsp;fertigstellen</a>";
                $stat = "&nbsp;In Arbeit";
              }
            elseif($status[0] == "SF")
              {
                $link = "";
                $stat = "&nbsp;Fertig";
              }
            else
              {
                $link = "<a href=\"main.php?section=".$_GET['section']."&module=sammler&action=list&status=sa&id=".$row[REC_ID]."&oname=".$_GET['oname']."\">&nbsp;bearbeiten</a>";
                $stat = "&nbsp;Neu";
              }
              
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=sammler&action=detail&id=".$row[REC_ID]."\">&nbsp;".$row[VRENUM]."</a></td><td>&nbsp;".$row[RDATUM]."</td><td>&nbsp;".$row[KUN_NAME1]." ".$row[KUN_NAME2]."</td><td align=\"right\">&nbsp;".number_format($row[NSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[MSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[BSUMME], 2, ",", ".")." &euro;</td><td>".$stat."</td><td>".$link."</td></tr>";

              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td><a href=\"main.php?section=".$_GET['section']."&module=sammler&action=detail&id=".$row[REC_ID]."\">&nbsp;".$row[VRENUM]."</a></td><td>&nbsp;".$row[RDATUM]."</td><td>&nbsp;".$row[KUN_NAME1]." ".$row[KUN_NAME2]."</td><td align=\"right\">&nbsp;".number_format($row[NSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[MSUMME], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[BSUMME], 2, ",", ".")." &euro;</td><td>".$stat."</td><td>".$link."</td></tr>";
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