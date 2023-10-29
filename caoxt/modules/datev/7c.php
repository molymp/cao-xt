<?php
###  Teil 7 - Kunden zahlen mit EC-Karte (Tageseinnahmen Kasse kummuliert) (Vorgang 8)
###  Foerderung an Umsatzerlöse

##   Teil 7.c 7% USt.
$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF(SUM(j13.BSUMME_2)+SUM(j13.BSUMME_3)<0,'S','H') as SollHabenKennzeichen,
replace(ABS(SUM(j13.BSUMME_2)+SUM(j13.BSUMME_3)),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$ECTransit."  as Gegenkonto,
concat(date_format(j13.RDATUM,'%d%m'),'-',".$WA7.",'-',MIN(j13.VRENUM),'-',MAX(j13.VRENUM)) as Belegfeld1,
'' as Belegfeld2,
date_format(j13.RDATUM,'%d%m') as Datum,
".$WA7." as Konto,
j13.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(date_format(j13.RDATUM,'%d%m'),'-',cast(".$WA7." as char),'-',MIN(j13.VRENUM),'-',MAX(j13.VRENUM)) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j13
where year(j13.RDATUM) = ".$year." and month(j13.RDATUM) = ".$month."
AND QUELLE_SUB=2 AND QUELLE=3 and j13.ZAHLART = 6 and ( j13.BSUMME_2 != 0 OR j13.BSUMME_3 != 0 )
Group by day(RDATUM)";
?>