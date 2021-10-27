<?php
###  Teil 6 - Tageseinnahmen werden aus der Kasse zur Bank gebracht (Vorgang 6)
###  Geldtransit an Kasse
$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF(z3.BETRAG>0,'S','H') as SollHabenKennzeichen,
replace(ABS(z3.BETRAG),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Geldtransit." as Gegenkonto,
concat('Banktransit_',date_format(z3.DATUM,'%d%m'),'_',z3.REC_ID) as Belegfeld1, 
'' as Belegfeld2,
date_format(z3.DATUM,'%d%m') as Datum,
z3.FIBU_KTO as Konto,
z3.FIBU_GEGENKTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(z3.VERW_ZWECK,' ',date_format(z3.DATUM,'%d%m')) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from zahlungen z3
where year(z3.DATUM) = ".$year." and month(z3.DATUM) = ".$month."
and z3.QUELLE in (99)";
?>