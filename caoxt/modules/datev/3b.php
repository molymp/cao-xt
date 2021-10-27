<?php

###  Teil 3 - Buchungen die durch ausgehende Rechnungen an Kunden ausgelöst werden (Vorgang 1)
###  Forderung an Umsatzerlöse

## Teil 3.b -- 19% USt.

$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF (j6.BSUMME_1<0,'S','H') as SollHabenKennzeichen,
replace(ABS(j6.BSUMME_1),'.',',') as Umsatz,
'' as 'BUSchluessel',
j6.GEGENKONTO as Gegenkonto,
j6.vrenum as Belegfeld1, 
## right(j6.ORGNUM,12) 
'' as Belegfeld2,
date_format(j6.RDATUM,'%d%m') as Datum,
".$WA19." as Konto,
j6.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j6.KUN_NAME1, ' 19%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from journal j6
where year(j6.rdatum) = ".$year." and month(j6.RDATUM) = ".$month."
and j6.QUELLE in (3) and j6.QUELLE_SUB!=2
and j6.BSUMME_1 != 0 and j6.STADIUM < 127";
?>