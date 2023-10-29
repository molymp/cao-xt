<?php

###
### Teil 1   - Buchungen, die durch eine eingehende Lieferantenrechnung ausgelöst werden (Vorgang 3).
###            (Wareneingang an Verbindlichkeit)
###            Wir berücksichtigen alle Adressen, außer Kundengruppe 998 (Versorger). Diese werden in Teil 1.e behandelt.

##
##  Teil 1.a - Buchungen mit 0% USt.

$sqlquery .= "
select 'EUR' as 'Waehrungskennung',
IF (j1.BSUMME_0 < 0,'S','H') as SollHabenKennzeichen,
replace(ABS(j1.BSUMME_0),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$WE0." as Gegenkonto,
j1.VRENUM as Belegfeld1,
'' as Belegfeld2,
date_format(j1.RDATUM,'%d%m') as Datum,
j1.GEGENKONTO as Konto,
j1.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j1.KUN_NAME1, ' 0%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNAL j1 left outer JOIN ADRESSEN A on j1.ADDR_ID=A.REC_ID
where year(j1.RDATUM) = ".$year."
and month(j1.RDATUM) = ".$month."
and j1.QUELLE in (5)
and j1.QUELLE_SUB!=2
and j1.BSUMME_0 != 0
and j1.STADIUM < 127
AND A.KUNDENGRUPPE <> 998";
?>