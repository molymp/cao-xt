<?php

print "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\">
<html>

<head>
 <meta http-equiv=\"content-type\" content=\"text/html; charset=iso-8859-1\">
 <meta http-equiv=\"language\" content=\"de\">
 <meta http-equiv=\"expires\" content=\"0\">
 <meta http-equiv=\"cache-control\" content=\"no-cache\">
 <meta http-equiv=\"pragma\" content=\"no-cache\">

 <meta name=\"author\" content=\"Marc Ledermann, Habacher Dorfladen UG\">
 <meta name=\"publisher\" content=\"Habacher Dorfladen\">
 <meta name=\"copyright\" content=\"Habacher Dorfladen\">
 <meta name=\"description\" content=\"Habacher Dorfladen CAO-XTensions\">

 <meta name=\"keywords\" content=\"\">
 <meta name=\"robots\" content=\"nofollow\">
 <title>
  Habacher Dorfladen
 </title>
 <link rel=\"icon\" href=\"favicon.ico\" type=\"image/ico\">
 <style type=\"text/css\">
  <!--
  body {  font: 10px Tahoma;  color: #000000; text-decoration: none; background: #d4d0c8}
  td {  font: 10px Tahoma;  color: #000000; text-decoration: none;}
  a {  font: 10px Tahoma;  color: #1e1e1e; text-decoration: none; cursor:default;}
  a:hover {  color: #000000; cursor:default;}
  h1 {  font: 12px Tahoma;  color: #ffffff; text-decoration: none; font-weight: bold;}
  h2 {  font: 32px Tahoma;  color: #000000; text-decoration: none; font-weight: bold;}
  h3 {  font: 12px Tahoma;  color: #000000; text-decoration: none; font-weight: bold;}

  .nav {  font: 10px Tahoma;  color: #ffffff; text-decoration: none;}
  .snav {  font: 9px Tahoma;  color: #000000; text-decoration: none; background: #d4d0c8}
  .bnav {  color: #000000; width: 30px; height: 16px; border: 0px; padding: 0px; background: #d4d0c8; font-size: 9px}
  .sma {  font: 2px Tahoma;}
  .head {  font: 14px Tahoma;  color: #ffffff; text-decoration: none; font-weight: bold;}
  -->
 </style>
</head>

<frameset rows=\"*,40\">
  <frame src=\"main.php?module=".$_GET['module']."&target=".$_GET['target']."\" name=\"main\">
  <frame src=\"navi.php?module=".$_GET['module']."&target=".$_GET['target']."\" name=\"navi\" scrolling=\"no\" noresize>
  <noframes>
    <body>
      <h1>Fehler</h1>
      <p>Ihr Browser unterst&uuml;tzt keine Frames!</p>
      <p>Die Navigationshilfen k&ouml;nnen daher leider nicht genutzt werden.</p>
    </body>
  </noframes>
</frameset>
</html>";
?>