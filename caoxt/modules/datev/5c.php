<?php
###  Teil 5 - Kunden zahlen bar (Tageseinnahmen Kasse kummuliert) (Vorgang 5)
###  Kasse an Umsatzerlöse

##   Teil 5.c 7% USt.
$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF(SUM(j10.BSUMME_2)<0,'S','H') as SollHabenKennzeichen,
replace(ABS(SUM(j10.BSUMME_2)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Kasse." as Gegenkonto,
concat(date_format(j10.RDATUM,'%d%m'),'-',".$WA7.",'-',MIN(j10.VRENUM),'-',MAX(j10.VRENUM)) as Belegfeld1,
'' as Belegfeld2,
date_format(j10.RDATUM,'%d%m') as Datum,
".$WA7." as Konto,
'' as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j10.RDATUM,'%d%m'),'-',cast(".$WA7." as char),'-',MIN(j10.VRENUM),'-',MAX(j10.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j10
where year(j10.RDATUM) = ".$year." and month(j10.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j10.ZAHLART = 1
Group by day(RDATUM)";
?>