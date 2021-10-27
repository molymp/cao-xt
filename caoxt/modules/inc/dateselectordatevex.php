<?php
		$dateselector = "<table width=\"150\" cellpadding=\"0\" cellspacing=\"0\"><form action=\"main.php\" method=\"GET\" enctype=\"text/plain\"><tr><td align=\"right\"><input type=\"hidden\" name=\"section\" value=\"" . $_GET['section'] . "\"><input type=\"hidden\" name=\"module\" value=\"" . $_GET['module'] . "\"><select name=\"month\" size=\"1\" class=\"snav\">";
		if ($month == 1) $dateselector .= "<option value=\"1\" selected>Januar</option>";
		else $dateselector .= "<option value=\"1\">Januar</option>";
		if ($month == 2) $dateselector .= "<option value=\"2\" selected>Februar</option>";
		else  $dateselector .= "<option value=\"2\">Februar</option>";
		if ($month == 3) $dateselector .= "<option value=\"3\" selected>M&auml;rz</option>";
		else $dateselector .= "<option value=\"3\">M&auml;rz</option>";
		if ($month == 4) $dateselector .= "<option value=\"4\" selected>April</option>";
		else $dateselector .= "<option value=\"4\">April</option>";
		if ($month == 5) $dateselector .= "<option value=\"5\" selected>Mai</option>";
		else $dateselector .= "<option value=\"5\">Mai</option>";
		if ($month == 6) $dateselector .= "<option value=\"6\" selected>Juni</option>";
		else $dateselector .= "<option value=\"6\">Juni</option>";
		if ($month == 7) $dateselector .= "<option value=\"7\" selected>Juli</option>";
		else $dateselector .= "<option value=\"7\">Juli</option>";
		if ($month == 8) $dateselector .= "<option value=\"8\" selected>August</option>";
		else $dateselector .= "<option value=\"8\">August</option>";
		if ($month == 9) $dateselector .= "<option value=\"9\" selected>September</option>";
		else $dateselector .= "<option value=\"9\">September</option>";
		if ($month == 10) $dateselector .= "<option value=\"10\" selected>Oktober</option>";
		else $dateselector .= "<option value=\"10\">Oktober</option>";
		if ($month == 11) $dateselector .= "<option value=\"11\" selected>November</option>";
		else $dateselector .= "<option value=\"11\">November</option>";
		if ($month == 12) $dateselector .= "<option value=\"12\" selected>Dezember</option>";
		else $dateselector .= "<option value=\"12\">Dezember</option>";
		if ($month == 20) $dateselector .= "<option value=\"20\" selected>Alle Monate</option>";
		else $dateselector .= "<option value=\"20\">Alle Monate</option>";
		$dateselector .= "</select></td><td align=\"right\"><select name=\"year\" size=\"1\" class=\"snav\">";
		$dateselector .= "<option>" . ($year - 2) . "</option>";
		$dateselector .= "<option>" . ($year - 1) . "</option>";
		$dateselector .= "<option selected>" . $year . "</option>";
		$dateselector .= "<option>" . ($year + 1) . "</option>";
		$dateselector .= "<option>" . ($year + 2) . "</option>";
		$dateselector .= "</select></td><td align=\"right\"><input type=\"submit\" value=\" OK \" class=\"bnav\"></td></tr></form></table>";

?>