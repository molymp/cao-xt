<?php
###  Teil 8 - Wertstellung (valuta) der Tageseinnahmen auf dem Bankkonto (Vorgang 8)
###  Bank an Geldtransit
$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF(z3.BETRAG>0,'H','S') as SollHabenKennzeichen,
replace(ABS(z3.BETRAG),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Bank." as Gegenkonto,
concat('Banktransit ',date_format(z3.VALUTA,'%d%m'),' ',z3.BELEG) as Belegfeld1, 
'' as Belegfeld2,
date_format(z3.VALUTA,'%d%m') as Datum,
".$Geldtransit." as Konto,
'' as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat('Banktransit EUR ', z3.BETRAG ,' valuta ',date_format(z3.VALUTA,'%d.%m.'),' ',z3.BELEG) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from xt_ktoaus z3
where year(z3.VALUTA) = ".$year." and month(z3.VALUTA) = ".$month."
and z3.AUFTRAGSART = 'Einzahlungen' and z3.ZP_ZE = '' and z3.VERWENDUNGSZWECK = '' and z3.KTO_IBAN = '' and z3.BLZ_BIC = ''";
?>