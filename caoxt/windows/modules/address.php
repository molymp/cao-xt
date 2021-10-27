<?php

$o_head = "Adressen";
$o_java = "function reset_all()
           {
            parent.navi.location.href = 'navi.php?module=address&target=".$_GET['target']."';
            self.location.href = 'main.php?module=address&target=".$_GET['target']."';
           }";

$o_body = "";
$o_navi = "<table width=\"4\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td width=\"1\" align=\"center\" valign=\"middle\" style=\"background: #808080;\"><a href=\"javascript:reset_all()\" style=\"background: #808080; color: #ffffff\" onmouseover=\"javascript:style.backgroundColor='#d4d0c8';style.color='#000000'\" onmouseout=\"javascript:style.backgroundColor='#808080';style.color='#ffffff'\">&nbsp;Auswahl&nbsp;</a></td></tr></table>";

if (!function_exists("str_split"))			// Abwärtskompatibilität zu PHP4
  {
    function str_split($str, $nr)
      {
         return array_slice(split("-l-", chunk_split($str, $nr, '-l-')), 0, -1);
      }
  }

function print_main($data, $group, $liefart, $zahlart, $type, $target, $id)
  {
    if(!$data['PR_EBENE']) $data['PR_EBENE'] = 5;
    $data['NET_SKONTO'] = number_format($data['NET_SKONTO'], 2, ',', '')."%";

    $o_cont .= "<form action=\"main.php?module=address&action=detail&target=".$target."&id=".$id."\" method=\"post\" name=\"SOURCE\">";
    $o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"80%\"><b>&nbsp;Suchbegriffe</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"20%\"><b>&nbsp;Kommunikation</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Suchbegriff:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"MATCHCODE\" style=\"width:395px;\" value=\"".htmlspecialchars($data['MATCHCODE'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Kunden-Nr.:</td><td align=\"right\"><input type=\"text\" name=\"KUNNUM1\" style=\"width:90px;\" value=\"".$data['KUNNUM1']."\" readonly></td><td valign=\"middle\" align=\"right\" width=\"100\">Ku.-Nr. vom Lief.:</td><td align=\"right\"><input type=\"text\" name=\"KUNNUM2\" style=\"width:195px;\" value=\"".htmlspecialchars($data['KUNNUM2'])."\"></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td><td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"5\">";
    $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Telefon:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"TELE1\" style=\"width:195px;\" value=\"".htmlspecialchars($data['TELE1'])."\"></td><td width=\"20\">&nbsp;</td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Telefon 2:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"TELE2\" style=\"width:195px;\" value=\"".htmlspecialchars($data['TELE2'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Telefax:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"FAX\" style=\"width:195px;\" value=\"".htmlspecialchars($data['FAX'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Mobilfunk:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"FUNK\" style=\"width:195px;\" value=\"".htmlspecialchars($data['FUNK'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">eMail:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"EMAIL\" style=\"width:195px;\" value=\"".htmlspecialchars($data['EMAIL'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">eMail 2:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"EMAIL2\" style=\"width:195px;\" value=\"".htmlspecialchars($data['EMAIL2'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Internet:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"INTERNET\" style=\"width:195px;\" value=\"".htmlspecialchars($data['INTERNET'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Diverses:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"DIVERSES\" style=\"width:195px;\" value=\"".htmlspecialchars($data['DIVERSES'])."\"></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Zuweisungen</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Gruppe:</td><td colspan=\"3\" align=\"right\"><select name=\"KUNDENGRUPPE_TXT\" size=\"1\" style=\"width:395px;\">";
    foreach($group as $row)
      {
        if($row['NUMMER']==$data['KUNDENGRUPPE'])
          {
            $o_cont .= "<option selected>".$row['NAME']."</option>";
          }
        else
          {
            $o_cont .= "<option>".$row['NAME']."</option>";
          }
      }
    $o_cont .= "</select></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Selektion:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"GRUPPE\" style=\"width:395px;\" value=\"".htmlspecialchars($data['GRUPPE'])."\"></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Anschrift</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Anrede:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"ANREDE\" style=\"width:395px;\" value=\"".htmlspecialchars($data['ANREDE'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name1:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME1\" style=\"width:395px;\" value=\"".htmlspecialchars($data['NAME1'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name2:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME2\" style=\"width:395px;\" value=\"".htmlspecialchars($data['NAME2'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name3:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME3\" style=\"width:395px;\" value=\"".htmlspecialchars($data['NAME3'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">z.Hd. von:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"ABTEILUNG\" style=\"width:395px;\" value=\"".htmlspecialchars($data['ABTEILUNG'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Strasse:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"STRASSE\" style=\"width:395px;\" value=\"".htmlspecialchars($data['STRASSE'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Land/PLZ/Ort:</td><td align=\"right\"><input type=\"text\" name=\"LAND\" style=\"width:20px;\" value=\"".htmlspecialchars($data['LAND'])."\"></td><td align=\"center\"><input type=\"text\" name=\"PLZ\" style=\"width:50px;\" value=\"".htmlspecialchars($data['PLZ'])."\"></td><td align=\"right\"><input type=\"text\" name=\"ORT\" style=\"width:310px;\" value=\"".htmlspecialchars($data['ORT'])."\"></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Info</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td><td bgcolor=\"#ffffdd\" valign=\"middle\"><b>&nbsp;Zahlungsbedingungen</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td></tr>";
    $o_cont .= "<tr><td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"right\"><textarea name=\"INFO\" cols=\"115\" rows=\"10\">".htmlspecialchars($data['INFO'])."</textarea></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td>";
    $o_cont .= "<td bgcolor=\"#ffffdd\" valign=\"top\">";
    $o_cont .= "<table width=\"300\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"right\" width=\"80%\" colspan=\"4\">Preisliste:</td><td align=\"center\"><select name=\"PR_EBENE_TXT\" size=\"1\">";
    for($i=1;$i<=5;$i++)
      {
        if($data['PR_EBENE']==$i)
          {
            $o_cont .= "<option selected>VK".$i."</option>";
          }
        else
          {
            $o_cont .= "<option>VK".$i."</option>";
          }
      }
    $o_cont .= "</select></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"left\" colspan=\"5\">Zahlungsziel:</td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\"><input type=\"text\" name=\"NET_SKONTO\" style=\"width:40px;\" value=\"".$data['NET_SKONTO']."\"> Skonto</td><td align=\"center\" colspan=\"2\"><input type=\"text\" name=\"NET_TAGE\" style=\"width:40px;\" value=\"".$data['NET_TAGE']."\"> Tage</td><td align=\"right\" colspan=\"2\">Netto: <input type=\"text\" name=\"BRT_TAGE\" style=\"width:40px;\" value=\"".$data['BRT_TAGE']."\"> Tage </td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Kunde-Versand:</td><td align=\"right\" colspan=\"4\"><select name=\"KUN_LIEFART_TXT\" size=\"1\" style=\"width:180px;\">";
    foreach($liefart as $row)
      {
        if($data['KUN_LIEFART']==$row['NUMMER'])
          {
            $o_cont .= "<option selected>".$row['NAME']."</option>";
          }
        else
          {
            $o_cont .= "<option>".$row['NAME']."</option>";
          }
      }
    $o_cont .= "</select></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td align=\"left\">Kunde-Zahlart:</td><td align=\"right\" colspan=\"4\"><select name=\"KUN_ZAHLART_TXT\" size=\"1\" style=\"width:180px;\">";
    foreach($zahlart as $row)
      {
        if($data['KUN_ZAHLART']==$row['NUMMER'])
          {
            $o_cont .= "<option selected>".$row['NAME']."</option>";
          }
        else
          {
            $o_cont .= "<option>".$row['NAME']."</option>";
          }
      }
    $o_cont .= "</select></td></tr>";
    $o_cont .= "</table>";
    $o_cont .= "</td></tr></table><input type=\"hidden\" name=\"TYPE\" value=\"".$type."\"><input type=\"hidden\" name=\"REC_ID\" value=\"".$id."\"></form>";


    return $o_cont;
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

        $query = "UPDATE ADRESSEN SET KUNNUM1='".$kunnum."', DEB_NUM='".$deb_num."' WHERE REC_ID=".$addr_id;
        //echo $query."<br>";
        if(!mysql_query($query, $db_id))
          {
            echo mysql_error($db_id)."<br>";
          }
      }
  }


function get_group($db_id)
  {
    $res_id = mysql_query("SELECT NAME, VAL_INT AS NUMMER FROM REGISTRY WHERE MAINKEY='MAIN\\\\ADDR_HIR' ORDER BY VAL_INT ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_zahlart($db_id)
  {
    $res_id = mysql_query("SELECT NAME, REC_ID AS NUMMER FROM ZAHLUNGSARTEN WHERE AKTIV_FLAG='Y' ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

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

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function address_update($data, $id, $db_id, $type)
  {
    $gruppe = get_group($db_id);					// ID der Kundengruppe holen
    foreach($gruppe as $set)
      {
        if($set['NAME']==$data['KUNDENGRUPPE_TXT'])
          {
            $data['KUNDENGRUPPE'] = $set['NUMMER'];
          }
      }

    $data['PR_EBENE'] = str_replace("VK", "", $data['PR_EBENE_TXT']);	// Preisgruppe holen

    $data['NET_SKONTO'] = str_replace(",", ".", $data['NET_SKONTO']);	// Skonto formatieren
    $data['NET_SKONTO'] = str_replace("%", "", $data['NET_SKONTO']);

    $zahlart = get_zahlart($db_id);					// ID der Zahlart holen
    foreach($zahlart as $set)
      {
        if($set['NAME']==$data['KUN_ZAHLART_TXT'])
          {
            $data['KUN_ZAHLART'] = $set['NUMMER'];
          }
      }

    $liefart = get_liefart($db_id);					// ID der Versandart holen
    foreach($liefart as $set)
      {
        if($set['NAME']==$data['KUN_LIEFART_TXT'])
          {
            $data['KUN_LIEFART'] = $set['NUMMER'];
          }
      }

    $query = "UPDATE ADRESSEN SET
                MATCHCODE='".strtoupper(addslashes($data['MATCHCODE']))."',
                KUNNUM2='".addslashes($data['KUNNUM2'])."',
                KUNDENGRUPPE ='".$data['KUNDENGRUPPE']."',
                GRUPPE='".addslashes($data['GRUPPE'])."',
                TELE1='".addslashes($data['TELE1'])."',
                TELE2='".addslashes($data['TELE2'])."',
                FAX='".addslashes($data['FAX'])."',
                FUNK='".addslashes($data['FUNK'])."',
                EMAIL='".addslashes($data['EMAIL'])."',
                EMAIL2='".addslashes($data['EMAIL2'])."',
                INTERNET='".addslashes($data['INTERNET'])."',
                DIVERSES='".addslashes($data['DIVERSES'])."',
                ANREDE='".addslashes($data['ANREDE'])."',
                NAME1='".addslashes($data['NAME1'])."',
                NAME2='".addslashes($data['NAME2'])."',
                NAME3='".addslashes($data['NAME3'])."',
                ABTEILUNG='".addslashes($data['ABTEILUNG'])."',
                STRASSE='".addslashes($data['STRASSE'])."',
                LAND='".addslashes($data['LAND'])."',
                PLZ='".addslashes($data['PLZ'])."',
                ORT='".addslashes($data['ORT'])."',
                INFO='".addslashes($data['INFO'])."',
                PR_EBENE='".$data['PR_EBENE']."',
                NET_SKONTO='".$data['NET_SKONTO']."',
                NET_TAGE='".$data['NET_TAGE']."',
                BRT_TAGE='".$data['BRT_TAGE']."',
                KUN_ZAHLART='".$data['KUN_ZAHLART']."',
                KUN_LIEFART='".$data['KUN_LIEFART']."',
                GEAEND=CURDATE(),
                GEAEND_NAME='".$data['GEAEND_NAME']."'
               WHERE REC_ID=".$id;

    // echo $query."<br><br>";

    if(!mysql_query($query, $db_id))
      {
        echo mysql_error($db_id)."<br>";
        return 0;
      }
    else
      {
        if($type=="krma")	// Kundennummer generieren? RMA-Formular
          {
          	$res_id = mysql_query("SELECT KUNNUM1 FROM ADRESSEN WHERE REC_ID=".$id, $db_id);
          	$result = mysql_fetch_array($res_id, MYSQL_ASSOC);
          	mysql_free_result($res_id);
          	set_kunnum($id, $result['KUNNUM1'], $db_id);
          }
        return 1;
      }
  }

function address_add($data, $db_id, $type)
  {
    $gruppe = get_group($db_id);					// ID der Kundengruppe holen
    foreach($gruppe as $set)
      {
        if($set['NAME']==$data['KUNDENGRUPPE_TXT'])
          {
            $data['KUNDENGRUPPE'] = $set['NUMMER'];
          }
      }

    $data['PR_EBENE'] = str_replace("VK", "", $data['PR_EBENE_TXT']);	// Preisgruppe holen

    $data['NET_SKONTO'] = str_replace(",", ".", $data['NET_SKONTO']);	// Skonto formatieren
    $data['NET_SKONTO'] = str_replace("%", "", $data['NET_SKONTO']);

    $zahlart = get_zahlart($db_id);					// ID der Zahlart holen
    foreach($zahlart as $set)
      {
        if($set['NAME']==$data['KUN_ZAHLART_TXT'])
          {
            $data['KUN_ZAHLART'] = $set['NUMMER'];
          }
      }

    $liefart = get_liefart($db_id);					// ID der Versandart holen
    foreach($liefart as $set)
      {
        if($set['NAME']==$data['KUN_LIEFART_TXT'])
          {
            $data['KUN_LIEFART'] = $set['NUMMER'];
          }
      }

    if(!$data['LAND']) $data['LAND'] = "DE";

    $query = "INSERT INTO ADRESSEN SET
                MATCHCODE='".strtoupper(addslashes($data['MATCHCODE']))."',
                KUNNUM2='".addslashes($data['KUNNUM2'])."',
                KUNDENGRUPPE ='".$data['KUNDENGRUPPE']."',
                GRUPPE='".addslashes($data['GRUPPE'])."',
                TELE1='".addslashes($data['TELE1'])."',
                TELE2='".addslashes($data['TELE2'])."',
                FAX='".addslashes($data['FAX'])."',
                FUNK='".addslashes($data['FUNK'])."',
                EMAIL='".addslashes($data['EMAIL'])."',
                EMAIL2='".addslashes($data['EMAIL2'])."',
                INTERNET='".addslashes($data['INTERNET'])."',
                DIVERSES='".addslashes($data['DIVERSES'])."',
                ANREDE='".addslashes($data['ANREDE'])."',
                NAME1='".addslashes($data['NAME1'])."',
                NAME2='".addslashes($data['NAME2'])."',
                NAME3='".addslashes($data['NAME3'])."',
                ABTEILUNG='".addslashes($data['ABTEILUNG'])."',
                STRASSE='".addslashes($data['STRASSE'])."',
                LAND='".addslashes($data['LAND'])."',
                PLZ='".addslashes($data['PLZ'])."',
                ORT='".addslashes($data['ORT'])."',
                INFO='".addslashes($data['INFO'])."',
                PR_EBENE='".$data['PR_EBENE']."',
                NET_SKONTO='".$data['NET_SKONTO']."',
                NET_TAGE='".$data['NET_TAGE']."',
                BRT_TAGE='".$data['BRT_TAGE']."',
                KUN_ZAHLART='".$data['KUN_ZAHLART']."',
                KUN_LIEFART='".$data['KUN_LIEFART']."',
                ERSTELLT=CURDATE(),
                ERST_NAME='".$data['GEAEND_NAME']."',
                GEAEND=CURDATE(),
                GEAEND_NAME='".$data['GEAEND_NAME']."'";

    // echo $query."<br><br>";

    if(!mysql_query($query, $db_id))
      {
        echo mysql_error($db_id)."<br>";
        return 0;
      }
    else
      {
        $insert_id = mysql_insert_id($db_id);

        if($type=="krma")	// Kundennummer generieren, RMA-Formular
          {
          	set_kunnum($insert_id, "", $db_id);
          }
        return $insert_id;
      }
  }


// HAUPTPROGRAMM

if($usr_rights)
  {
    if($_GET['action']=="detail")
      {
        if($_POST)		// Daten wurden eingegeben, Datenbank aktualisieren
          {
            if($_POST['TYPE']=="update")
              {
                $_POST['GEAEND_NAME'] = $usr_name;
                address_update($_POST, $_GET['id'], $db_id, $_GET['target']);
              }
            elseif($_POST['TYPE']=="add")
              {
                $_POST['ERST_NAME'] = $usr_name;
                $_POST['GEAEND_NAME'] = $usr_name;
                $_GET['id'] = address_add($_POST, $db_id, $_GET['target']);
              }
          }

        $res_id = mysql_query("SELECT * FROM ADRESSEN WHERE REC_ID=".$_GET['id'], $db_id);
        $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        $group = array();
        $liefart = array();
        $zahlart = array();
        $group = get_group($db_id);
        $liefart = get_liefart($db_id);
        $zahlart = get_zahlart($db_id);

        $o_cont = print_main($data, $group, $liefart, $zahlart, "update", $_GET['target'], $_GET['id']);

        $o_java .= "function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=address&target=".$_GET['target']."&id=".$_GET['id']."';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    elseif($_GET['action']=="add")
      {
        $data = array();
        $group = array();
        $liefart = array();
        $zahlart = array();
        $group = get_group($db_id);
        $liefart = get_liefart($db_id);
        $zahlart = get_zahlart($db_id);
        $data['PR_EBENE'] = 5;
        $data['KUN_LIEFART'] = 2;
        $data['KUN_ZAHLART'] = 2;

        $o_cont = print_main($data, $group, $liefart, $zahlart, "add", $_GET['target'], 'new');

        $o_java .= "
                   function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=address&target=".$_GET['target']."&id=new';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    else
      {
        // Suchparameter merken:

        if($_POST)
          {
            $_SESSION['addr_type'] = $_POST['type'];
            $_SESSION['addr_order'] = $_POST['order'];
            $_SESSION['addr_limit'] = $_POST['limit'];
            $_SESSION['addr_text'] = $_POST['text'];
          }

        // Suchparameter

        if($_POST['type']=="Suchbegriff")
          {
            $abfrage['type'] = "MATCHCODE";
          }
        elseif($_POST['type']=="Name")
          {
            $abfrage['type'] = "NAME1";
          }
        elseif($_POST['type']=="Kundennummer")
          {
            $abfrage['type'] = "KUNNUM1";
          }
        elseif($_POST['type']=="Ku.-Nr. bei Lief.")
          {
            $abfrage['type'] = "KUNNUM2";
          }
        elseif($_POST['type']=="Ort")
          {
            $abfrage['type'] = "ORT";
          }
        elseif($_POST['type']=="Strasse")
          {
            $abfrage['type'] = "STRASSE";
          }
        else
          {
            $abfrage['type'] = "REC_ID";
          }

        if($_POST['order']=="Absteigend")
          {
            $abfrage['order'] = "DESC";
          }
        else
          {
            $abfrage['order'] = "ASC";
          }

        if($_POST['limit'])
          {
            $abfrage['limit'] = $_POST['limit'];
          }
       else
          {
            $abfrage['limit'] = 50;
          }

        if($_POST['text'] && ($_POST['type']=="Name"))				// SQL-Abfragen basteln
          {
            $abfrage['text'] = "WHERE (";
            $begriffe = explode(" ", $_POST['text']);
            $reset = count($begriffe);

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(NAME1 LIKE '%".$begriffe[$num]."%') AND ";
                $num--;
              }
            $abfrage['text'] .= "(NAME1 LIKE '%".$begriffe[$num]."%')) OR (";

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(NAME2 LIKE '%".$begriffe[$num]."%') AND ";
                $num--;
              }
            $abfrage['text'] .= "(NAME2 LIKE '%".$begriffe[$num]."%')) OR (";

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(NAME3 LIKE '%".$begriffe[$num]."%') AND ";
                $num--;
              }
            $abfrage['text'] .= "(NAME3 LIKE '%".$begriffe[$num]."%'))";

            // echo $abfrage['text']."<br>";			// Debug
          }
        elseif($_POST['text'] && ($_POST['type']=="Suchbegriff"))
          {
            $abfrage['text'] = "WHERE (";
            $begriffe = explode(" ", $_POST['text']);
            $reset = count($begriffe);

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(MATCHCODE LIKE '%".$begriffe[$num]."%') AND ";
                $num--;
              }
            $abfrage['text'] .= "(MATCHCODE LIKE '%".$begriffe[$num]."%'))";

            // echo $abfrage['text']."<br>";			// Debug
          }
        elseif($_POST['text'] && ($_POST['type']!="Text") && ($_POST['type']!="Suchbegriff"))
          {
            $abfrage['text'] = "WHERE ".$abfrage['type']." LIKE '%".str_replace(" ", "%", $_POST['text'])."%'";
          }
        else
          {
            $abfrage['text'] = "";
          }

        $res_id = mysql_query("SELECT REC_ID, KUNNUM1, KUNNUM2, MATCHCODE, NAME1, NAME2, STRASSE, PLZ, ORT FROM ADRESSEN ".$abfrage['text']." ORDER BY ".$abfrage['type']." ".$abfrage['order']." LIMIT ".$abfrage['limit'], $db_id);
        $data = array();
        $number = mysql_num_rows($res_id);

        for($i=0; $i<$number; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"../images/leer.gif\"></td><td>&nbsp;Suchbegriff</td><td>&nbsp;Ku.-Nr.</td><td>&nbsp;Lie.-Nr.</td><td>&nbsp;Name</td><td>&nbsp;Strasse</td><td>&nbsp;PLZ</td><td>&nbsp;Ort</td></tr>";
        foreach($data as $row)
          {
            if(strlen($row['MATCHCODE'])>30)
              {
                $tmp = str_split($row['MATCHCODE'], 30);
                $row['MATCHCODE'] = $tmp[0]."...";
              }

            $tmp_name = $row['NAME1']." ".$row['NAME2'];
            if(strlen($tmp_name)>40)
              {
                $tmp = str_split($tmp_name, 40);
                $tmp_name = $tmp[0]."...";
              }

            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".strtoupper($row['MATCHCODE'])."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KUNNUM1']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KUNNUM2']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$tmp_name."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['STRASSE']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['PLZ']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ORT']."</a></td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".strtoupper($row['MATCHCODE'])."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KUNNUM1']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KUNNUM2']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$tmp_name."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['STRASSE']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['PLZ']."</a></td><td>&nbsp;<a href=\"main.php?module=address&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ORT']."</a></td></tr>";
              }
          }
        $o_cont .= "</table>";

        $o_java .= "function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=address&target=".$_GET['target']."';
                   }";

        $o_body = " onload=\"set_navi()\"";

      }
  }
else
  {
    $o_cont = "<div align=\"center\"><br><br><br><h1>Zugriff verweigert!</h1><br><br><br></div>";
  }

?>