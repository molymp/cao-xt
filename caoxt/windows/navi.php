<?php

// ------------------------------------------------------------------------------------------------
//      Session:

session_start();
set_time_limit(6000);
error_reporting(E_ALL & ~E_NOTICE);

// ------------------------------------------------------------------------------------------------
//	Datenkompression bei der Übertragung:

if(substr_count($_SERVER['HTTP_ACCEPT_ENCODING'], 'gzip'))
  {
    ob_start("ob_gzhandler");
  }
else
  {
    ob_start();
  }

// ------------------------------------------------------------------------------------------------
//      Hauptprogramm:

if($_GET['module']=="address")
  {
    // Variable setzen um zwischen Lieferanten- und Kundenformular unterscheiden zu können

    if($_GET['target']=="krma")
      {
        $t_name = "KUN_NR";
        $s_name = "KUNNUM1";

        $o_java = "function update_data()
                   {
                    parent.opener.document.TARGET.".$t_name.".value = parent.main.document.SOURCE.".$s_name.".value;
                   }";
      }
    elseif($_GET['target']=="erma")
      {
        $t_name = "LIEF_NR";
        $s_name = "KUNNUM2";

        $o_java = "function update_data()
                   {
                    parent.opener.document.TARGET.".$t_name.".value = parent.main.document.SOURCE.".$s_name.".value;
                   }";
      }
    elseif($_GET['target']=="kun_id")
      {
        $t_name = "ADDR_ID";
        $s_name = "REC_ID";

        $o_java = "function update_data()
                   {
                    parent.opener.document.TARGET.".$t_name.".value = parent.main.document.SOURCE.".$s_name.".value;
                    parent.opener.document.TARGET.submit(); return false;
                    self.focus();
                   }";
      }


    // vorhergehende Eingabe wiederherstellen

    if($_SESSION['addr_type'])
      {
        $addr_type = $_SESSION['addr_type'];
      }
    else
      {
        $addr_type = "Suchbegriff";
      }

    if($_SESSION['addr_order'])
      {
        $addr_order = $_SESSION['addr_order'];
      }
    else
      {
        $addr_order = "Aufsteigend";
      }


    if($_SESSION['addr_limit'])
      {
        $addr_limit = $_SESSION['addr_limit'];
      }
    else
      {
        $addr_limit = "25";
      }

    if($_SESSION['addr_text'])
      {
        $addr_text = $_SESSION['addr_text'];
      }
    else
      {
        $addr_text = "";
      }


    $o_java .="function reset_all()
               {
                parent.main.location.href = 'main.php?module=address&target=".$_GET['target']."';
                self.location.href = 'navi.php?module=address&target=".$_GET['target']."';
               }

               function set_navi()
               {
                self.location.href = 'navi.php?module=address&target=".$_GET['target']."';
               }

               function change(ObjectName, ChangeTo)
               {
                document[ObjectName].src = eval(ObjectName + ChangeTo + \".src\");
               }

                n_add_on = new Image(24,22);
                n_add_on.src = \"../images/n_add_on.gif\";
                n_add_off = new Image(24,22);
                n_add_off.src = \"../images/n_add_off.gif\";
                n_delete_on = new Image(24,22);
                n_delete_on.src = \"../images/n_delete_on.gif\";
                n_delete_off = new Image(24,22);
                n_delete_off.src = \"../images/n_delete_off.gif\";
                n_ok_on = new Image(24,22);
                n_ok_on.src = \"../images/n_ok_on.gif\";
                n_ok_off = new Image(24,22);
                n_ok_off.src = \"../images/n_ok_off.gif\";
                n_cancel_on = new Image(24,22);
                n_cancel_on.src = \"../images/n_cancel_on.gif\";
                n_cancel_off = new Image(24,22);
                n_cancel_off.src = \"../images/n_cancel_off.gif\";

              ";

    if($_GET['id'])
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=address&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=address&target=".$_GET['target']."&action=delete&id=".$_GET['id']."'\" onMouseOver=\"change('n_delete_', 'on')\"  onMouseOut=\"change('n_delete_', 'off')\"><img name=\"n_delete_\" src=\"../images/n_delete_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.document.SOURCE.submit()\" onMouseOver=\"change('n_ok_', 'on')\"  onMouseOut=\"change('n_ok_', 'off')\"><img name=\"n_ok_\" src=\"../images/n_ok_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:reset_all()\" onMouseOver=\"change('n_cancel_', 'on')\"  onMouseOut=\"change('n_cancel_', 'off')\"><img name=\"n_cancel_\" src=\"../images/n_cancel_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                     </tr>
                    </table>
                   </td>
                   <form action=\"main.php?module=address&action=list&target=".$_GET['target']."\" method=\"post\" target=\"main\" onsubmit=\"set_navi()\">
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">&nbsp;Suchfeld:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"type\" size=\"1\">";
        if($addr_type == "Name")
          {
            $o_cont .= "<option>Suchbegriff</option><option selected>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Kundennummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option selected>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Ku.-Nr. bei Lief.")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option selected>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Ort")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option selected>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Strasse")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option selected>Strasse</option>";
          }
        else
          {
            $o_cont .= "<option selected>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Suchbegriff:&nbsp;</td>
                   <td bgcolor=\"#808080\"><input type=\"text\" name=\"text\" value=\"".htmlspecialchars($addr_text)."\" size=\"14\">&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Sortierung:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"order\" size=\"1\">";
        if($addr_order == "Aufsteigend")
          {
            $o_cont .= "<option selected>Aufsteigend</option><option>Absteigend</option>";
          }
        else
          {
            $o_cont .= "<option>Aufsteigend</option><option selected>Absteigend</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td><td bgcolor=\"#808080\">Limit:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"limit\" size=\"1\">";
        if($addr_limit == "25")
          {
            $o_cont .= "<option selected>25</option><option>50</option><option>100</option><option>250</option><option>500</option>";
          }
        elseif($addr_limit == "100")
          {
            $o_cont .= "<option>25</option><option>50</option><option selected>100</option><option>250</option><option>500</option>";
          }
        elseif($addr_limit == "250")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option selected>250</option><option>500</option>";
          }
        elseif($addr_limit == "500")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option>250</option><option selected>500</option>";
          }
        else
          {
            $o_cont .= "<option>25</option><option selected>50</option><option>100</option><option>250</option><option>500</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\" align=\"right\"><input type=\"submit\" name=\"submit\" value=\"suchen\"></td>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </form>";
        if($_GET['id']!="new")
          {
            $o_cont .= "<td align=\"right\"><button name=\"apply\" type=\"button\" value=\"submit\" onClick=\"update_data()\"><b>&Uuml;bernehmen</b></button></td>";
          }
        else
          {
            $o_cont .= "<td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>";
          }
        $o_cont .= "</tr></table></div>";
      }
    else
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=address&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <img name=\"n_delete_\" src=\"../images/n_delete_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_ok_\" src=\"../images/n_ok_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_cancel_\" src=\"../images/n_cancel_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                     </tr>
                    </table>
                   </td>
                   <form action=\"main.php?module=address&action=list&target=".$_GET['target']."\" method=\"post\" target=\"main\" onsubmit=\"set_navi()\">
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">&nbsp;Suchfeld:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"type\" size=\"1\">";
        if($addr_type == "Name")
          {
            $o_cont .= "<option>Suchbegriff</option><option selected>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Kundennummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option selected>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Ku.-Nr. bei Lief.")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option selected>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Ort")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option selected>Ort</option><option>Strasse</option>";
          }
        elseif($addr_type == "Strasse")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option selected>Strasse</option>";
          }
        else
          {
            $o_cont .= "<option selected>Suchbegriff</option><option>Name</option><option>Kundennummer</option><option>Ku.-Nr. bei Lief.</option><option>Ort</option><option>Strasse</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Suchbegriff:&nbsp;</td>
                   <td bgcolor=\"#808080\"><input type=\"text\" name=\"text\" value=\"".htmlspecialchars($addr_text)."\" size=\"14\">&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Sortierung:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"order\" size=\"1\">";
        if($addr_order == "Aufsteigend")
          {
            $o_cont .= "<option selected>Aufsteigend</option><option>Absteigend</option>";
          }
        else
          {
            $o_cont .= "<option>Aufsteigend</option><option selected>Absteigend</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td><td bgcolor=\"#808080\">Limit:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"limit\" size=\"1\">";
        if($addr_limit == "25")
          {
            $o_cont .= "<option selected>25</option><option>50</option><option>100</option><option>250</option><option>500</option>";
          }
        elseif($addr_limit == "100")
          {
            $o_cont .= "<option>25</option><option>50</option><option selected>100</option><option>250</option><option>500</option>";
          }
        elseif($addr_limit == "250")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option selected>250</option><option>500</option>";
          }
        elseif($addr_limit == "500")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option>250</option><option selected>500</option>";
          }
        else
          {
            $o_cont .= "<option>25</option><option selected>50</option><option>100</option><option>250</option><option>500</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\" align=\"right\"><input type=\"submit\" name=\"submit\" value=\"suchen\"></td>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </form>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </tr></table></div>";

      }
  }
elseif($_GET['module']=="liefaddr")
  {
        $o_java = "function update_data()
                   {
                    parent.opener.document.maindata.LIEF_ADDR_ID.value = parent.main.document.SOURCE.LIEF_ADDR_ID.value;
                    parent.opener.document.maindata.submit();
                    self-focus();
                   }

                   function reset_all()
                   {
                    parent.main.location.href = 'main.php?module=article&target=".$_GET['target']."';
                    self.location.href = 'navi.php?module=article&target=".$_GET['target']."';
                   }

                   function set_navi()
                   {
                    self.location.href = 'navi.php?module=article&target=".$_GET['target']."';
                   }

                   function change(ObjectName, ChangeTo)
                   {
                    document[ObjectName].src = eval(ObjectName + ChangeTo + \".src\");
                   }

                    n_add_on = new Image(24,22);
                    n_add_on.src = \"../images/n_add_on.gif\";
                    n_add_off = new Image(24,22);
                    n_add_off.src = \"../images/n_add_off.gif\";
                    n_delete_on = new Image(24,22);
                    n_delete_on.src = \"../images/n_delete_on.gif\";
                    n_delete_off = new Image(24,22);
                    n_delete_off.src = \"../images/n_delete_off.gif\";
                    n_ok_on = new Image(24,22);
                    n_ok_on.src = \"../images/n_ok_on.gif\";
                    n_ok_off = new Image(24,22);
                    n_ok_off.src = \"../images/n_ok_off.gif\";
                    n_cancel_on = new Image(24,22);
                    n_cancel_on.src = \"../images/n_cancel_on.gif\";
                    n_cancel_off = new Image(24,22);
                    n_cancel_off.src = \"../images/n_cancel_off.gif\";
                   ";

    if($_GET['id'])
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=liefaddr&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=liefaddr&target=".$_GET['target']."&action=delete&id=".$_GET['id']."'\" onMouseOver=\"change('n_delete_', 'on')\"  onMouseOut=\"change('n_delete_', 'off')\"><img name=\"n_delete_\" src=\"../images/n_delete_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.document.SOURCE.submit()\" onMouseOver=\"change('n_ok_', 'on')\"  onMouseOut=\"change('n_ok_', 'off')\"><img name=\"n_ok_\" src=\"../images/n_ok_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:reset_all()\" onMouseOver=\"change('n_cancel_', 'on')\"  onMouseOut=\"change('n_cancel_', 'off')\"><img name=\"n_cancel_\" src=\"../images/n_cancel_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                     </tr>
                    </table>
                   </td>";
        if($_GET['id']!="new")
          {
            $o_cont .= "<td align=\"right\"><button name=\"apply\" type=\"button\" value=\"submit\" onClick=\"update_data()\"><b>&Uuml;bernehmen</b></button></td>";
          }
        else
          {
            $o_cont .= "<td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>";
          }
        $o_cont .= "</tr></table></div>";
      }
    else
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=liefaddr&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <img name=\"n_delete_\" src=\"../images/n_delete_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_ok_\" src=\"../images/n_ok_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_cancel_\" src=\"../images/n_cancel_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                     </tr>
                    </table>
                   </td>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </tr></table></div>";
      }
  }
elseif($_GET['module']=="article")
  {
    // Variable setzen um zwischen ID- und Artnumformular unterscheiden zu können

    if($_GET['target']=="rec_id")
      {
        $t_name = "ARTIKEL_ID";
        $s_name = "REC_ID";

        $o_java = "function update_data()
                   {
                    parent.opener.document.TARGET.".$t_name.".value = parent.main.document.SOURCE.".$s_name.".value;
                    parent.opener.document.TARGET.submit();
                    self.focus();
                   }";
      }
    elseif($_GET['target']=="artnum")
      {
        $t_name = "ARTNUM";
        $s_name = "ARTNUM";

        $o_java = "function update_data()
                   {
                    parent.opener.document.TARGET.".$t_name.".value = parent.main.document.SOURCE.".$s_name.".value;
                   }";
      }

    // vorhergehende Eingabe wiederherstellen

    if($_SESSION['art_type'])
      {
        $art_type = $_SESSION['art_type'];
      }
    else
      {
        $art_type = "Suchbegriff";
      }

    if($_SESSION['art_order'])
      {
        $art_order = $_SESSION['art_order'];
      }
    else
      {
        $art_order = "Aufsteigend";
      }

    if($_SESSION['art_limit'])
      {
        $art_limit = $_SESSION['art_limit'];
      }
    else
      {
        $art_limit = "25";
      }

    if($_SESSION['art_text'])
      {
        $art_text = $_SESSION['art_text'];
      }
    else
      {
        $art_text = "";
      }

    if($_SESSION['art_lager'])
      {
        $art_lager = $_SESSION['art_lager'];
      }
    else
      {
        $art_lager = "FALSE";
      }


    $o_java .= "function reset_all()
               {
                parent.main.location.href = 'main.php?module=article&target=".$_GET['target']."';
                self.location.href = 'navi.php?module=article&target=".$_GET['target']."';
               }

               function set_navi()
               {
                self.location.href = 'navi.php?module=article&target=".$_GET['target']."';
               }

               function change(ObjectName, ChangeTo)
               {
                document[ObjectName].src = eval(ObjectName + ChangeTo + \".src\");
               }

                n_add_on = new Image(24,22);
                n_add_on.src = \"../images/n_add_on.gif\";
                n_add_off = new Image(24,22);
                n_add_off.src = \"../images/n_add_off.gif\";
                n_delete_on = new Image(24,22);
                n_delete_on.src = \"../images/n_delete_on.gif\";
                n_delete_off = new Image(24,22);
                n_delete_off.src = \"../images/n_delete_off.gif\";
                n_ok_on = new Image(24,22);
                n_ok_on.src = \"../images/n_ok_on.gif\";
                n_ok_off = new Image(24,22);
                n_ok_off.src = \"../images/n_ok_off.gif\";
                n_cancel_on = new Image(24,22);
                n_cancel_on.src = \"../images/n_cancel_on.gif\";
                n_cancel_off = new Image(24,22);
                n_cancel_off.src = \"../images/n_cancel_off.gif\";

              ";

    if($_GET['id'])		// Navigation für Detaildatensatz erstellen
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=article&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=article&target=".$_GET['target']."&action=delete&id=".$_GET['id']."'\" onMouseOver=\"change('n_delete_', 'on')\"  onMouseOut=\"change('n_delete_', 'off')\"><img name=\"n_delete_\" src=\"../images/n_delete_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.document.SOURCE.submit()\" onMouseOver=\"change('n_ok_', 'on')\"  onMouseOut=\"change('n_ok_', 'off')\"><img name=\"n_ok_\" src=\"../images/n_ok_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <a href=\"javascript:reset_all()\" onMouseOver=\"change('n_cancel_', 'on')\"  onMouseOut=\"change('n_cancel_', 'off')\"><img name=\"n_cancel_\" src=\"../images/n_cancel_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                     </tr>
                    </table>
                   </td>
                   <form action=\"main.php?module=article&action=list&target=".$_GET['target']."\" method=\"post\" target=\"main\" onsubmit=\"set_navi()\">
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">&nbsp;Suchfeld:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"type\" size=\"1\">";
        if($art_type == "Text")
          {
            $o_cont .= "<option>Suchbegriff</option><option selected>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Artikelnummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option selected>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Herstellernummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option selected>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Lief.-Bestellnr.")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option selected>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Info")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option selected>Info</option>";
          }
        else
          {
            $o_cont .= "<option selected>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Suchbegriff:&nbsp;</td>
                   <td bgcolor=\"#808080\"><input type=\"text\" name=\"text\" value=\"".htmlspecialchars($art_text)."\" size=\"14\">&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Sortierung:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"order\" size=\"1\">";
        if($art_order == "Aufsteigend")
          {
            $o_cont .= "<option selected>Aufsteigend</option><option>Absteigend</option>";
          }
        else
          {
            $o_cont .= "<option>Aufsteigend</option><option selected>Absteigend</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td><td bgcolor=\"#808080\">Limit:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"limit\" size=\"1\">";
        if($art_limit == "25")
          {
            $o_cont .= "<option selected>25</option><option>50</option><option>100</option><option>250</option><option>500</option>";
          }
        elseif($art_limit == "100")
          {
            $o_cont .= "<option>25</option><option>50</option><option selected>100</option><option>250</option><option>500</option>";
          }
        elseif($art_limit == "250")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option selected>250</option><option>500</option>";
          }
        elseif($art_limit == "500")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option>250</option><option selected>500</option>";
          }
        else
          {
            $o_cont .= "<option>25</option><option selected>50</option><option>100</option><option>250</option><option>500</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\" align=\"right\">&nbsp;Lager:&nbsp;</td>";
        if($art_lager == "TRUE")
          {
            $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"checkbox\" name=\"lager\" value=\"TRUE\" checked></td>";
          }
        else
          {
            $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"checkbox\" name=\"lager\" value=\"TRUE\"></td>";
          }
        $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"submit\" name=\"submit\" value=\"suchen\"></td>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </form>";
        if($_GET['id']!="new")
          {
            $o_cont .= "<td align=\"right\"><button name=\"apply\" type=\"button\" value=\"submit\" onClick=\"update_data()\"><b>&Uuml;bernehmen</b></button></td>";
          }
        else
          {
            $o_cont .= "<td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>";
          }
        $o_cont .= "</tr></table></div>";
      }
    else
      {
        $o_cont = "<div align=\"center\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr>
                   <td>
                    <table width=\"96\" cellpadding==\"0\" cellspacing=\"0\" border=\"0\">
                     <tr>
                      <td width=\"24\">
                       <a href=\"javascript:parent.main.location.href='main.php?module=article&target=".$_GET['target']."&action=add'\" onMouseOver=\"change('n_add_', 'on')\"  onMouseOut=\"change('n_add_', 'off')\"><img name=\"n_add_\" src=\"../images/n_add_off.gif\" width=24 height=22 border=0 alt=\"\"></a>
                      </td>
                      <td width=\"24\">
                       <img name=\"n_delete_\" src=\"../images/n_delete_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_ok_\" src=\"../images/n_ok_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                      <td width=\"24\">
                       <img name=\"n_cancel_\" src=\"../images/n_cancel_na.gif\" width=24 height=22 border=0 alt=\"\">
                      </td>
                     </tr>
                    </table>
                   </td>
                   <form action=\"main.php?module=article&action=list&target=".$_GET['target']."\" method=\"post\" target=\"main\" onsubmit=\"set_navi()\">
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">&nbsp;Suchfeld:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"type\" size=\"1\">";
        if($art_type == "Text")
          {
            $o_cont .= "<option>Suchbegriff</option><option selected>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Artikelnummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option selected>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Herstellernummer")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option selected>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Lief.-Bestellnr.")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option selected>Lief.-Bestellnr.</option><option>Info</option>";
          }
        elseif($art_type == "Info")
          {
            $o_cont .= "<option>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option selected>Info</option>";
          }
        else
          {
            $o_cont .= "<option selected>Suchbegriff</option><option>Text</option><option>Artikelnummer</option><option>Herstellernummer</option><option>Lief.-Bestellnr.</option><option>Info</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Suchbegriff:&nbsp;</td>
                   <td bgcolor=\"#808080\"><input type=\"text\" name=\"text\" value=\"".htmlspecialchars($art_text)."\" size=\"14\">&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\">Sortierung:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"order\" size=\"1\">";
        if($art_order == "Aufsteigend")
          {
            $o_cont .= "<option selected>Aufsteigend</option><option>Absteigend</option>";
          }
        else
          {
            $o_cont .= "<option>Aufsteigend</option><option selected>Absteigend</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td><td bgcolor=\"#808080\">Limit:&nbsp;</td>
                   <td bgcolor=\"#808080\"><select name=\"limit\" size=\"1\">";
        if($art_limit == "25")
          {
            $o_cont .= "<option selected>25</option><option>50</option><option>100</option><option>250</option><option>500</option>";
          }
        elseif($art_limit == "100")
          {
            $o_cont .= "<option>25</option><option>50</option><option selected>100</option><option>250</option><option>500</option>";
          }
        elseif($art_limit == "250")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option selected>250</option><option>500</option>";
          }
        elseif($art_limit == "500")
          {
            $o_cont .= "<option>25</option><option>50</option><option>100</option><option>250</option><option selected>500</option>";
          }
        else
          {
            $o_cont .= "<option>25</option><option selected>50</option><option>100</option><option>250</option><option>500</option>";
          }
        $o_cont .= "</select>&nbsp;&nbsp;</td>
                   <td bgcolor=\"#808080\" align=\"right\">&nbsp;Lager:&nbsp;</td>";
        if($art_lager == "TRUE")
          {
            $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"checkbox\" name=\"lager\" value=\"TRUE\" checked></td>";
          }
        else
          {
            $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"checkbox\" name=\"lager\" value=\"TRUE\"></td>";
          }
        $o_cont .= "<td bgcolor=\"#808080\" align=\"right\"><input type=\"submit\" name=\"submit\" value=\"suchen\"></td>
                   <td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
                   </form>";
        $o_cont .= "<td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>";
        $o_cont .= "</tr></table></div>";
      }
  }
elseif($_GET['module']=="snum")
  {
  	$o_cont = "<div align=\"center\">F&uuml;r diesen Artikel wurde eine Seriennummern-Pflicht gesetzt!<br>Bitte weisen Sie die Seriennummern der entsprechenden Artikel dem Beleg zu.</div>";
  }
else
  {
    $o_cont = "<div align=\"center\"><h1>Modul nicht gefunden!</h1></div>";
  }

$output = file_get_contents("includes/ntemplate.html");
$output = str_replace("@@java@@", $o_java, $output);				// Javascripte
$output = str_replace("@@cont@@", $o_cont, $output);				// Inhalt der Seite

print $output;


ob_end_flush();									// Ausgabepuffer leeren

?>