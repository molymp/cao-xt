<?php
###  Teil 7 - Kunden zahlen mit EC-Karte (Tageseinnahmen Kasse kummuliert) (Vorgang 8)
###  Foerderung an Umsatzerlöse

##   Teil 7.b 19% USt.
$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF(SUM(j12.BSUMME_1)<0,'S','H') as SollHabenKennzeichen,
replace(ABS(SUM(j12.BSUMME_1)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$ECTransit." as Gegenkonto,
concat(date_format(j12.RDATUM,'%d%m'),'-',".$WA19.",'-',MIN(j12.VRENUM),'-',MAX(j12.VRENUM)) as Belegfeld1, 
'' as Belegfeld2,
date_format(j12.RDATUM,'%d%m') as Datum,
".$WA19." as Konto,
j12.gegenkonto as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j12.RDATUM,'%d%m'),'-',cast(".$WA19." as char),'-',MIN(j12.VRENUM),'-',MAX(j12.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j12
where year(j12.RDATUM) = ".$year." and month(j12.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j12.ZAHLART = 6 and j12.BSUMME_1 != 0
Group by day(RDATUM)";
?>