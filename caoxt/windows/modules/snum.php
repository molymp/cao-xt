<?php

$o_head = "Seriennummern zuweisen";
$o_body = "";

function print_main($journalpos_id, $db_id)
  {
    $db_res = mysql_query("SELECT ARTIKEL_SERNUM.SERNUMMER AS SERNUM, ARTIKEL.KURZNAME AS NAME, ARTIKEL.ARTNUM AS ARTNR, JOURNALPOS_SERNUM.* FROM JOURNALPOS_SERNUM
    		                      LEFT JOIN ARTIKEL_SERNUM ON JOURNALPOS_SERNUM.SNUM_ID = ARTIKEL_SERNUM.SNUM_ID
    		                      LEFT JOIN ARTIKEL ON JOURNALPOS_SERNUM.ARTIKEL_ID = ARTIKEL.REC_ID
    		                      WHERE JOURNALPOS_ID=".$journalpos_id, $db_id);
    $data = array();
    $res_num = mysql_num_rows($db_res);
    for($i=0; $i<$res_num; $i++)
      {
      	array_push($data, mysql_fetch_array($db_res, MYSQL_ASSOC));
      }
    mysql_free_result($db_res);

    // Stammdaten ausgeben

    $res_id0 = mysql_query("SELECT ARTIKEL.KURZNAME AS NAME, ARTIKEL.ARTNUM AS NUMMER,JOURNALPOS.ARTIKEL_ID FROM JOURNALPOS INNER JOIN ARTIKEL ON ARTIKEL.REC_ID = JOURNALPOS.ARTIKEL_ID WHERE JOURNALPOS.REC_ID=".$journalpos_id, $db_id);
    $res0 = mysql_fetch_array($res_id0, MYSQL_ASSOC);
    mysql_free_result($res_id0);

    $color = 0;
    $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
    		    <tr bgcolor=\"#d4d0c8\"><td width=\"100\">&nbsp;<b>Artikel-Nr.:</b></td><td>&nbsp;".$res0['NUMMER']."</td></tr>
    		    <tr bgcolor=\"#d4d0c8\"><td width=\"100\">&nbsp;<b>Name:</b></td><td>&nbsp;".$res0['NAME']."</td></tr>
    		   </table>";
    $o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"../images/leer.gif\"></td><td>&nbsp;Seriennummern</td><td width=\"100\">&nbsp;Optionen</td></tr>";

    // Bereits eingetragene Seriennummern ausgeben

    foreach($data as $row)
      {
        $color++;
        if($color%2)
          {
            $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;".$row['SERNUM']."</td><td align=\"center\"><a href=\"main.php?module=snum&action=delete&target=".$journalpos_id."&snum_id=".$row['SNUM_ID']."\">entfernen</a></td></tr>";
          }
        else
          {
          	$o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;".$row['SERNUM']."</td><td align=\"center\"><a href=\"main.php?module=snum&action=delete&target=".$journalpos_id."&snum_id=".$row['SNUM_ID']."\">entfernen</a></td></tr>";
          }
      }
    $o_cont .= "</table>";

    // Weitere verfügbare Seriennummer eintragen?

    $res_id1 = mysql_query("SELECT SERNUMMER FROM ARTIKEL_SERNUM WHERE ARTIKEL_ID=".$res0['ARTIKEL_ID']." AND STATUS='LAGER'", $db_id);
    $num1 = mysql_num_rows($res_id1);
    $res1 = array();
    for($i=0; $i<$num1; $i++)
      {
        $tmp = mysql_fetch_array($res_id1, MYSQL_NUM);
        array_push($res1, $tmp[0]);
      }
    mysql_free_result($res_id1);

    // Filter, diese Seriennummern sind bereits im VK verbraucht. Quelle 5 (EK) spielt hier keine Rolle

    $res_id2 = mysql_query("SELECT DISTINCT ARTIKEL_SERNUM.SERNUMMER FROM JOURNALPOS_SERNUM
                            LEFT JOIN ARTIKEL_SERNUM ON JOURNALPOS_SERNUM.SNUM_ID = ARTIKEL_SERNUM.SNUM_ID
                            WHERE JOURNALPOS_SERNUM.ARTIKEL_ID=".$res0['ARTIKEL_ID']." AND QUELLE!=5", $db_id);
    $num2 = mysql_num_rows($res_id2);
    $res2 = array();
    for($i=0; $i<$num2; $i++)
      {
        $tmp = mysql_fetch_array($res_id2, MYSQL_NUM);
        array_push($res2, $tmp[0]);
      }
    mysql_free_result($res_id2);

    $result = array_diff($res1, $res2);

    // Auswahl generieren, wenn noch was auszuwählen ist

   if(count($result))
     {
       $o_cont .= "<br><br><form action=\"main.php?module=snum&action=add&target=".$journalpos_id."\" method=\"post\">
       		       <div align=\"center\">
       		       <table width=\"480\" cellpadding=\"0\" cellspacing=\"1\">
        		     <tr bgcolor=\"#d4d0c8\"><td align=\"right\"><select name=\"snum\" style=\"width:380px;\">";
       foreach($result as $sernum)
         {
         	$o_cont .= "<option>".$sernum."</option>";
         }
       $o_cont .= "</select></td><td width=\"100\" align=\"center\"><input type=\"submit\" value=\"Hinzuf&uuml;gen\"></td></tr>
        		   </table></div></form>";
     }
    return $o_cont;
  }


// HAUPTPROGRAMM

if($usr_rights)
  {
    if($_GET['action']=="delete")
      {
        if(!mysql_query("DELETE FROM JOURNALPOS_SERNUM WHERE JOURNALPOS_ID='".$_GET['target']."' AND SNUM_ID='".$_GET['snum_id']."'", $db_id))
          {
          	echo mysql_error($db_id);
          }
        $o_cont = print_main($_GET['target'], $db_id);
      }
    elseif($_GET['action']=="add")
      {
        $res_id1 = mysql_query("SELECT JOURNAL_ID, ARTIKEL_ID FROM JOURNALPOS WHERE REC_ID='".$_GET['target']."' LIMIT 1", $db_id);
        $res1 = mysql_fetch_array($res_id1, MYSQL_ASSOC);
        mysql_free_result($res_id1);
        $res_id2 = mysql_query("SELECT SNUM_ID FROM ARTIKEL_SERNUM WHERE ARTIKEL_ID='".$res1['ARTIKEL_ID']."' AND SERNUMMER='".$_POST['snum']."'", $db_id);
        $res2 = mysql_fetch_array($res_id2, MYSQL_ASSOC);
        mysql_free_result($res_id2);

        if($res2['SNUM_ID'])
          {
            if(!mysql_query("INSERT INTO JOURNALPOS_SERNUM SET QUELLE='13', JOURNALPOS_ID='".$_GET['target']."', SNUM_ID='".$res2['SNUM_ID']."', ARTIKEL_ID='".$res1['ARTIKEL_ID']."', JOURNAL_ID='".$res1['JOURNAL_ID']."'", $db_id))
              {
          	    echo mysql_error();
              }
          }
        $o_cont = print_main($_GET['target'], $db_id);
      }
    else
      {
      	$o_cont = print_main($_GET['target'], $db_id);
      }
  }
else
  {
    $o_cont = "<div align=\"center\"><br><br><br><h1>Zugriff verweigert!</h1><br><br><br></div>";
  }

?>