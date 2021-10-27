<?php
###  Teil 4 - Kunde begleicht Rechnung (Vorgang 2)
###  Bank an Forderungen

$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF (z2.BETRAG<0,'S','H') as SollHabenKennzeichen,
replace(ABS(z2.BETRAG),'.',',') as Umsatz,
'' as 'BUSchluessel',
z2.FIBU_KTO as Gegenkonto,
z2.BELEGNUM as Belegfeld1, 
## right(z2.JOURNAL_ID,12) 
'' as Belegfeld2,
date_format(z2.DATUM,'%d%m') as Datum,
z2.FIBU_GEGENKTO as Konto,
z2.FIBU_GEGENKTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
IF(z2.SKONTO_BETRAG!=0,replace(replace(z2.SKONTO_BETRAG,'.',','),'-',''),'') as Skonto,
z2.VERW_ZWECK as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from zahlungen z2
where year(z2.DATUM) = ".$year." and month(z2.DATUM) = ".$month."
and z2.QUELLE in (3)";
?>