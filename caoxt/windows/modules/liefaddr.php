<?php

$o_head = "Lieferadressen";
$o_java = "function reset_all()
           {
            parent.navi.location.href = 'navi.php?module=liefaddr&target=".$_GET['target']."';
            self.location.href = 'main.php?module=liefaddr&target=".$_GET['target']."';
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

function print_main($data, $target, $type, $id)
  {
    $o_cont .= "<form action=\"main.php?module=liefaddr&action=detail&target=".$target."&id=".$id."\" method=\"post\" name=\"SOURCE\">";
    $o_cont .= "<table width=\"100%\" cellpadding=\"2\" cellspacing=\"0\">";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Anrede:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"ANREDE\" style=\"width:550px;\" value=\"".htmlspecialchars($data['ANREDE'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name1:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME1\" style=\"width:550px;\" value=\"".htmlspecialchars($data['NAME1'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name2:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME2\" style=\"width:550px;\" value=\"".htmlspecialchars($data['NAME2'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Name3:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"NAME3\" style=\"width:550px;\" value=\"".htmlspecialchars($data['NAME3'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Strasse:</td><td colspan=\"3\" align=\"right\"><input type=\"text\" name=\"STRASSE\" style=\"width:550px;\" value=\"".htmlspecialchars($data['STRASSE'])."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Land/PLZ/Ort:</td><td align=\"right\"><input type=\"text\" name=\"LAND\" style=\"width:20px;\" value=\"".htmlspecialchars($data['LAND'])."\"></td><td align=\"center\"><input type=\"text\" name=\"PLZ\" style=\"width:50px;\" value=\"".htmlspecialchars($data['PLZ'])."\"></td><td align=\"right\"><input type=\"text\" name=\"ORT\" style=\"width:465px;\" value=\"".htmlspecialchars($data['ORT'])."\"><input type=\"hidden\" name=\"ADDR_ID\" value=\"".$data['ADDR_ID']."\"><input type=\"hidden\" name=\"TYPE\" value=\"".$type."\"><input type=\"hidden\" name=\"LIEF_ADDR_ID\" value=\"".$id."\"></td></tr>";
    $o_cont .= "<tr bgcolor=\"#ffffdd\"><td valign=\"middle\" width=\"100\">Info:</td><td colspan=\"3\" align=\"right\"><textarea name=\"INFO\" style=\"width: 100%;\" rows=\"4\">".htmlspecialchars($data['INFO'])."</textarea></td></tr>";
    $o_cont .= "</table></form>";

    return $o_cont;
  }

function liefaddr_update($data, $id, $db_id)
  {
    $query = "UPDATE ADRESSEN_LIEF SET
                ANREDE='".addslashes($data['ANREDE'])."',
                NAME1='".addslashes($data['NAME1'])."',
                NAME2='".addslashes($data['NAME2'])."',
                NAME3='".addslashes($data['NAME3'])."',
                ABTEILUNG='".addslashes($data['ABTEILUNG'])."',
                STRASSE='".addslashes($data['STRASSE'])."',
                LAND='".addslashes($data['LAND'])."',
                PLZ='".addslashes($data['PLZ'])."',
                ORT='".addslashes($data['ORT'])."',
                INFO='".addslashes($data['INFO'])."'
               WHERE REC_ID=".$id;

     echo $query."<br><br>";

    if(!mysql_query($query, $db_id))
      {
        echo mysql_error($db_id)."<br>";
        return 0;
      }
    else
      {
        return 1;
      }
  }

function liefaddr_add($data, $db_id)
  {
    $query = "INSERT INTO ADRESSEN_LIEF SET
                ADDR_ID='".$data['ADDR_ID']."',
                ANREDE='".addslashes($data['ANREDE'])."',
                NAME1='".addslashes($data['NAME1'])."',
                NAME2='".addslashes($data['NAME2'])."',
                NAME3='".addslashes($data['NAME3'])."',
                ABTEILUNG='".addslashes($data['ABTEILUNG'])."',
                STRASSE='".addslashes($data['STRASSE'])."',
                LAND='".addslashes($data['LAND'])."',
                PLZ='".addslashes($data['PLZ'])."',
                ORT='".addslashes($data['ORT'])."',
                INFO='".addslashes($data['INFO'])."'";

     echo $query."<br><br>";

    if(!mysql_query($query, $db_id))
      {
        echo mysql_error($db_id)."<br>";
        return 0;
      }
    else
      {
        return mysql_insert_id($db_id);
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
                liefaddr_update($_POST, $_GET['id'], $db_id);
              }
            elseif($_POST['TYPE']=="add")
              {
                $_GET['id'] = liefaddr_add($_POST, $db_id);
              }
          }

        $res_id = mysql_query("SELECT * FROM ADRESSEN_LIEF WHERE REC_ID=".$_GET['id'], $db_id);
        $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        $o_cont = print_main($data, $_GET['target'], 'update', $_GET['id']);

        $o_java .= "function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=liefaddr&target=".$_GET['target']."&id=".$_GET['id']."';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    elseif($_GET['action']=="add")
      {
        $data = array();
        $data['ADDR_ID'] = $_GET['target'];

        $o_cont = print_main($data, $_GET['target'], 'add', 'new');

        $o_java .= "
                   function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=liefaddr&target=".$_GET['target']."&id=new';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    else
      {
        $res_id = mysql_query("SELECT REC_ID, ANREDE, NAME1, NAME2, STRASSE, PLZ, ORT FROM ADRESSEN_LIEF WHERE ADDR_ID='".$_GET['target']."' ORDER BY NAME1", $db_id);
        $data = array();
        $number = mysql_num_rows($res_id);

        for($i=0; $i<$number; $i++)
          {
            array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
          }
        mysql_free_result($res_id);

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"../images/leer.gif\"></td><td>&nbsp;Anrede</td><td>&nbsp;Name</td><td>&nbsp;Strasse</td><td>&nbsp;Land</td><td>&nbsp;PLZ</td><td>&nbsp;Ort</td></tr>";
        foreach($data as $row)
          {
            $tmp_name = $row['NAME1']." ".$row['NAME2'];
            if(strlen($tmp_name)>30)
              {
                $tmp = str_split($tmp_name, 30);
                $tmp_name = $tmp[0]."...";
              }

            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ANREDE']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$tmp_name."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['STRASSE']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['LAND']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['PLZ']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ORT']."</a></td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ANREDE']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$tmp_name."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['STRASSE']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['LAND']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['PLZ']."</a></td><td>&nbsp;<a href=\"main.php?module=liefaddr&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ORT']."</a></td></tr>";
              }
          }
        $o_cont .= "</table>";

        $o_java .= "function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=liefaddr&target=".$_GET['target']."';
                   }";

        $o_body = " onload=\"set_navi()\"";

      }
  }
else
  {
    $o_cont = "<div align=\"center\"><br><br><br><h1>Zugriff verweigert!</h1><br><br><br></div>";
  }

?>