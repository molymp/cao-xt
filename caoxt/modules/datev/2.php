<?php

###  Teil 2 - Buchungen die durch das Begleichen von Lieferantenrechnungen ausgelöst werden (Vorgang 4)
###  Verbindlichkeiten an Bank

$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF (z1.BETRAG>0,'S','H') as SollHabenKennzeichen,
replace(ABS(z1.BETRAG),'.',',') as Umsatz,
'' as 'BUSchluessel',
z1.FIBU_GEGENKTO as Gegenkonto,
z1.BELEGNUM as Belegfeld1,
## right(z1.JOURNAL_ID,12)
'' as Belegfeld2,
date_format(z1.DATUM,'%d%m') as Datum,
z1.FIBU_KTO as Konto,
z1.FIBU_GEGENKTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
IF(z1.SKONTO_BETRAG!=0,replace(replace(z1.SKONTO_BETRAG,'.',','),'-',''),'') as Skonto,
z1.VERW_ZWECK as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from ZAHLUNGEN z1
where year(z1.DATUM) = ".$year." and month(z1.DATUM) = ".$month."
and z1.QUELLE in (5)";
?>