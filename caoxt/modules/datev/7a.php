<?php
###  Teil 7 - Kunden zahlen mit EC-Karte (Tageseinnahmen Kasse kummuliert) (Vorgang 8)
###  Foerderung an Umsatzerlöse

##   Teil 7.a 0% USt.
$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF(SUM(j11.BSUMME_0)<0,'S','H') as SollHabenKennzeichen,
replace(ABS(SUM(j11.BSUMME_0)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$ECTransit." as Gegenkonto,
concat(date_format(j11.RDATUM,'%d%m'),'-',".$WA0.",'-',MIN(j11.VRENUM),'-',MAX(j11.VRENUM)) as Belegfeld1,
'' as Belegfeld2,
date_format(j11.RDATUM,'%d%m') as Datum,
".$WA0." as Konto,
j11.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j11.RDATUM,'%d%m'),'-',cast(".$WA0." as char),'-',MIN(j11.VRENUM),'-',MAX(j11.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j11
where year(j11.RDATUM) = ".$year." and month(j11.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j11.ZAHLART = 6 and j11.BSUMME_0 != 0
Group by day(RDATUM)";
?>