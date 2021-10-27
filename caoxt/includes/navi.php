 <?php

// Variablen initialisieren:

$var_string = "";

if($_GET['module']) $var_string .= "&module=".$_GET['module'];
if($_GET['action']) $var_string .= "&action=".$_GET['action'];
if($_GET['type']) $var_string .= "&type=".$_GET['type'];
if($_GET['id']) $var_string .= "&id=".$_GET['id'];


$o_java =  "<!--

            function open_lief()
            {
             window_erma = window.open(\"windows/windows.php?module=address&target=erma\", \"Adressbrowser\", \"width=1000,height=580,left=50,top=50\");
             window_erma.focus();
            }

            function open_kunde()
            {
             window_krma = window.open(\"windows/windows.php?module=address&target=krma\", \"Adressbrowser\", \"width=1000,height=580,left=50,top=50\");
             window_krma.focus();
            }

            function open_kun_id()
            {
             window_kun_id = window.open(\"windows/windows.php?module=address&target=kun_id\", \"Adressbrowser\", \"width=1000,height=580,left=50,top=50\");
             window_kun_id.focus();
            }

            function open_artnum()
            {
             window_article = window.open(\"windows/windows.php?module=article&target=artnum\", \"Artikelbrowser\", \"width=1000,height=580,left=50,top=50\");
             window_article.focus();
            }

            function open_artid()
            {
             window_article = window.open(\"windows/windows.php?module=article&target=rec_id\", \"Artikelbrowser\", \"width=1000,height=580,left=50,top=50\");
             window_article.focus();
            }
			
			function open_snum(recid)
            {
             window_snum = window.open(\"windows/windows.php?module=snum&target=\"+recid, \"Artikelbrowser\", \"width=600,height=300,left=50,top=50\");
             window_snum.focus();
            }

            function change(ObjectName, ChangeTo)
            {
             document[ObjectName].src = eval(ObjectName + ChangeTo + \".src\");
            }
            ";


// HAUPTPROGRAMM:

if(!$_GET['section'] || ($_GET['section']=="best"))
  {
    $o_java .= "b_repbest_on = new Image(38,38);
                b_repbest_on.src = \"images/b_repbest_on.gif\";
                b_repbest_off = new Image(38,38);
                b_repbest_off.src = \"images/b_repbest_off.gif\";
                b_eigenbest_on = new Image(38,38);
                b_eigenbest_on.src = \"images/b_eigenbest_on.gif\";
                b_eigenbest_off = new Image(38,38);
                b_eigenbest_off.src = \"images/b_eigenbest_off.gif\";
                b_lager_on = new Image(38,38);
                b_lager_on.src = \"images/b_lager_on.gif\";
                b_lager_off = new Image(38,38);
                b_lager_off.src = \"images/b_lager_off.gif\";
                //-->";

    $o_jnv1 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=best".$var_string."\">Best&auml;nde</a></td>";

    $o_jnv2 = "<td bgcolor=\"#808080\" width=\"80\" align=\"center\" valign=\"top\">
                <div class=\"sma\">&nbsp;</div><br>
                <a href=\"main.php?section=best&module=lager\" onMouseOver=\"change('b_lager_', 'on')\"  onMouseOut=\"change('b_lager_', 'off')\"><img name=\"b_lager_\" src=\"images/b_lager_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Lager</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
               </td>";

    $o_jnv3 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=vor".$var_string."\">Vorg&auml;nge</a></td>";

    $o_jnv4 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=journ".$var_string."\">Journale</a></td>";

    $o_jnv5 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=werk".$var_string."\">Statistiken</a></td>";

    $o_jnv6 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=help".$var_string."\">Hilfe</a></td>";
  }
elseif($_GET['section']=="vor")
  {
    $o_java .= "b_rma_on = new Image(38,38);
                b_rma_on.src = \"images/b_rma_on.gif\";
                b_rma_off = new Image(38,38);
                b_rma_off.src = \"images/b_rma_off.gif\";
                b_sn_on = new Image(38,38);
                b_sn_on.src = \"images/b_sn_on.gif\";
                b_sn_off = new Image(38,38);
                b_sn_off.src = \"images/b_sn_off.gif\";
                b_best_on = new Image(38,38);
                b_best_on.src = \"images/b_best_on.gif\";
                b_best_off = new Image(38,38);
                b_best_off.src = \"images/b_best_off.gif\";
                b_sammler_on = new Image(38,38);
                b_sammler_on.src = \"images/b_sammler_on.gif\";
                b_sammler_off = new Image(38,38);
                b_sammler_off.src = \"images/b_sammler_off.gif\";
                b_angebot_on = new Image(38,38);
                b_angebot_on.src = \"images/b_angebot_on.gif\";
                b_angebot_off = new Image(38,38);
                b_angebot_off.src = \"images/b_angebot_off.gif\";
                b_rechnung_on = new Image(38,38);
                b_rechnung_on.src = \"images/b_rechnung_on.gif\";
                b_rechnung_off = new Image(38,38);
                b_rechnung_off.src = \"images/b_rechnung_off.gif\";
                //-->";

    $o_jnv1 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=best".$var_string."\">Best&auml;nde</a></td>";

    $o_jnv2 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=vor".$var_string."\">Vorg&auml;nge</a></td>";

    $o_jnv3 = "<td bgcolor=\"#808080\" width=\"80\" align=\"center\" valign=\"top\">
                <div class=\"sma\">&nbsp;</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=angebot\" onMouseOver=\"change('b_angebot_', 'on')\"  onMouseOut=\"change('b_angebot_', 'off')\"><img name=\"b_angebot_\" src=\"images/b_angebot_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Angebot</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=rechnung\" onMouseOver=\"change('b_rechnung_', 'on')\"  onMouseOut=\"change('b_rechnung_', 'off')\"><img name=\"b_rechnung_\" src=\"images/b_rechnung_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Rechnung</div><br>

                <a href=\"main.php?section=".$_GET['section']."&module=sn\" onMouseOver=\"change('b_sn_', 'on')\"  onMouseOut=\"change('b_sn_', 'off')\"><img name=\"b_sn_\" src=\"images/b_sn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Seriennummern</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=best\" onMouseOver=\"change('b_best_', 'on')\"  onMouseOut=\"change('b_best_', 'off')\"><img name=\"b_best_\" src=\"images/b_best_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Best&auml;nde</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=sammler\" onMouseOver=\"change('b_sammler_', 'on')\"  onMouseOut=\"change('b_sammler_', 'off')\"><img name=\"b_sammler_\" src=\"images/b_sammler_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Sammler</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>               </td>";

    $o_jnv4 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=journ".$var_string."\">Journale</a></td>";

    $o_jnv5 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=werk".$var_string."\">Statistiken</a></td>";

    $o_jnv6 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=help".$var_string."\">Hilfe</a></td>";
  }
elseif($_GET['section']=="journ")
  {
    $o_java .= "b_rmajourn_on = new Image(38,38);
                b_rmajourn_on.src = \"images/b_rmajourn_on.gif\";
                b_rmajourn_off = new Image(38,38);
                b_rmajourn_off.src = \"images/b_rmajourn_off.gif\";
                b_wejourn_on = new Image(38,38);
                b_wejourn_on.src = \"images/b_wejourn_on.gif\";
                b_wejourn_off = new Image(38,38);
                b_wejourn_off.src = \"images/b_wejourn_off.gif\";
                b_rejourn_on = new Image(38,38);
                b_rejourn_on.src = \"images/b_rejourn_on.gif\";
                b_rejourn_off = new Image(38,38);
                b_rejourn_off.src = \"images/b_rejourn_off.gif\";
                b_agjourn_on = new Image(38,38);
                b_agjourn_on.src = \"images/b_agjourn_on.gif\";
                b_agjourn_off = new Image(38,38);
                b_agjourn_off.src = \"images/b_agjourn_off.gif\";
                b_snjourn_on = new Image(38,38);
                b_snjourn_on.src = \"images/b_snjourn_on.gif\";
                b_snjourn_off = new Image(38,38);
                b_snjourn_off.src = \"images/b_snjourn_off.gif\";
                b_bejourn_on = new Image(38,38);
                b_bejourn_on.src = \"images/b_bejourn_on.gif\";
                b_bejourn_off = new Image(38,38);
                b_bejourn_off.src = \"images/b_bejourn_off.gif\";
                b_kajourn_on = new Image(38,38);
                b_kajourn_on.src = \"images/b_kajourn_on.gif\";
                b_kajourn_off = new Image(38,38);
                b_kajourn_off.src = \"images/b_kajourn_off.gif\";
                //-->";

    $o_jnv1 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=best".$var_string."\">Best&auml;nde</a></td>";

    $o_jnv2 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=vor".$var_string."\">Vorg&auml;nge</a></td>";

    $o_jnv3 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=journ".$var_string."\">Journale</a></td>";

    $o_jnv4 = "<td bgcolor=\"#808080\" width=\"80\" align=\"center\" valign=\"top\">
                <div class=\"sma\">&nbsp;</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=agjourn\" onMouseOver=\"change('b_agjourn_', 'on')\"  onMouseOut=\"change('b_agjourn_', 'off')\"><img name=\"b_agjourn_\" src=\"images/b_agjourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Angebot</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=rejourn\" onMouseOver=\"change('b_rejourn_', 'on')\"  onMouseOut=\"change('b_rejourn_', 'off')\"><img name=\"b_rejourn_\" src=\"images/b_rejourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Rechnung</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=bejourn\" onMouseOver=\"change('b_bejourn_', 'on')\"  onMouseOut=\"change('b_bejourn_', 'off')\"><img name=\"b_bejourn_\" src=\"images/b_bejourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Best&auml;nde</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=wejourn\" onMouseOver=\"change('b_wejourn_', 'on')\"  onMouseOut=\"change('b_wejourn_', 'off')\"><img name=\"b_wejourn_\" src=\"images/b_wejourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Wareneingang</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=kajourn\" onMouseOver=\"change('b_kajourn_', 'on')\"  onMouseOut=\"change('b_kajourn_', 'off')\"><img name=\"b_kajourn_\" src=\"images/b_kajourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Kassenjournal</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=datevex\" onMouseOver=\"change('b_kajourn_', 'on')\"  onMouseOut=\"change('b_kajourn_', 'off')\"><img name=\"b_kajourn_\" src=\"images/b_kajourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Datev-Export</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=ktoaus\" onMouseOver=\"change('b_snjourn_', 'on')\"  onMouseOut=\"change('b_snjourn_', 'off')\"><img name=\"b_snjourn_\" src=\"images/b_snjourn_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Kontoausz&uuml;ge</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
</td>";

    $o_jnv5 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=werk".$var_string."\">Statistiken</a></td>";

    $o_jnv6 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=help".$var_string."\">Hilfe</a></td>";
  }
elseif($_GET['section']=="werk")
  {
    $o_java .= "b_konfig_on = new Image(38,38);
                b_konfig_on.src = \"images/b_konfig_on.gif\";
                b_konfig_off = new Image(38,38);
                b_konfig_off.src = \"images/b_konfig_off.gif\";
                //-->";

    $o_jnv1 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=best".$var_string."\">Best&auml;nde</a></td>";

    $o_jnv2 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=vor".$var_string."\">Vorg&auml;nge</a></td>";

    $o_jnv3 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=journ".$var_string."\">Journale</a></td>";

    $o_jnv4 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=werk".$var_string."\">Statistiken</a></td>";

    $o_jnv5 = "<td bgcolor=\"#808080\" width=\"80\" align=\"center\" valign=\"top\">
                <div class=\"sma\">&nbsp;</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=stat1\" onMouseOver=\"change('b_konfig_', 'on')\"  onMouseOut=\"change('b_konfig_', 'off')\"><img name=\"b_konfig_\" src=\"images/b_konfig_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Statistik 1</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=stat2\" onMouseOver=\"change('b_konfig_', 'on')\"  onMouseOut=\"change('b_konfig_', 'off')\"><img name=\"b_konfig_\" src=\"images/b_konfig_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Statistik 2</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
               </td>";

    $o_jnv6 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=help".$var_string."\">Hilfe</a></td>";
  }
elseif($_GET['section']=="help")
  {
    $o_java .= "b_home_on = new Image(38,38);
                b_home_on.src = \"images/b_home_on.gif\";
                b_home_off = new Image(38,38);
                b_home_off.src = \"images/b_home_off.gif\";

                //-->";

    $o_jnv1 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=best".$var_string."\">Best&auml;nde</a></td>";

    $o_jnv2 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=vor".$var_string."\">Vorg&auml;nge</a></td>";

    $o_jnv3 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=journ".$var_string."\">Journale</a></td>";

    $o_jnv4 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=werk".$var_string."\">Statistiken</a></td>";

    $o_jnv5 = "<td bgcolor=\"#d4d0c8\" width=\"80\" height=\"14\" align=\"center\"><a href=\"main.php?section=help".$var_string."\">Hilfe</a></td>";

    $o_jnv6 = "<td bgcolor=\"#808080\" width=\"80\" align=\"center\" valign=\"top\">
                <div class=\"sma\">&nbsp;</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=home\" onMouseOver=\"change('b_home_', 'on')\"  onMouseOut=\"change('b_home_', 'off')\"><img name=\"b_home_\" src=\"images/b_home_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Info</div><br>
                <a href=\"main.php?section=".$_GET['section']."&module=konfig\" onMouseOver=\"change('b_konfig_', 'on')\"  onMouseOut=\"change('b_konfig_', 'off')\"><img name=\"b_konfig_\" src=\"images/b_konfig_off.gif\" width=38 height=38 border=0 alt=\"\"></a><br>
                <div class=\"nav\">Konfiguration</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
                <img src=\"images/b_dummy.gif\" width=38 height=38 border=0 alt=\"\"><br>
                <div class=\"nav\">&nbsp;</div><br>
               </td>";
  }
?>