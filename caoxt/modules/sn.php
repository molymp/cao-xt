<?php

$o_head = "Seriennummernverwaltung";
$o_navi = "";
$now = time();

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
    if((!$_GET['action']) || ($_GET['action']=="new"))
      {
        // Header: main.php?section=".$_GET['section']."&module=sn&action=new
        $res_id = mysql_query("SELECT ID FROM ".$db_pref."SN_AEND WHERE 1 ORDER BY ID DESC LIMIT 10", $db_id);
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
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><form action=\"main.php?section=".$_GET['section']."&module=sn&action=check\" method=\"post\">";
        $o_cont .= "<tr><td colspan=\"8\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td colspan=\"8\" bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"30\" value=\"".$_POST['ARTNUM']."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Serien-Nr.:</td><td><input type=\"text\" name=\"SERNUM\" size=\"30\" value=\"".$_POST['SERNUM']."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\" valign=\"top\">Status:</td><td><select name=\"STATUS\" size=\"1\"><option>LAGER</option><option>VK_LIEF</option><option>VK_RECH</option><option>RMA_IH</option><option>RMA_AH</option><option>RMA_AT</option><option>INV_DIV</option><option>EK_EDI</option></select></td></tr>";
        $o_cont .= "</table><br><br>";                
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"8\" align=\"center\"><br><input type=\"submit\" value=\" Buchen \"><br><br></td></tr>";
        $o_cont .= "<tr><td colspan=\"8\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Letzte Buchungen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Artikelnr.</td><td>&nbsp;Artikelname</td><td>&nbsp;Seriennummer</td><td>&nbsp;Status (alt)</td><td>&nbsp;Status (neu)</td><td>&nbsp;Datum</td><td>&nbsp;Erstellt</td></tr>";
        foreach($data as $row)
          {
            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$row['ARTNUM']."</td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ART_SNR']."</td><td>&nbsp;".$row['O_STATUS']."</td><td>&nbsp;".$row['N_STATUS']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$row['ARTNUM']."</td><td>&nbsp;".$row['NAME']."</td><td>&nbsp;".$row['ART_SNR']."</td><td>&nbsp;".$row['O_STATUS']."</td><td>&nbsp;".$row['N_STATUS']."</td><td align=\"right\">".$row['DATUM']."</td><td align=\"right\">".$row['ERSTELLT']."</td></tr>";
              }

          }        
        $o_cont .= "</form></table>";

      }
    elseif($_GET['action']=="check")
      {
        // Header: main.php?section=".$_GET['section']."&module=sn&action=check

        // Plausibilitätsprüfung
        
        $error = "";
        $ercnt = 0;
        
        if(!$_POST['ARTNUM'])
          {
            $ercnt++;
            $error .= "Keine Artikelnummer angegeben.<br>";
          }
        else
          {
            if(!$art_id = mysql_query("SELECT REC_ID FROM ARTIKEL WHERE ARTNUM=".$_POST['ARTNUM'], $db_id))
              {
                $ercnt++;
                $error .= "Artikelnummer nicht in Datenbank vorhanden.<br>";                  
              }
            else
              {
                // Artikelid für nächsten Check sichern
                $tmpid = mysql_fetch_array($art_id, MYSQL_ASSOC);
                mysql_free_result($art_id);
              }
          }
        if(!$_POST['SERNUM'])
          {
            $ercnt++;
            $error .= "Keine Seriennummer angegeben.<br>";
          }     
        else
          {
            if(!$snum_id = mysql_query("SELECT SNUM_ID FROM ARTIKEL_SERNUM WHERE ARTIKEL_ID=".$tmpid['REC_ID']." AND SERNUMMER='".$_POST['SERNUM']."'", $db_id))
              {
                $ercnt++;
                $error .= "Seriennummer nicht in Datenbank vorhanden.<br>";                  
              }
          }
        
        // Keine Fehler aufgetreten -> weiter
        
        if(!$ercnt)
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="Die eingegebenen Daten scheinen plausibel zu sein. Keine Fehler gefunden.";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?section=".$_GET['section']."&module=sn&action=submit\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"ARTNUM\" value=\"".$_POST['ARTNUM']."\">
                         <input type=\"hidden\" name=\"SERNUM\" value=\"".$_POST['SERNUM']."\">
                         <input type=\"hidden\" name=\"STATUS\" value=\"".$_POST['STATUS']."\">
                         <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Zur&uuml;ck\" onClick=\"history.back()\">Zur&uuml;ck</button>&nbsp;&nbsp;&nbsp;&nbsp;<input type=\"submit\" name=\"submit\" value=\"Weiter\">
                        </form>
                        </td></tr></table>";
            $o_cont .= "<br><br><br><br><br><br><br><br>";
            $o_cont .= "</td></tr></table>";        
          
          }
        else
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aufgetretene Fehler (".$ercnt."):</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">";
            $o_cont .= $error;
            $o_cont .= "</td></tr></table>";
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?module=sn&action=new\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"ARTNUM\" value=\"".$_POST['ARTNUM']."\">
                         <input type=\"hidden\" name=\"SERNUM\" value=\"".$_POST['SERNUM']."\">
                         <div align=\"center\"><input type=\"submit\" name=\"new\" value=\"Korrektur\">
                        </form>
                        </td></tr></table>";
            $o_cont .= "<br><br><br><br><br><br><br><br>";
            $o_cont .= "</td></tr></table>";        
          }
      }
    elseif($_GET['action']=="submit")
      {
        // Header: main.php?section=".$_GET['section']."&module=sn&action=submit
        
        // ArtikelID aus ARTIKEL holen
        
        $art_id = mysql_query("SELECT REC_ID FROM ARTIKEL WHERE ARTNUM=".$_POST['ARTNUM'], $db_id);
        $artikel = mysql_fetch_array($art_id, MYSQL_ASSOC);
        mysql_free_result($art_id);
        
        // SeriennummerID und STATUS aus ARTIKEL_SERNUM holen

        $snr_id = mysql_query("SELECT SNUM_ID, STATUS FROM ARTIKEL_SERNUM WHERE ARTIKEL_ID=".$artikel['REC_ID']." AND SERNUMMER='".$_POST['SERNUM']."'", $db_id);
        $snum = mysql_fetch_array($snr_id, MYSQL_ASSOC);
        mysql_free_result($snr_id);

        // Neuen Status in ARTIKEL_SERNUM eintragen
        
        mysql_query("UPDATE ARTIKEL_SERNUM SET STATUS='".$_POST['STATUS']."' WHERE SNUM_ID=".$snum['SNUM_ID'], $db_id);

        // Logeintrag in SN_AEND
        
        mysql_query("INSERT INTO ".$db_pref."SN_AEND SET ART_ID='".$artikel['REC_ID']."', SNR_ID='".$snum['SNUM_ID']."', O_STATUS='".$snum['STATUS']."', N_STATUS='".$_POST['STATUS']."', ERSTELLT='".$usr_name."', DATUM=CURDATE()", $db_id);

        // Bericht ausgeben
    
        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">
                   <br><br><br><br>
                   Buchung erfolgreich durchgef&uuml;hrt!
                   <br><br><br><br>
                   <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                   <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                   <tr><td bgcolor=\"#808080\" align=\"left\">
                    <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Weiter\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=sn&action=new'\">Weiter</button>
                   </td></tr></table>
                   <br><br><br><br><br><br><br><br>
                   </td></tr></table>";
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