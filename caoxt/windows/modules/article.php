<?php

$o_head = "Artikel";
$o_java = "function reset_all()
           {
            parent.navi.location.href = 'navi.php?module=article&target=".$_GET['target']."';
            self.location.href = 'main.php?module=article&target=".$_GET['target']."';
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

function print_main($data, $group, $country, $manufacturer, $mengeneinheit, $mwst, $type, $target, $id)
  {
    if(!$data['STEUER_CODE'])
      {
        foreach($mwst as $row)
          {
            if($row['NAME']=="DEFAULT")
              {
                $data['STEUER_CODE'] = $row['VAL_INT'];
              }
          }
      }
    if(!$data['VPE']) $data['VPE'] = 1;
    if(!$data['INVENTUR_WERT']) $data['INVENTUR_WERT'] = "100,00";
    if(!$data['AUFW_KTO']) $data['AUFW_KTO'] = "3400";
    if(!$data['ERLOES_KTO']) $data['ERLOES_KTO'] = "8400";
    if(!$data['ME_ID']) $data['ME_ID'] = 2;

    $data['EK_PREIS'] = number_format($data['EK_PREIS'], 2, ',', '')." €";
    $data['VK5'] = number_format($data['VK5'], 2, ',', '')." €";
    $data['VK5B'] = number_format($data['VK5B'], 2, ',', '')." €";
    $data['GEWICHT'] = number_format($data['GEWICHT'], 4, ',', '');
    $data['MENGE_MIN'] = number_format($data['MENGE_MIN'], 2, ',', '');
    $data['MENGE_BVOR'] = number_format($data['MENGE_BVOR'], 2, ',', '');
    $data['MENGE_AKT'] = number_format($data['MENGE_AKT'], 2, ',', '');
    $data['INVENTUR_WERT'] = number_format($data['INVENTUR_WERT'], 2, ',', '')." %";



    $o_cont = "<form action=\"main.php?module=article&action=detail&target=".$target."&id=".$id."\" method=\"post\" name=\"SOURCE\">
                <table width=\"100%\" bgcolor=\"#ffffdd\" cellpadding=\"0\" cellspacing=\"0\">
                 <tr>
                  <td bgcolor=\"#808080\" valign=\"top\" width=\"50%\">
                   <table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"100%\">
                      <b>&nbsp;Suchbegriffe</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"400\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Suchbegriff:</td><td align=\"right\"><input type=\"text\" name=\"MATCHCODE\" style=\"width:300px;\" value=\"".htmlspecialchars($data['MATCHCODE'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Artikel-Nr.:</td><td align=\"right\"><input type=\"text\" name=\"ARTNUM\" style=\"width:300px;\" value=\"".htmlspecialchars($data['ARTNUM'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Ersatz-Nr.:</td><td align=\"right\"><input type=\"text\" name=\"ERSATZ_ARTNUM\" style=\"width:300px;\" value=\"".htmlspecialchars($data['ERSATZ_ARTNUM'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Barcode/EAN:</td><td align=\"right\"><input type=\"text\" name=\"BARCODE\" style=\"width:300px;\" value=\"".htmlspecialchars($data['BARCODE'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Artikel-Typ:</td><td align=\"right\"><select name=\"ARTIKELTYP_TXT\" size=\"1\" style=\"width:300px;\">";
    if($data['ARTIKELTYP']=="S")
      {
        $o_cont .=     "<option>normaler Artikel</option><option selected>Artikel mit Stückliste</option><option>Lohn</option><option>Transportkosten</option><option>Text / Kommentar</option>";
      }
    elseif($data['ARTIKELTYP']=="L")
      {
        $o_cont .=     "<option>normaler Artikel</option><option>Artikel mit Stückliste</option><option selected>Lohn</option><option>Transportkosten</option><option>Text / Kommentar</option>";
      }
    elseif($data['ARTIKELTYP']=="K")
      {
        $o_cont .=     "<option>normaler Artikel</option><option>Artikel mit Stückliste</option><option>Lohn</option><option selected>Transportkosten</option><option>Text / Kommentar</option>";
      }
    elseif($data['ARTIKELTYP']=="T")
      {
        $o_cont .=     "<option>normaler Artikel</option><option>Artikel mit Stückliste</option><option>Lohn</option><option>Transportkosten</option><option selected>Text / Kommentar</option>";
      }
    else
      {
        $o_cont .=     "<option selected>normaler Artikel</option><option>Artikel mit Stückliste</option><option>Lohn</option><option>Transportkosten</option><option>Text / Kommentar</option>";
      }

    $o_cont .=        "</select></td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"100%\">
                      <b>&nbsp;Zuweisungen</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"400\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Warengruppe:</td><td align=\"right\"><select name=\"WARENGRUPPE_TXT\" size=\"1\" style=\"width:300px;\">";
    foreach($group as $row)
      {
        if($row['ID']==$data['WARENGRUPPE'])
          {
            $o_cont .=    "<option selected>".$row['NAME']." [".$row['ID']."]</option>";
          }
        else
          {
            $o_cont .=    "<option>".$row['NAME']." [".$row['ID']."]</option>";
          }
      }
    $o_cont .=        "</select></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Herkunftsland:</td><td align=\"right\"><select name=\"HERKUNFTSLAND_TXT\" size=\"1\" style=\"width:300px;\">";
    foreach($country as $row)
      {
        if($row['ID']==$data['HERKUNFTSLAND'])
          {
            $o_cont .=    "<option selected>".$row['ID']." ".$row['NAME']."</option>";
          }
        else
          {
            $o_cont .=    "<option>".$row['ID']." ".$row['NAME']."</option>";
          }
      }
    $o_cont .=        "</select></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Lager-Ort:</td><td align=\"right\"><input type=\"text\" name=\"LAGERORT\" style=\"width:300px;\" value=\"".htmlspecialchars($data['LAGERORT'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Hersteller:</td><td align=\"right\"><select name=\"HERSTELLER_ID_TXT\" size=\"1\" style=\"width:300px;\">";
    foreach($manufacturer as $row)
      {
        if($row['ID']==$data['HERSTELLER_ID'])
          {
            if(!$row['ID'])
              {
                $o_cont .= "<option selected></option>";
              }
            else
              {
                $o_cont .= "<option selected>".$row['NAME']." [".$row['ID']."]</option>";
              }
          }
        else
          {
            if(!$row['ID'])
              {
                $o_cont .= "<option selected></option>";
              }
            else
              {
                $o_cont .=    "<option>".$row['NAME']." [".$row['ID']."]</option>";
              }
          }
      }
    $o_cont .=        "</select></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Herst.-Artnr.:</td><td align=\"right\"><input type=\"text\" name=\"HERST_ARTNUM\" style=\"width:300px;\" value=\"".htmlspecialchars($data['HERST_ARTNUM'])."\"></td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"100%\">
                      <b>&nbsp;Einheiten / Konten</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"400\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Mengeneinh.:</td><td align=\"right\"><select name=\"ME_ID\" size=\"1\" style=\"width:95px;\">";
    foreach($mengeneinheit as $row)
      {
        if($row['ID']==$data['ME_ID'])
          {
            $o_cont .=    "<option value=".$row['ID']." selected>".$row['NAME']." [".$row['ID']."]</option>";
          }
        else
          {
            $o_cont .=    "<option value=".$row['ID'].">".$row['NAME']." [".$row['ID']."]</option>";
          }
      }
    $o_cont .=        "</select></td><td valign=\"middle\">Aufw.-Kto.:</td><td align=\"right\"><input type=\"text\" name=\"AUFW_KTO\" style=\"width:95px;\" value=\"".htmlspecialchars($data['AUFW_KTO'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">VPE:</td><td align=\"right\"><input type=\"text\" name=\"VPE\" style=\"width:95px;\" value=\"".htmlspecialchars($data['VPE'])."\"></td><td valign=\"middle\">Erl&ouml;s-Kto.:</td><td align=\"right\"><input type=\"text\" name=\"ERLOES_KTO\" style=\"width:95px;\" value=\"".htmlspecialchars($data['ERLOES_KTO'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">MwSt.-Code:</td><td align=\"right\"><select name=\"STEUER_CODE_TXT\" size=\"1\" style=\"width:95px;\">";
    foreach($mwst as $row)
      {
        if($row['NAME']!="DEFAULT")
          {
            if($row['NAME']==$data['STEUER_CODE'])
              {
                $o_cont .=    "<option selected>".$row['NAME']." ".$row['VAL_DOUBLE']." %</option>";
              }
            else
              {
                $o_cont .=    "<option>".$row['NAME']." ".$row['VAL_DOUBLE']." %</option>";
              }
          }
      }
    $o_cont .=        "</select></td><td valign=\"middle\">Inv.-Wert:</td><td align=\"right\"><input type=\"text\" name=\"INVENTUR_WERT\" style=\"width:95px;\" value=\"".htmlspecialchars($data['INVENTUR_WERT'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Gewicht(Kg):</td><td align=\"right\"><input type=\"text\" name=\"GEWICHT\" style=\"width:95px;\" value=\"".htmlspecialchars($data['GEWICHT'])."\"></td><td valign=\"middle\">L&auml;nge:</td><td align=\"right\"><input type=\"text\" name=\"LAENGE\" style=\"width:95px;\" value=\"".htmlspecialchars($data['LAENGE'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Dimension:</td><td align=\"right\"><input type=\"text\" name=\"DIMENSION\" style=\"width:95px;\" value=\"".htmlspecialchars($data['DIMENSION'])."\"></td><td valign=\"middle\">Gr&ouml;sse:</td><td align=\"right\"><input type=\"text\" name=\"GROESSE\" style=\"width:95px;\" value=\"".htmlspecialchars($data['GROESSE'])."\"></td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"100%\">
                      <b>&nbsp;Menge / Preis</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"400\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Mind.-Bestand:</td><td align=\"right\"><input type=\"text\" name=\"MENGE_MIN\" style=\"width:95px;\" value=\"".htmlspecialchars($data['MENGE_MIN'])."\"></td><td valign=\"middle\">Einkaufspreis:</td><td align=\"right\"><input type=\"text\" name=\"EK_PREIS\" style=\"width:95px;\" value=\"".htmlspecialchars($data['EK_PREIS'])."\"></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Bestellvorschl.:</td><td align=\"right\"><input type=\"text\" name=\"MENGE_BVOR\" style=\"width:95px;\" value=\"".htmlspecialchars($data['MENGE_BVOR'])."\"></td><td valign=\"middle\">Listenpreis(5):</td><td align=\"right\"><input type=\"text\" name=\"VK5\" style=\"width:95px;\" value=\"".htmlspecialchars($data['VK5'])."\" readonly></td></tr>
                       <tr bgcolor=\"#ffffdd\"><td valign=\"middle\">Bestand:</td><td align=\"right\"><input type=\"text\" name=\"MENGE_AKT\" style=\"width:95px;\" value=\"".htmlspecialchars($data['MENGE_AKT'])."\"></td><td valign=\"middle\">Brutto:</td><td align=\"right\"><input type=\"text\" name=\"VK5B\" style=\"width:95px;\" value=\"".htmlspecialchars($data['VK5B'])."\" readonly></td></tr>
                      </table>
                     </td>
                    </tr>
                   </table>
                  </td>
                  <td bgcolor=\"#808080\" valign=\"top\" width=\"50%\">
                   <table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\">
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"100%\">
                       <b>&nbsp;Kurztext</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td align=\"right\"><input type=\"text\" name=\"KURZNAME\" style=\"width:495px;\" value=\"".htmlspecialchars($data['KURZNAME'])."\"></td><td width=\"20\">&nbsp;</td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"80%\"><b>&nbsp;Kasse</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\"></td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td align=\"right\"><input type=\"text\" name=\"KAS_NAME\" style=\"width:495px;\" value=\"".htmlspecialchars($data['KAS_NAME'])."\"></td><td width=\"20\">&nbsp;</td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"80%\">
                      <b>&nbsp;Langtext</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\">
                      <table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td align=\"right\"><textarea name=\"LANGNAME\" cols=\"115\" rows=\"18\">".htmlspecialchars($data['LANGNAME'])."</textarea></td><td width=\"20\">&nbsp;</td></tr>
                      </table>
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"middle\" width=\"80%\">
                      <b>&nbsp;Info</b><img src=\"../images/slash.gif\" style=\"vertical-align:middle\">
                     </td>
                    </tr>
                    <tr>
                     <td bgcolor=\"#ffffdd\" valign=\"top\" rowspan=\"2\">
                      <table width=\"500\" cellpadding=\"2\" cellspacing=\"0\">
                       <tr bgcolor=\"#ffffdd\"><td align=\"right\"><textarea name=\"INFO\" cols=\"115\" rows=\"7\">".htmlspecialchars($data['INFO'])."</textarea></td><td width=\"20\">&nbsp;</td></tr>
                      </table>
                     </td>
                    </tr>
                   </table>
                  </td>
                 </tr>
                </table>
                <input type=\"hidden\" name=\"REC_ID\" value=\"".$data['REC_ID']."\"><input type=\"hidden\" name=\"TYPE\" value=\"".$type."\">
               </form>";


    return $o_cont;
  }

function get_faktor($wg_id, $db_id)
  {
    $res_id = mysql_query("SELECT VK1_FAKTOR, VK2_FAKTOR, VK3_FAKTOR, VK4_FAKTOR, VK5_FAKTOR FROM WARENGRUPPEN WHERE ID=".$wg_id, $db_id);
    $wg_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $result = array();

    $result['VK1'] = $wg_ar['VK1_FAKTOR'];
    $result['VK2'] = $wg_ar['VK2_FAKTOR'];
    $result['VK3'] = $wg_ar['VK3_FAKTOR'];
    $result['VK4'] = $wg_ar['VK4_FAKTOR'];
    $result['VK5'] = $wg_ar['VK5_FAKTOR'];

    if(($result['VK1']==0) || ($result['VK2']==0) || ($result['VK3']==0) || ($result['VK4']==0) || ($result['VK5']==0))
      {
	    $result['VK1'] = 1;
	    $result['VK2'] = 1;
	    $result['VK3'] = 1;
	    $result['VK4'] = 1;
	    $result['VK5'] = 1;       
		
		return $result;
      }
    else
      {
        return $result;
      }
  }

function get_faktor_default($db_id)
  {
    $res_id = mysql_query("SELECT VAL_DOUBLE FROM REGISTRY WHERE NAME='VK1_CALC_FAKTOR'", $db_id);
    $vk1_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    $res_id = mysql_query("SELECT VAL_DOUBLE FROM REGISTRY WHERE NAME='VK2_CALC_FAKTOR'", $db_id);
    $vk2_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    $res_id = mysql_query("SELECT VAL_DOUBLE FROM REGISTRY WHERE NAME='VK3_CALC_FAKTOR'", $db_id);
    $vk3_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    $res_id = mysql_query("SELECT VAL_DOUBLE FROM REGISTRY WHERE NAME='VK4_CALC_FAKTOR'", $db_id);
    $vk4_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);
    $res_id = mysql_query("SELECT VAL_DOUBLE FROM REGISTRY WHERE NAME='VK5_CALC_FAKTOR'", $db_id);
    $vk5_ar = mysql_fetch_array($res_id, MYSQL_ASSOC);
    mysql_free_result($res_id);

    $result = array();

    $result['VK1'] = $vk1_ar['VAL_DOUBLE'];
    $result['VK2'] = $vk2_ar['VAL_DOUBLE'];
    $result['VK3'] = $vk3_ar['VAL_DOUBLE'];
    $result['VK4'] = $vk4_ar['VAL_DOUBLE'];
    $result['VK5'] = $vk5_ar['VAL_DOUBLE'];

    return $result;
  }

function get_group($db_id)
  {
    $res_id = mysql_query("SELECT NAME, ID FROM WARENGRUPPEN ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_country($db_id)
  {
    $res_id = mysql_query("SELECT NAME, ID FROM LAND ORDER BY ID ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    $data[0]['NAME'] = "";
    $data[0]['ID'] = "";

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_manufacturer($db_id)
  {
    $res_id = mysql_query("SELECT HERSTELLER_NAME AS NAME, HERSTELLER_ID AS ID FROM HERSTELLER ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    $data[0]['NAME'] = "";
    $data[0]['ID'] = "";

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }

function get_mengeneinheit($db_id)
  {
    $res_id = mysql_query("SELECT BEZEICHNUNG AS NAME, REC_ID AS ID FROM MENGENEINHEIT ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }


function get_mwst($db_id)
  {
    $res_id = mysql_query("SELECT * FROM REGISTRY WHERE MAINKEY='MAIN\\\\MWST' ORDER BY NAME ASC", $db_id);
    $data = array();
    $number = mysql_num_rows($res_id);

    for($i=0; $i<$number; $i++)
      {
        array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
      }
    mysql_free_result($res_id);

    return $data;
  }


function article_update($data, $id, $db_id)
  {
    $data['EK_PREIS'] = str_replace(",", ".", $data['EK_PREIS']);		// EK formatieren
    $data['EK_PREIS'] = str_replace("€", "", $data['EK_PREIS']);
    $data['INVENTUR_WERT'] = str_replace(",", ".", $data['INVENTUR_WERT']);	// INV formatieren
    $data['INVENTUR_WERT'] = str_replace("%", "", $data['INVENTUR_WERT']);
    $data['MENGE_MIN'] = str_replace(",", ".", $data['MENGE_MIN']);		// usw.
    $data['MENGE_AKT'] = str_replace(",", ".", $data['MENGE_AKT']);
    $data['MENGE_BVOR'] = str_replace(",", ".", $data['MENGE_BVOR']);
    $data['GEWICHT'] = str_replace(",", ".", $data['GEWICHT']);

    if($data['ARTIKELTYP_TXT']=="Artikel mit Stückliste")			// Artikeltyp herausfinden
      {
        $data['ARTIKELTYP'] = "S";
      }
    elseif($data['ARTIKELTYP_TXT']=="Lohn")
      {
        $data['ARTIKELTYP'] = "L";
      }
    elseif($data['ARTIKELTYP_TXT']=="Transportkosten")
      {
        $data['ARTIKELTYP'] = "K";
      }
    elseif($data['ARTIKELTYP_TXT']=="Text / Kommentar")
      {
        $data['ARTIKELTYP'] = "T";
      }
    else
      {
        $data['ARTIKELTYP'] = "N";
      }


    $wg_temp1 = explode("[", $data['WARENGRUPPE_TXT']);				// Herausschälen der ID
    $wg_temp2 = explode("]", $wg_temp1[1]);

    $group = get_group($db_id);							// ID der WG holen
    foreach($group as $set)
      {
        if($wg_temp2[0]==$set['ID'])
          {
            $data['WARENGRUPPE'] = $set['ID'];
          }
      }

    $hs_temp1 = explode("[", $data['HERSTELLER_ID_TXT']);			// Herausschälen der ID
    $hs_temp2 = explode("]", $hs_temp1[1]);

    $manufacturer = get_manufacturer($db_id);					// ID des HERST holen
    foreach($manufacturer as $set)
      {
        if($hs_temp2[0]==$set['ID'])
          {
            $data['HERSTELLER_ID'] = $set['ID'];
          }
      }

    $cn_temp = explode(" ", $data['HERKUNFTSLAND_TXT']);			// Herausschälen der ID
    $data['HERKUNFTSLAND'] = $cn_temp[0];					// ID des LAND holen

    $mwst_temp = explode(" ", $data['STEUER_CODE_TXT']);			// Herausschälen der ID
    $data['STEUER_CODE'] = $mwst_temp[0];					// ID des Steuersatzes

    $mwst_fak = ($mwst_temp[1] + 100) / 100;					// MwSt-Kalkulationsfaktor


    if(!$faktor = get_faktor($data['WARENGRUPPE'], $db_id))			// Kalkulationsfaktoren
      {
        $faktor = get_faktor_default($db_id);
		printf ($faktor['VK1']);
      }

    $data['VK1'] = $data['EK_PREIS'] * $faktor['VK1'];
    $data['VK2'] = $data['EK_PREIS'] * $faktor['VK2'];
    $data['VK3'] = $data['EK_PREIS'] * $faktor['VK3'];
    $data['VK4'] = $data['EK_PREIS'] * $faktor['VK4'];
    $data['VK5'] = $data['EK_PREIS'] * $faktor['VK5'];

    $data['VK1B'] = $data['VK1'] * $mwst_fak;
    $data['VK2B'] = $data['VK2'] * $mwst_fak;
    $data['VK3B'] = $data['VK3'] * $mwst_fak;
    $data['VK4B'] = $data['VK4'] * $mwst_fak;
    $data['VK5B'] = $data['VK5'] * $mwst_fak;

    $query = "UPDATE ARTIKEL SET
                MATCHCODE='".strtoupper(addslashes($data['MATCHCODE']))."',
                ARTNUM='".addslashes($data['ARTNUM'])."',
                ERSATZ_ARTNUM ='".addslashes($data['ERSATZ_ARTNUM'])."',
                WARENGRUPPE='".$data['WARENGRUPPE']."',
                BARCODE='".addslashes($data['BARCODE'])."',
                ARTIKELTYP='".$data['ARTIKELTYP']."',
                KURZNAME='".addslashes($data['KURZNAME'])."',
                LANGNAME='".addslashes($data['LANGNAME'])."',
                KAS_NAME='".addslashes($data['KAS_NAME'])."',
                INFO='".addslashes($data['INFO'])."',
                ME_ID='".addslashes($data['ME_ID'])."',
                VPE='".$data['VPE']."',
                LAENGE='".addslashes($data['LAENGE'])."',
                GROESSE='".addslashes($data['GROESSE'])."',
                DIMENSION='".addslashes($data['DIMENSION'])."',
                GEWICHT='".addslashes($data['GEWICHT'])."',
                INVENTUR_WERT='".$data['INVENTUR_WERT']."',
                EK_PREIS='".$data['EK_PREIS']."',
                VK1='".$data['VK1']."',
                VK2='".$data['VK2']."',
                VK3='".$data['VK3']."',
                VK4='".$data['VK4']."',
                VK5='".$data['VK5']."',
                VK1B='".$data['VK1B']."',
                VK2B='".$data['VK2B']."',
                VK3B='".$data['VK3B']."',
                VK4B='".$data['VK4B']."',
                VK5B='".$data['VK5B']."',
                STEUER_CODE='".$data['STEUER_CODE']."',
                MENGE_AKT='".$data['MENGE_AKT']."',
                MENGE_MIN='".$data['MENGE_MIN']."',
                MENGE_BVOR='".$data['MENGE_BVOR']."',
                ERLOES_KTO='".$data['ERLOES_KTO']."',
                AUFW_KTO='".$data['AUFW_KTO']."',
                HERKUNFTSLAND='".$data['HERKUNFTSLAND']."',
                HERSTELLER_ID='".$data['HERSTELLER_ID']."',
                HERST_ARTNUM='".addslashes($data['HERST_ARTNUM'])."',
                LAGERORT='".addslashes($data['LAGERORT'])."',
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
        return 1;
      }
  }

function article_add($data, $db_id)
  {
    // Nächste zu vergebende Artikelnummer aus DB holen

    $rec_id = mysql_query("SELECT VAL_INT2, VAL_INT3 FROM REGISTRY WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='ARTIKELNUMMER'", $db_id);
    $rec_tmp = mysql_fetch_array($rec_id, MYSQL_ASSOC);
    mysql_free_result($rec_id);

    $l_template = $rec_tmp['VAL_INT3'];
    $l_current = strlen($rec_tmp['VAL_INT2']);
    $l_diff = $l_template - $l_current;

    $data['ARTNUM'] = "";					// String mit führenden Nullen bauen

    while($l_diff)
      {
        $data['ARTNUM'] .= "0";
        $l_diff--;
      }

    $data['ARTNUM'] .= $rec_tmp['VAL_INT2'];			// String komplett, neue NEXT_ARTNUM in REGISTRY eintragen

    $rec_tmp['VAL_INT2']++;

    $rec_id = mysql_query("UPDATE REGISTRY SET VAL_INT2='".$rec_tmp['VAL_INT2']."' WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='ARTIKELNUMMER'", $db_id);


    // Weiter im Text

    $data['EK_PREIS'] = str_replace(",", ".", $data['EK_PREIS']);		// EK formatieren
    $data['EK_PREIS'] = str_replace("€", "", $data['EK_PREIS']);
    $data['INVENTUR_WERT'] = str_replace(",", ".", $data['INVENTUR_WERT']);	// INV formatieren
    $data['INVENTUR_WERT'] = str_replace("%", "", $data['INVENTUR_WERT']);
    $data['MENGE_MIN'] = str_replace(",", ".", $data['MENGE_MIN']);		// usw.
    $data['MENGE_AKT'] = str_replace(",", ".", $data['MENGE_AKT']);
    $data['MENGE_BVOR'] = str_replace(",", ".", $data['MENGE_BVOR']);
    $data['GEWICHT'] = str_replace(",", ".", $data['GEWICHT']);

    if($data['ARTIKELTYP_TXT']=="Artikel mit Stückliste")			// Artikeltyp herausfinden
      {
        $data['ARTIKELTYP'] = "S";
      }
    elseif($data['ARTIKELTYP_TXT']=="Lohn")
      {
        $data['ARTIKELTYP'] = "L";
      }
    elseif($data['ARTIKELTYP_TXT']=="Transportkosten")
      {
        $data['ARTIKELTYP'] = "K";
      }
    elseif($data['ARTIKELTYP_TXT']=="Text / Kommentar")
      {
        $data['ARTIKELTYP'] = "T";
      }
    else
      {
        $data['ARTIKELTYP'] = "N";
      }

    $wg_temp1 = explode("[", $data['WARENGRUPPE_TXT']);				// Herausschälen der ID
    $wg_temp2 = explode("]", $wg_temp1[1]);

    $group = get_group($db_id);							// ID der WG holen
    foreach($group as $set)
      {
        if($wg_temp2[0]==$set['ID'])
          {
            $data['WARENGRUPPE'] = $set['ID'];
          }
      }

    $hs_temp1 = explode("[", $data['HERSTELLER_ID_TXT']);			// Herausschälen der ID
    $hs_temp2 = explode("]", $hs_temp1[1]);

    $manufacturer = get_manufacturer($db_id);					// ID des HERST holen
    foreach($manufacturer as $set)
      {
        if($hs_temp2[0]==$set['ID'])
          {
            $data['HERSTELLER_ID'] = $set['ID'];
          }
      }

    $cn_temp = explode(" ", $data['HERKUNFTSLAND_TXT']);			// Herausschälen der ID
    $data['HERKUNFTSLAND'] = $cn_temp[0];					// ID des LAND holen

    $mwst_temp = explode(" ", $data['STEUER_CODE_TXT']);			// Herausschälen der ID
    $data['STEUER_CODE'] = $mwst_temp[0];					// ID des Steuersatzes

    $mwst_fak = ($mwst_temp[1] + 100) / 100;					// MwSt-Kalkulationsfaktor


    if(!$faktor = get_faktor($data['WARENGRUPPE'], $db_id))			// Kalkulationsfaktoren
      {
        $faktor = get_faktor_default($db_id);
      }

    $data['VK1'] = $data['EK_PREIS'] * $faktor['VK1'];
    $data['VK2'] = $data['EK_PREIS'] * $faktor['VK2'];
    $data['VK3'] = $data['EK_PREIS'] * $faktor['VK3'];
    $data['VK4'] = $data['EK_PREIS'] * $faktor['VK4'];
    $data['VK5'] = $data['EK_PREIS'] * $faktor['VK5'];

    $data['VK1B'] = $data['VK1'] * $mwst_fak;
    $data['VK2B'] = $data['VK2'] * $mwst_fak;
    $data['VK3B'] = $data['VK3'] * $mwst_fak;
    $data['VK4B'] = $data['VK4'] * $mwst_fak;
    $data['VK5B'] = $data['VK5'] * $mwst_fak;

    $query = "INSERT INTO ARTIKEL SET
                MATCHCODE='".strtoupper(addslashes($data['MATCHCODE']))."',
                ARTNUM='".addslashes($data['ARTNUM'])."',
                ERSATZ_ARTNUM ='".addslashes($data['ERSATZ_ARTNUM'])."',
                WARENGRUPPE='".$data['WARENGRUPPE']."',
                BARCODE='".addslashes($data['BARCODE'])."',
                ARTIKELTYP='".$data['ARTIKELTYP']."',
                KURZNAME='".addslashes($data['KURZNAME'])."',
                LANGNAME='".addslashes($data['LANGNAME'])."',
                KAS_NAME='".addslashes($data['KAS_NAME'])."',
                INFO='".addslashes($data['INFO'])."',
                ME_ID='".addslashes($data['ME_ID'])."',
                VPE='".$data['VPE']."',
                LAENGE='".addslashes($data['LAENGE'])."',
                GROESSE='".addslashes($data['GROESSE'])."',
                DIMENSION='".addslashes($data['DIMENSION'])."',
                GEWICHT='".addslashes($data['GEWICHT'])."',
                INVENTUR_WERT='".$data['INVENTUR_WERT']."',
                EK_PREIS='".$data['EK_PREIS']."',
                VK1='".$data['VK1']."',
                VK2='".$data['VK2']."',
                VK3='".$data['VK3']."',
                VK4='".$data['VK4']."',
                VK5='".$data['VK5']."',
                VK1B='".$data['VK1B']."',
                VK2B='".$data['VK2B']."',
                VK3B='".$data['VK3B']."',
                VK4B='".$data['VK4B']."',
                VK5B='".$data['VK5B']."',
                STEUER_CODE='".$data['STEUER_CODE']."',
                MENGE_AKT='".$data['MENGE_AKT']."',
                MENGE_MIN='".$data['MENGE_MIN']."',
                MENGE_BVOR='".$data['MENGE_BVOR']."',
                ERLOES_KTO='".$data['ERLOES_KTO']."',
                AUFW_KTO='".$data['AUFW_KTO']."',
                HERKUNFTSLAND='".$data['HERKUNFTSLAND']."',
                HERSTELLER_ID='".$data['HERSTELLER_ID']."',
                HERST_ARTNUM='".addslashes($data['HERST_ARTNUM'])."',
                LAGERORT='".addslashes($data['LAGERORT'])."',
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
                $_POST['GEAEND_NAME'] = $usr_name;
                article_update($_POST, $_GET['id'], $db_id);
              }
            elseif($_POST['TYPE']=="add")
              {
                $_POST['ERST_NAME'] = $usr_name;
                $_POST['GEAEND_NAME'] = $usr_name;
                $_GET['id'] = article_add($_POST, $db_id);
              }
          }

        $res_id = mysql_query("SELECT * FROM ARTIKEL WHERE REC_ID=".$_GET['id'], $db_id);
        $data = mysql_fetch_array($res_id, MYSQL_ASSOC);
        mysql_free_result($res_id);

        $group = get_group($db_id);
        $country = get_country($db_id);
        $manufacturer = get_manufacturer($db_id);
		$mengeneinheit = get_mengeneinheit($db_id);
        $mwst = get_mwst($db_id);

        $o_cont = print_main($data, $group, $country, $manufacturer, $mengeneinheit, $mwst, "update", $_GET['target'], $_GET['id']);

        $o_java .= "function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=article&target=".$_GET['target']."&id=".$_GET['id']."';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    elseif($_GET['action']=="add")
      {
        $group = get_group($db_id);
        $country = get_country($db_id);
        $manufacturer = get_manufacturer($db_id);
		$mengeneinheit = get_mengeneinheit($db_id);
        $mwst = get_mwst($db_id);

        $o_cont = print_main($data, $group, $country, $manufacturer, $mengeneinheit, $mwst, "add", $_GET['target'], 'new');

        $o_java .= "
                   function set_navi()
                   {
                    parent.navi.location.href = 'navi.php?module=article&target=".$_GET['target']."&id=new';
                   }";

        $o_body = " onload=\"set_navi()\"";
      }
    else
      {
        // Suchparameter merken:

        if($_POST)
          {
            $_SESSION['art_type'] = $_POST['type'];
            $_SESSION['art_order'] = $_POST['order'];
            $_SESSION['art_limit'] = $_POST['limit'];
            $_SESSION['art_text'] = $_POST['text'];
            $_SESSION['art_lager'] = $_POST['lager'];
          }

        // Suchparameter

        if($_POST['type']=="Suchbegriff")
          {
            $abfrage['type'] = "MATCHCODE";
          }
        elseif($_POST['type']=="Text")
          {
            $abfrage['type'] = "KURZNAME";
          }
        elseif($_POST['type']=="Artikelnummer")
          {
            $abfrage['type'] = "ARTNUM";
          }
        elseif($_POST['type']=="Herstellernummer")
          {
            $abfrage['type'] = "HERST_ARTNUM";
          }
        elseif($_POST['type']=="Lief.-Bestellnr.")
          {
            $abfrage['type'] = "BESTNUM";
          }
        elseif($_POST['type']=="Info")
          {
            $abfrage['type'] = "INFO";
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

        if($_POST['lager']=="TRUE")
          {
            $abfrage['lager1'] = " AND MENGE_AKT>0";
            $abfrage['lager2'] = "WHERE MENGE_AKT>0";
          }
        else
          {
            $abfrage['lager1'] = "";
            $abfrage['lager2'] = "";
          }


        if($_POST['text'] && ($_POST['type']=="Text"))				// SQL-Abfragen basteln
          {
            $abfrage['text'] = "WHERE (";
            $begriffe = explode(" ", $_POST['text']);
            $reset = count($begriffe);

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(KURZNAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].") AND ";
                $num--;
              }
            $abfrage['text'] .= "(KURZNAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].")) OR (";

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(LANGNAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].") AND ";
                $num--;
              }
            $abfrage['text'] .= "(LANGNAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].")) OR (";

            $num = $reset;
            $num--;		// letzte [id]

            while($num)
              {
                $abfrage['text'] .= "(KAS_NAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].") AND ";
                $num--;
              }
            $abfrage['text'] .= "(KAS_NAME LIKE '%".$begriffe[$num]."%'".$abfrage['lager1']."))";

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
                $abfrage['text'] .= "(MATCHCODE LIKE '%".$begriffe[$num]."%'".$abfrage['lager1'].") AND ";
                $num--;
              }
            $abfrage['text'] .= "(MATCHCODE LIKE '%".$begriffe[$num]."%'".$abfrage['lager1']."))";

            if($abfrage['lager'])
              {
                $abfrage['text'] .= " AND ".$abfrage['lager'];
              }

            // echo $abfrage['text']."<br>";			// Debug
          }
        elseif($_POST['text'] && ($_POST['type']!="Text") && ($_POST['type']!="Suchbegriff"))
          {
            $abfrage['text'] = "WHERE ".$abfrage['type']." LIKE '%".str_replace(" ", "%", $_POST['text'])."%'".$abfrage['lager1']."";
          }
        else
          {
            $abfrage['text'] = "";
          }

        if($abfrage['type']=="BESTNUM")
          {
            $res_id = mysql_query("SELECT ARTIKEL_ID FROM ARTIKEL_PREIS WHERE BESTNUM LIKE '%".str_replace(" ", "%", $_POST['text'])."%' ORDER BY ARTIKEL_ID ".$abfrage['order']." LIMIT ".$abfrage['limit'], $db_id);
            $first = array();
            $data = array();
            $number = mysql_num_rows($res_id);

            for($i=0; $i<$number; $i++)
              {
                array_push($first, mysql_fetch_array($res_id, MYSQL_ASSOC));
              }
            mysql_free_result($res_id);

            foreach($first as $row)
              {
                $res_id = mysql_query("SELECT REC_ID, MATCHCODE, KURZNAME, ARTNUM, MENGE_AKT, ME_ID, EK_PREIS, VK1, VK2, VK3, VK4, VK5 FROM ARTIKEL WHERE REC_ID=".$row['ARTIKEL_ID'].$abfrage['lager1'], $db_id);
                $thisrow = mysql_fetch_array($res_id, MYSQL_ASSOC);
                if($thisrow['REC_ID'])
                  {
                    array_push($data, $thisrow);
                  }
                mysql_free_result($res_id);
              }
          }
        else
          {
            if($abfrage['lager1'] && $abfrage['text'])
              {
                $temp = $abfrage['lager1'];
              }
            elseif($abfrage['lager2'] && !$abfrage['text'])
              {
                $temp = $abfrage['lager2'];
              }
            else
              {
                $temp = "";
              }
            $res_id = mysql_query("SELECT REC_ID, MATCHCODE, KURZNAME, ARTNUM, MENGE_AKT, ME_ID, EK_PREIS, VK1, VK2, VK3, VK4, VK5 FROM ARTIKEL ".$abfrage['text'].$temp." ORDER BY ".$abfrage['type']." ".$abfrage['order']." LIMIT ".$abfrage['limit'], $db_id);
            $data = array();
            $number = mysql_num_rows($res_id);

            for($i=0; $i<$number; $i++)
              {
                array_push($data, mysql_fetch_array($res_id, MYSQL_ASSOC));
              }
            mysql_free_result($res_id);
          }

        $o_cont = "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"../images/leer.gif\"></td><td>&nbsp;Suchbegriff</td><td>&nbsp;Art.-Nr.</td><td>&nbsp;Kurzname</td><td>&nbsp;Menge</td><td>&nbsp;ME-Einh.</td><td>&nbsp;EK-Preis</td><td>&nbsp;VK1 N</td><td>&nbsp;VK2 N</td><td>&nbsp;VK3 N</td><td>&nbsp;VK4 N</td><td>&nbsp;VK5 N</td></tr>";
        foreach($data as $row)
          {
            if(strlen($row['MATCHCODE'])>30)
              {
                $tmp = str_split($row['MATCHCODE'], 30);
                $row['MATCHCODE'] = $tmp[0]."...";
              }
            if(strlen($row['KURZNAME'])>40)
              {
                $tmp = str_split($row['KURZNAME'], 40);
                $row['KURZNAME'] = $tmp[0]."...";
              }

            $color++;
            if($color%2)
              {
                $o_cont .= "<tr bgcolor=\"#ffffff\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".strtoupper($row['MATCHCODE'])."</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ARTNUM']."</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KURZNAME']."</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['MENGE_AKT'], 2, ',', '.')."&nbsp;</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ME_ID']."</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['EK_PREIS'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK1'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK2'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK3'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK4'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK5'], 2, ',', '.')." &euro;&nbsp;</a></td></tr>";
              }
            else
              {
                $o_cont .= "<tr bgcolor=\"#ffffdd\"><td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"../images/leer.gif\"></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".strtoupper($row['MATCHCODE'])."</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ARTNUM']."</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['KURZNAME']."</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['MENGE_AKT'], 2, ',', '.')."&nbsp;</a></td><td>&nbsp;<a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".$row['ME_ID']."</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['EK_PREIS'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK1'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK2'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK3'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK4'], 2, ',', '.')." &euro;&nbsp;</a></td><td align=\"right\"><a href=\"main.php?module=article&action=detail&target=".$_GET['target']."&id=".$row['REC_ID']."\">".number_format($row['VK5'], 2, ',', '.')." &euro;&nbsp;</a></td></tr>";
              }
           }
         $o_cont .= "</table>";

         $o_java .= "function set_navi()
                     {
                      parent.navi.location.href = 'navi.php?module=article&target=".$_GET['target']."';
                     }";

         $o_body = " onload=\"set_navi()\"";
      }
  }
else
  {
    $o_cont = "<div align=\"center\"><br><br><br><h1>Zugriff verweigert!</h1><br><br><br></div>";
  }

?>