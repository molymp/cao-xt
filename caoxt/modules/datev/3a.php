<?php

###  Teil 3 - Buchungen die durch ausgehende Rechnungen an Kunden ausgelöst werden (Vorgang 1)
###  Forderung an Umsatzerlöse

## Teil 3.a -- 0% USt.

$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF (j5.BSUMME_0<0,'S','H') as SollHabenKennzeichen,
replace(ABS(j5.BSUMME_0),'.',',') as Umsatz,
'' as 'BUSchluessel',
j5.GEGENKONTO as Gegenkonto,
j5.VRENUM as Belegfeld1,
## right(j5.ORGNUM,12)
'' as Belegfeld2,
date_format(j5.RDATUM,'%d%m') as Datum,
".$WA0." as Konto,
j5.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j5.KUN_NAME1, ' 0%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j5
where year(j5.RDATUM) = ".$year." and month(j5.RDATUM) = ".$month."
and j5.QUELLE in (3) and j5.QUELLE_SUB!=2
and j5.BSUMME_0 != 0 and j5.STADIUM < 127";

?>