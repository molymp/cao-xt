<?php
###  Teil 5 - Kunden zahlen bar (Tageseinnahmen Kasse kummuliert) (Vorgang 5)
###  Kasse an Umsatzerlöse

##   Teil 5.a 0% USt.

$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF(SUM(j8.BSUMME_0)<0,'S','H') as SollHabenKennzeichen,
##replace(ABS(j8.BSUMME_0),'.',',') as Umsatz,
replace(ABS(sum(j8.BSUMME_0)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Kasse." as Gegenkonto,
concat(date_format(j8.RDATUM,'%d%m'),'-',".$WA0.",'-',MIN(j8.VRENUM),'-',MAX(j8.VRENUM)) as Belegfeld1,
'' as Belegfeld2,
date_format(j8.RDATUM,'%d%m') as Datum,
".$WA0." as Konto,
'' as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j8.RDATUM,'%d%m'),'-',cast(".$WA0." as char),'-',MIN(j8.VRENUM),'-',MAX(j8.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j8
where year(j8.RDATUM) = ".$year." and month(j8.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j8.ZAHLART = 1
Group by day(RDATUM)";
?>