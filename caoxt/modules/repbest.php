<?php

$o_head = "Reparaturbestand";
$o_navi = "";

if($usr_rights)
  {
   if($db_res = mysql_query("SELECT ART_ID, RMA_BEST as Bestand FROM ".$db_pref."BEST WHERE RMA_BEST!=0", $db_id))
     {
       $number = mysql_num_rows($db_res);
     }
   else
     {
       $number = 0;
     }

   $result = array();
    
   for($i=0; $i<$number; $i++)
     {
       array_push($result, mysql_fetch_array($db_res, MYSQL_ASSOC));
     }
   
   if($number)
     {
       mysql_free_result($db_res);
     }
     
   for($i=0; $i<$number; $i++)
     {
       $db_res = mysql_query("SELECT WARENGRUPPE as Warengruppe, ARTNUM as Artikelnummer, KURZNAME as Name, EK_PREIS as NettoEK, VK4 as NettoVK, (".$result[$i]['Bestand']."*EK_PREIS) as Gesamtwert FROM ARTIKEL WHERE REC_ID=".$result[$i]['ART_ID'], $db_id);   
       $tmp = mysql_fetch_array($db_res, MYSQL_ASSOC);
       mysql_free_result($db_res);
       
       $result[$i]['Artikelnummer'] = $tmp['Artikelnummer'];
       $result[$i]['Name'] = $tmp['Name'];
       $result[$i]['NettoEK'] = $tmp['NettoEK'];
       $result[$i]['NettoVK'] = $tmp['NettoVK'];
       $result[$i]['Gesamtwert'] = $tmp['Gesamtwert'];
     }

   $Name = array();
   $Warengruppe = array();

   foreach($result as $key => $row)
     {
       $Warengruppe[$key]  = $row['Warengruppe'];
       $Name[$key] = $row['Name'];
     }

   array_multisort($Name, SORT_ASC, $Warengruppe, SORT_ASC, $result);
   
   $a_anzahl = 0;
   $a_wert = 0;
   $color = 0;

   $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td>&nbsp;Artikelnummer</td><td>&nbsp;Name</td><td>&nbsp;NettoEK</td><td>&nbsp;NettoVK</td><td>&nbsp;Bestand</td><td>&nbsp;Gesamtwert</td></tr>";
   foreach($result as $row)
     {
       $color++;
       $a_anzahl += $row['Bestand'];
       $a_wert += $row['Gesamtwert'];
       if($color%2)
         {
           $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$row[Artikelnummer]."</td><td>&nbsp;".$row[Name]."</td><td align=\"right\">&nbsp;".number_format($row[NettoEK], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[NettoVK], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[Bestand], 0)."</td><td align=\"right\">&nbsp;".number_format($row[Gesamtwert], 2, ",", ".")." &euro;</td></tr>";
         }
       else
         {
           $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td><td>&nbsp;".$row[Artikelnummer]."</td><td>&nbsp;".$row[Name]."</td><td align=\"right\">&nbsp;".number_format($row[NettoEK], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[NettoVK], 2, ",", ".")." &euro;</td><td align=\"right\">&nbsp;".number_format($row[Bestand], 0)."</td><td align=\"right\">&nbsp;".number_format($row[Gesamtwert], 2, ",", ".")." &euro;</td></tr>";
         }

     }
  
   $o_cont .= "</table></td></tr>";
  
   $o_cont .= "<tr><td></td><td bgcolor=\"#ffffff\" align=\"center\"><br><br>&nbsp;Es sind insgesamt <b>".$a_anzahl." Artikel</b> mit einem EK-Gesamtwert von <b>".number_format($a_wert, 2, ",", ".")." &euro;</b> im Reparaturbestand.<br><br></div>";
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>