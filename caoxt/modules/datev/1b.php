<?php

###
### Teil 1   - Buchungen, die durch eine eingehende Lieferantenrechnung ausgelöst werden (Vorgang 3).
###            (Wareneingang an Verbindlichkeit)
###            Wir berücksichtigen alle Adressen, außer Kundengruppe 998 (Versorger). Diese werden in Teil 1.e behandelt.

##
##  Teil 1.b - Buchungen mit 19% USt.

$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF (j2.BSUMME_1 < 0,'S','H') as SollHabenKennzeichen,
replace(ABS(j2.BSUMME_1),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$WE19." as Gegenkonto,
j2.vrenum as Belegfeld1, 
## right(j2.ORGNUM,12) 
'' as Belegfeld2,
date_format(j2.RDATUM,'%d%m') as Datum,
j2.GEGENKONTO as Konto,
j2.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j2.KUN_NAME1, ' 19%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from journal j2
	 left outer JOIN ADRESSEN A on j2.ADDR_ID=A.REC_ID
where year(j2.rdatum) = ".$year."  and month(j2.RDATUM) = ".$month."
and j2.QUELLE in (5) and j2.QUELLE_SUB!=2
and j2.BSUMME_1 != 0 and j2.STADIUM < 127
AND A.KUNDENGRUPPE <> 998";

?>