<?php
// error_reporting(E_ALL); 
// ini_set("display_errors", true);

$o_head = "Datev-Export Habacher Dorfladen";
$o_navi = "";

$WE0 = 3200; $WE7 = 3300; $WE19 = 3400; $WE107 = 3540;	# WE = Wareneingang
$WA0 = 8200; $WA7 = 8300; $WA19 = 8400;					# WA = Warenausgang
$Forderungen = 1400;  $Verbindlichkeiten = 1600;
$Bank = 1200; $Kasse = 1000; $Geldtransit = 1360; $ECTransit = 1361; $Gutscheine = 1362;
$Festschreibungskennzeichen = 0;

if (!$usr_rights) 
{
	$o_cont = "<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
}
ELSE 
{
	date_default_timezone_set('CET');
	if (!$_GET['month']) {
		// Header: main.php?section=".$_GET['section']."&module=datevex
		$month = date("n");
		$year  = date("Y");
	} else {
		// Header: main.php?section=".$_GET['section']."&module=datevex&month=xx&year=xxxx
		$month = $_GET['month'];
		$year  = $_GET['year'];
	}
	include("modules/inc/dateselectordatevex.php");
	$o_navi = $dateselector;
	$sqlquery = '';
	include ('datev/1a.php');
	include ('datev/1b.php');
	include ('datev/1c.php');
	include ('datev/1d.php'); 
	include ('datev/1e.php');
	include ('datev/2.php');
	include ('datev/3a.php');
	include ('datev/3b.php');
	include ('datev/3c.php');
	include ('datev/4.php');
	include ('datev/5a.php');
	include ('datev/5b.php');
	include ('datev/5c.php');
	include ('datev/6.php');
	include ('datev/8.php');
	include ('datev/9.php');
	include ('datev/7a.php');
	include ('datev/7b.php');
	include ('datev/7c.php');
	$res_id = mysql_query($sqlquery, $db_id);
	$res_num = mysql_numrows($res_id);
	$result  = array();
	for ($i = 0; $i < $res_num; $i++) {
		array_push($result, mysql_fetch_array($res_id, MYSQL_ASSOC)); // Journaldatensätze in Array
	}
	mysql_free_result($res_id);
	$o_cont = "
	<table width=\"100%\"><tr bgcolor=\"#f4f0e8\"><td align=\"right\">";
	if ($_GET['action']!='save_csv') 
	{
		$o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=datevex&action=save_csv&month=".$month."&year=".$year."\" method='post' enctype='multipart/form-data' style='height:9px;'>
		<input type='submit' name='btn[save_csv]' value='CSV-Datei erstellen...'></form>";
	}
	if ($_GET['action']=='save_csv') 
	{
		include_once('includes/parsecsv.lib.php');
		$csv = new parseCSV();
		$csv->delimiter = "\t";
		$csv->encoding('ISO-8859-1', 'ISO-8859-1');
		$csv->parse('modules/datev/header.csv');
		$csv->data = $result;

		$filename = 'export/habadola2datev_' . $year . '-' . $month . '_as-of_' . date("Y-m-d_H-i-s") . '.csv';
		$csv->save($filename);
		$o_cont .= "<form action=\"main.php?section=".$_GET['section']."&module=datevex&action=send_csv&month=".$month."&year=".$year."&filename=".$filename."\" method='post' enctype='multipart/form-data' style='height:9px;'>
		<a href=\"".$filename."\">".$filename."</a>
		<input type='submit' name='btn[upload]' value='...und per Email verschicken'></form>";
	}
	if ($_GET['action']=='send_csv') 
	{
		require 'includes/PHPMailer/PHPMailerAutoload.php';
		$mail = new PHPMailer;
		$mail->isSMTP();
		$mail->Host = 'smtp.udag.de';
		$mail->SMTPAuth = true;
		$mail->Username = 'habacher-dorfladende-0007';   // SMTP username
		$mail->Password = 'SUN_leit';                    // SMTP password
		$mail->SMTPSecure = 'tls';                       // Enable TLS encryption, `ssl` also accepted
		$mail->Port = 587;                               // TCP port to connect to
		$mail->setFrom('g.bierbichler@t-online.de', 'Gabi Bierbichler');
		$mail->addAddress('peggywoerle@t-online.de', 'Peggy Wöhrle');     // Add a recipient, Name is optional
		$mail->addReplyTo('g.bierbichler@t-online.de', 'Gabi Bierbichler');
		$mail->addCC('marc.ledermann@gmail.com', 'Marc Ledermann');
		$mail->addCC('g.bierbichler@t-online.de', 'Gabi Bierbichler');
		$mail->addAttachment($_GET['filename']);         // Add attachments
		$mail->isHTML(true);                             // Set email format to HTML
		$mail->Subject = 'Habacher Dorfladen - DATEV-Export ' . $month . '-' . $year;
		$mail->Body    = 'Hallo,<br/><br/>anbei der DATEV-Export '.$month.'-'.$year.'<br/><br/>Viele Grüße,<br/>Das Habacher-Dorfladen-Team';
		$mail->AltBody = 'Hallo, anbei der DATEV-Export '.$month.'-'.$year.' Viele Grüße, Das Habacher-Dorfladen-Team';
		if(!$mail->send()) {
			$o_cont .= "Message could not be sent.";
			$o_cont .= "Mailer Error: " . $mail->ErrorInfo;
		} else {
			$o_cont .= "EMAIL GESENDET";
		}		
	}
	$o_cont .= "</td></tr></table>";
	$o_cont .= "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"1\"><tr bgcolor=\"#d4d0c8\"><td width=\"16\"><img src=\"images/leer.gif\"></td><td align=\"right\">Waehrung</td><td align=\"right\">S/H</td><td align=\"right\">Umsatz</td><td align=\"right\">Gegenkonto</td><td>Belegfeld1</td><td align=\"right\">Datum</td><td align=\"right\">Konto</td><td align=\"right\">Skonto</td><td>Buchungstext</td></tr>";
	foreach ($result as $row) {
		$color++;
		$o_cont .= "<tr bgcolor=\"";
		if ($color % 2) {$o_cont .= "#ffffff";} else {$o_cont .= "#ffffdd";}
		$o_cont .= "\">
		<td width=\"16\" bgcolor=\"#d4d0c8\"><img src=\"images/leer.gif\"></td>
		<td align=\"right\">" . $row['Waehrungskennung'] . "</td>
		<td align=\"right\">" . $row['SollHabenKennzeichen'] . "</td>
		<td align=\"right\">" . number_format($row['Umsatz'], 2, ",", ".") . "&nbsp;&euro;</td>
		<td align=\"right\">" . $row['Gegenkonto'] . "</td>
		<td>" . $row['Belegfeld1'] . "</td>
		<td align=\"right\">" . $row['Datum'] . "</td>
		<td align=\"right\">" . $row['Konto'] . "</td>
		<td align=\"right\">";
		if ($row['Skonto']) $o_cont .= number_format($row['Skonto'], 2, ",", ".") . "&nbsp;&euro;";
		$o_cont .= "</td>
		<td>" . $row['Buchungstext'] . "</td>
		</tr>";
		}
	$o_cont .= "</table>";
} 
?>