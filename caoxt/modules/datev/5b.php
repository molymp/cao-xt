<?php
###  Teil 5 - Kunden zahlen bar (Tageseinnahmen Kasse kummuliert) (Vorgang 5)
###  Kasse an Umsatzerlöse

##   Teil 5.b 19% USt.
$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF(SUM(j9.BSUMME_1)<0,'S','H') as SollHabenKennzeichen,
replace(ABS(SUM(j9.BSUMME_1)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$Kasse." as Gegenkonto,
concat(date_format(j9.RDATUM,'%d%m'),'-',".$WA19.",'-',MIN(j9.VRENUM),'-',MAX(j9.VRENUM)) as Belegfeld1, 
'' as Belegfeld2,
date_format(j9.RDATUM,'%d%m') as Datum,
".$WA19." as Konto,
'' as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j9.RDATUM,'%d%m'),'-',cast(".$WA19." as char),'-',MIN(j9.VRENUM),'-',MAX(j9.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j9
where year(j9.RDATUM) = ".$year." and month(j9.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j9.ZAHLART = 1 
Group by day(RDATUM)";
?>