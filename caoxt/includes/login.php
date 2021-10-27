<?php

if(!$_SESSION['user'])
  {
    $o_login = "<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Login</h1></td></tr>
                <tr><td bgcolor=\"#808080\" align=\"center\">
                <form action=\"main.php?module=".$module."\" method=\"post\"><br>
                 Benutzer: <input name=\"user\" size=\"20\"><br>
                 Passwort: <input name=\"pass\" size=\"20\" type=\"password\"><br><br>
                 <input type=\"submit\" name=\"login\" value=\"Anmelden\">
                </form>
                </td></tr></table>";
  }
else
  {
    $o_login = "<table width=\"220\" cellpadding=\"2\" cellspacing=\"1\">
                <tr><td bgcolor=\"#808080\" align=\"center\"><h1>Login</h1></td></tr>
                <tr><td bgcolor=\"#808080\" align=\"center\">
                <form action=\"main.php?module=".$module."\" method=\"post\"><br>
                 Benutzer:<b> ".$usr_name."</b><br><br>
                 <input type=\"submit\" name=\"login\" value=\"Abmelden\">
                </form>
                </td></tr></table>";
  }

?>