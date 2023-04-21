<?php

###
### Teil 1   - Buchungen, die durch eine eingehende Lieferantenrechnung ausgelöst werden (Vorgang 3).
###            (Wareneingang an Verbindlichkeit)
###            Wir berücksichtigen alle Adressen, außer Kundengruppe 998 (Versorger). Diese werden in Teil 1.e behandelt.

##
##  Teil 1.d - Buchungen mit 9% USt.
##
##  2023-04-21 - Geänderter Steuersatz - ist: 9% war: 10,7%
##
$sqlquery .= "
UNION
select 
'EUR' as 'Waehrungskennung',
IF (j4.BSUMME_3 < 0,'S','H') as SollHabenKennzeichen,
replace(ABS(j4.BSUMME_3),'.',',') as Umsatz,
'' as 'BUSchluessel',
".$WE107." as Gegenkonto,
j4.vrenum as Belegfeld1, 
## right(j4.ORGNUM,12) 
'' as Belegfeld2,
date_format(j4.RDATUM,'%d%m') as Datum,
j4.GEGENKONTO as Konto,
j4.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
concat(j4.KUN_NAME1, ' 9%') as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from journal j4
	 left outer JOIN ADRESSEN A on j4.ADDR_ID=A.REC_ID
where year(j4.rdatum) = ".$year." and month(j4.RDATUM) = ".$month."
and j4.QUELLE in (5) and j4.QUELLE_SUB!=2
and j4.BSUMME_3 != 0 and j4.STADIUM < 127
AND A.KUNDENGRUPPE <> 998";
?>