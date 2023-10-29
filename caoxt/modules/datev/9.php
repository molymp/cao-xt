<?php
###  Teil 9 - Wertstellung (valuta) der EC-Zahlungen auf dem Bankkonto (Vorgang 9)
###  Bank an Forderungen
$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF(z3.BETRAG>0,'H','S') as SollHabenKennzeichen,
replace(ABS(z3.BETRAG),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Bank." as Gegenkonto,
concat('EC-Zahlungen ',date_format(z3.VALUTA,'%d%m'),' ',z3.BELEG) as Belegfeld1,
'' as Belegfeld2,
date_format(z3.VALUTA,'%d%m') as Datum,
".$ECTransit." as Konto,
'' as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat('EC-Zahlungen ', substr(z3.VERWENDUNGSZWECK, locate('TELECASH ',z3.VERWENDUNGSZWECK)+11, 4) ,' EUR ', z3.BETRAG ,' valuta ',date_format(z3.VALUTA,'%d.%m.'),' ',z3.BELEG) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from XT_KTOAUS z3
where year(z3.VALUTA) = ".$year." and month(z3.VALUTA) = ".$month."
and z3.ZP_ZE = 'HABACHER DORFLADE' and z3.VERWENDUNGSZWECK like '%TELECASH%' ";
?>