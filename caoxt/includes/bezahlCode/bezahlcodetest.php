<?php 
// die Bibliotheken um den QR-Code zu erzeugen
// basierend auf PHP QR Code encoder http://phpqrcode.sourceforge.net/
include "phpqrcode/qrlib.php"; 
// strtoupper wandelt keine Umlaute ausser man verändert die locale
setlocale (LC_ALL, 'de_DE@euro', 'de_DE', 'de', 'ge');

// generiert einen Bezahlcode und gibt diesen direkt als PNG-Bild aus
function generateBezahlCode($name, $blz, $kontonummer, $vwz, $betrag){
	try {
		// URL zusammensetzen
		$bezahlCode="bank://singlepayment?postingkey=69";
		$bezahlCode.="&name="   .encodeDtausString($name, 27);
		$bezahlCode.="&account=".encodeNumberString($kontonummer);
		$bezahlCode.="&BNC="    .encodeNumberString($blz);
		$bezahlCode.="&amount=" .encodeAmountString($betrag);
		$bezahlCode.="&reason=" .encodeDtausString($vwz, 54);
		// QR-Code erzeugen und ausgeben
		QRcode::pngWithBezahlCode($bezahlCode, false, "L", 100, 4, false);	
		// alternativ kann ein BezahlCode ohne Logo generiert werden,
		// es sind dann keine Anpassungen an der PHP QR Code Bibliothek nötig
		// QRcode::png($bezahlCode, false, "L", 100, 4, false);	
	} catch (Exception $e) {
		echo 'Es ist ein Fehler aufgetreten.',  $e->getMessage(), "\n";
	}
}

// Name und Verwendungsszweck müssen den DTAUS-Zeichensatz verwenden
function encodeDtausString($aString, $aAllowedLength = 27){
	$aString = strtoupper($aString);
	$aString = preg_replace('|[^0-9A-Z\s\.,&\-+*%/$ÄÖÜß]|m', '', $aString);
	
	if(strlen($aString) <= $aAllowedLength){
		return urlencode($aString);
	} else {
		throw new Exception('Empfängerbezeichnung zu lange.');
	}
}

// Der Betrag sollte ein Komma als Dezimaltrennzeichen verwenden und darf keine
// anderen Zeichen als Ziffern und das Komma enthalten
function encodeAmountString($aString){
	// Aufbau: 1-10 Ziffern [,1-2 Ziffern]
	// also 1 oder 1,1 oder 11111,11
	if(preg_match('/^\d{1,10}(?:,\d{1,2})?$/', $aString)){
		return urlencode($aString);
	} else {
		throw new Exception('Betrag ungültig formatiert.');	
	}
}

// BLZ und Konto-Nr dürfen nur aus Zahlen bestehen. 
function encodeNumberString($aString){
	// Aufbau: nur Ziffern
	if(preg_match('/^\d+$/', $aString)){
		return urlencode($aString);
	} else {
		throw new Exception('Zahl ungültig formatiert.');	
	}
}


// BEISPIELCODE um auf POST-Requests zu reagieren
// Für den Produktiv-Einsatz bitte anpassen oder entfernen
$name        = $_POST['name'];
$blz         = $_POST['blz'];
$kontonummer = $_POST['konto'];
$vwz         = $_POST['vwz'];
$betrag      = $_POST['betrag'];
generateBezahlCode($name,$blz,$kontonummer,$vwz,$betrag);
// ENDE BEISPIELCODE um auf POST-Requests zu reagieren

?>
