<?php

###
### Teil 1   - Buchungen, die durch eine eingehende Lieferantenrechnung ausgelöst werden (Vorgang 3).
###            (Wareneingang an Verbindlichkeit)
###            Wir berücksichtigen alle Adressen, außer Kundengruppe 998 (Versorger). Diese werden in Teil 1.e behandelt.

##
##  Teil 1.c - Buchungen mit 7% USt.

$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF (j3.BSUMME_2 < 0,'S','H') as SollHabenKennzeichen,
replace(ABS(j3.BSUMME_2),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$WE7." as Gegenkonto,
j3.vrenum as Belegfeld1, 
## right(j3.ORGNUM,12) 
'' as Belegfeld2,
date_format(j3.RDATUM,'%d%m') as Datum,
j3.GEGENKONTO as Konto,
j3.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j3.KUN_NAME1, ' 7%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from journal j3
	 left outer JOIN ADRESSEN A on j3.ADDR_ID=A.REC_ID
where year(j3.rdatum) = ".$year." and month(j3.RDATUM) = ".$month."
and j3.QUELLE in (5) and j3.QUELLE_SUB!=2
and j3.BSUMME_2 != 0 and j3.STADIUM < 127
AND A.KUNDENGRUPPE <> 998";

?>