<?php

###  Teil 3 - Buchungen die durch ausgehende Rechnungen an Kunden ausgelöst werden (Vorgang 1)
###  Forderung an Umsatzerlöse

## Teil 3.c -- 7% USt.

$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF (j7.BSUMME_2<0,'S','H') as SollHabenKennzeichen,
replace(ABS(j7.BSUMME_2),'.',',') as Umsatz,
'' as 'BUSchluessel',
j7.GEGENKONTO as Gegenkonto,
j7.VRENUM as Belegfeld1,
## right(j7.ORGNUM,12)
'' as Belegfeld2,
date_format(j7.RDATUM,'%d%m') as Datum,
".$WA7." as Konto,
j7.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j7.KUN_NAME1, ' 7%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j7
where year(j7.RDATUM) = ".$year." and month(j7.RDATUM) = ".$month."
and j7.QUELLE in (3) and j7.QUELLE_SUB!=2
and j7.BSUMME_2 != 0 and j7.STADIUM < 127";
?>