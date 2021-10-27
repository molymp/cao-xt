<?php

$o_head = "Bestands&auml;nderungen";
$o_navi = "";
$now = time();

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
    if((!$_GET['action']) || ($_GET['action']=="new"))
      {
        // Header: main.php?section=".$_GET['section']."&module=best&action=new
        $res_id = mysql_query("SELECT ID FROM ".$db_pref."BEST_AEND WHERE 1 ORDER BY ID DESC LIMIT 10", $db_id);
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
        
        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><form action=\"main.php?section=".$_GET['section']."&module=best&action=check\" method=\"post\">";
        $o_cont .= "<tr><td colspan=\"3\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Quelle</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td><td colspan=\"5\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Daten</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td colspan=\"3\" bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Bestand:</td><td><select name=\"QUELLE\" size=\"1\"><option>Lager</option><option>Eigenbestand</option><option>Reparaturbestand</option></select></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Konto:</td><td><input type=\"text\" name=\"KONTO\" size=\"30\"></td></tr>";
        $o_cont .= "</table>"; 
        $o_cont .= "<br><br>";
        $o_cont .= "</td><td colspan=\"5\" rowspan=\"3\" bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Artikel-Nr.:</td><td><input type=\"text\" name=\"ARTNUM\" size=\"30\" value=\"".$_POST['ARTNUM']."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Anzahl:</td><td><input type=\"text\" name=\"ANZAHL\" size=\"3\" value=\"".$_POST['ANZAHL']."\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\" valign=\"top\">Kommentar:</td><td><textarea name=\"KOMMENTAR\" cols=\"50\" rows=\"5\">".$_POST['KOMMENTAR']."</textarea></td></tr>";
        $o_cont .= "</table>";        
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr><td colspan=\"3\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Ziel</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr><td colspan=\"3\" bgcolor=\"#ffffdd\" valign=\"top\">";
        $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Bestand:</td><td><select name=\"ZIEL\" size=\"1\"><option>Lager</option><option selected>Eigenbestand</option><option>Reparaturbestand</option><option>Verlust</option></select></td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"100\">Gegenkonto:</td><td><input type=\"text\" name=\"GKONTO\" size=\"30\"></td></tr>";
        $o_cont .= "</table><br><br>";                
        $o_cont .= "</td></tr>";
        $o_cont .= "<tr bgcolor=\"#ffffdd\"><td colspan=\"8\" align=\"center\"><br><input type=\"submit\" value=\" Buchen \"><br><br></td></tr>";
        $o_cont .= "<tr><td colspan=\"8\" bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Letzte Buchungen</b><img src=\"images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
        $o_cont .= "<tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Artikelnr.</td><td>&nbsp;Artikelname</td><td>&nbsp;Anzahl</td><td>&nbsp;Quelle</td><td>&nbsp;Ziel</td><td>&nbsp;Datum</td><td>&nbsp;Erstellt</td></tr>";
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
        $o_cont .= "</form></table>";

      }
    elseif($_GET['action']=="check")
      {
        // Header: main.php?section=".$_GET['section']."&module=best&action=check

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
                $error .= "Artikelnummer nicht vorhanden.<br>";                  
              }
          }
        if(!$_POST['KOMMENTAR'])
          {
            $ercnt++;
            $error .= "Kein Kommentar angegeben.<br>";
          }
        else
          {
            $_POST['KOMMENTAR'] = stripslashes($_POST['KOMMENTAR']);
            $_POST['KOMMENTAR'] = htmlspecialchars($_POST['KOMMENTAR'], ENT_QUOTES);
          }
        if(!$_POST['ANZAHL'])
          {
            $ercnt++;
            $error .= "Keine Anzahl angegeben.<br>";
          }        
        if($_POST['ANZAHL']<0)
          {
            $ercnt++;
            $error .= "Negative Anzahl angegeben.<br>";
          }        
        if($_POST['QUELLE'] == $_POST['ZIEL'])
          {
            $ercnt++;
            $error .= "Bestand kann nicht auf sich selbst gebucht werden.<br>";
          }            
        
	// Hinweise generieren, leere Variablen füllen
	
	$msage = "";
	$mscnt = 0;

        if($_POST['KONTO'] == "")
          {
            $mscnt++;
            $msage .= "Keine FiBu-Konto angegeben.<br>";
            $_POST['KONTO'] = 0;
          }
        if($_POST['GKONTO'] == "")
          {
            $mscnt++;
            $msage .= "Keine FiBu-Gegenkonto angegeben.<br>";
            $_POST['GKONTO'] = 0;
          }

        // Keine Fehler aufgetreten -> weiter
        
        if(!$ercnt)
          {
            $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">";
            $o_cont .= "<br><br><br><br>";
            if($mscnt)
              {
                $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                            <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Hinweise (".$mscnt."):</h1></td></tr>
                            <tr><td bgcolor=\"#808080\" align=\"left\">";
                $o_cont .= $msage;
                $o_cont .= "</td></tr></table>";
              }
            else
              {
                $o_cont .="Die eingegebenen Daten scheinen plausibel zu sein. Keine Fehler gefunden.";
              }
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?section=".$_GET['section']."&module=best&action=submit\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"ARTNUM\" value=\"".$_POST['ARTNUM']."\">
                         <input type=\"hidden\" name=\"KOMMENTAR\" value=\"".$_POST['KOMMENTAR']."\">
                         <input type=\"hidden\" name=\"ANZAHL\" value=\"".$_POST['ANZAHL']."\">
                         <input type=\"hidden\" name=\"QUELLE\" value=\"".$_POST['QUELLE']."\">
                         <input type=\"hidden\" name=\"ZIEL\" value=\"".$_POST['ZIEL']."\">
                         <input type=\"hidden\" name=\"KONTO\" value=\"".$_POST['KONTO']."\">
                         <input type=\"hidden\" name=\"GKONTO\" value=\"".$_POST['GKONTO']."\">
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
            if($mscnt)
              {
                $o_cont .= "<br><br>";
                $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                            <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Hinweise (".$mscnt."):</h1></td></tr>
                            <tr><td bgcolor=\"#808080\" align=\"left\">";
                $o_cont .= $msage;
                $o_cont .= "</td></tr></table>";
              }
            $o_cont .= "<br><br><br><br>";
            $o_cont .="<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                        <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                        <tr><td bgcolor=\"#808080\" align=\"left\">
                        <form action=\"main.php?module=best&action=new\" method=\"post\"><br>
                         <input type=\"hidden\" name=\"ARTNUM\" value=\"".$_POST['ARTNUM']."\">
                         <input type=\"hidden\" name=\"KOMMENTAR\" value=\"".$_POST['KOMMENTAR']."\">
                         <input type=\"hidden\" name=\"ANZAHL\" value=\"".$_POST['ANZAHL']."\">
                         <div align=\"center\"><input type=\"submit\" name=\"new\" value=\"Korrektur\">
                        </form>
                        </td></tr></table>";
            $o_cont .= "<br><br><br><br><br><br><br><br>";
            $o_cont .= "</td></tr></table>";        
          }
      }
    elseif($_GET['action']=="submit")
      {
        // Header: main.php?section=".$_GET['section']."&module=best&action=submit
        
        // ArtikelID und Menge aus ARTIKEL holen
        
        $art_id = mysql_query("SELECT REC_ID, MENGE_AKT FROM ARTIKEL WHERE ARTNUM=".$_POST['ARTNUM'], $db_id);
        $artikel = mysql_fetch_array($art_id, MYSQL_ASSOC);
        
        // ArtikelID in BEST vorhanden? Falls nicht -> anlegen!
 
        if($res_id = mysql_query("SELECT E_BEST, RMA_BEST FROM ".$db_pref."BEST WHERE ART_ID=".$artikel['REC_ID'], $db_id))
          {
            $test = mysql_num_rows($res_id);
            $e_data = mysql_fetch_array($res_id, MYSQL_ASSOC);
            mysql_free_result($res_id);
            
            if($test==0)
              {
                $e_data['E_BEST'] = 0;
                $e_data['RMA_BEST'] = 0;
                mysql_query("INSERT INTO ".$db_pref."BEST SET ART_ID=".$artikel['REC_ID'], $db_id);                  
              }
          }
        else
          {
            $e_data['E_BEST'] = 0;
            $e_data['RMA_BEST'] = 0;
            mysql_query("INSERT INTO ".$db_pref."BEST SET ART_ID=".$artikel['REC_ID'], $db_id);
          }

        // Bestand mit ANZAHL verrechnen und in entsprechende Tabelle eintragen
        
        if($_POST['QUELLE']=="Lager")
          {
            mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($artikel['MENGE_AKT']-$_POST['ANZAHL'])." WHERE REC_ID=".$artikel['REC_ID'], $db_id);
            $QUELLE = "LAGER";
          }
        elseif($_POST['QUELLE']=="Eigenbestand")
          {
            mysql_query("UPDATE ".$db_pref."BEST SET E_BEST=".($e_data['E_BEST']-$_POST['ANZAHL'])." WHERE ART_ID=".$artikel['REC_ID'], $db_id);
            $QUELLE = "E_BEST";
          }
        elseif($_POST['QUELLE']=="Reparaturbestand")
          {
            mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($e_data['RMA_BEST']-$_POST['ANZAHL'])." WHERE ART_ID=".$artikel['REC_ID'], $db_id);
            $QUELLE = "RMA_BEST";
          }

        if($_POST['ZIEL']=="Lager")
          {
            mysql_query("UPDATE ARTIKEL SET MENGE_AKT=".($artikel['MENGE_AKT']+$_POST['ANZAHL'])." WHERE REC_ID=".$artikel['REC_ID'], $db_id);
            $ZIEL = "LAGER";
          }
        elseif($_POST['ZIEL']=="Eigenbestand")
          {
            mysql_query("UPDATE ".$db_pref."BEST SET E_BEST=".($e_data['E_BEST']+$_POST['ANZAHL'])." WHERE ART_ID=".$artikel['REC_ID'], $db_id);
            $ZIEL = "E_BEST";
          }
        elseif($_POST['ZIEL']=="Reparaturbestand")
          {
            mysql_query("UPDATE ".$db_pref."BEST SET RMA_BEST=".($e_data['RMA_BEST']+$_POST['ANZAHL'])." WHERE ART_ID=".$artikel['REC_ID'], $db_id);
            $ZIEL = "RMA_BEST";
          }
        else
          {
            $ZIEL = "NULL";
          }

        // Logeintrag in BEST_AEND
        
        mysql_query("INSERT INTO ".$db_pref."BEST_AEND SET ART_ID='".$artikel['REC_ID']."', ANZAHL='".$_POST['ANZAHL']."', KONTO='".$_POST['KONTO']."', GKONTO='".$_POST['GKONTO']."', LAGER_QUELLE='".$QUELLE."', LAGER_ZIEL='".$ZIEL."', KOMMENTAR='".$_POST['KOMMENTAR']."', ERSTELLT='".$usr_name."', DATUM=CURDATE()", $db_id);

        // Bericht ausgeben
    
        $o_cont = "<table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr><td align=\"center\" valign=\"middle\" style=\"background: #ffffdd;\">
                   <br><br><br><br>
                   Buchung erfolgreich durchgef&uuml;hrt!
                   <br><br><br><br>
                   <table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                   <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Aktion:</h1></td></tr>
                   <tr><td bgcolor=\"#808080\" align=\"left\">
                    <div align=\"center\"><button name=\"back\" type=\"button\" value=\"Weiter\" onClick=\"self.location.href='main.php?section=".$_GET['section']."&module=best&action=new'\">Weiter</button>
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