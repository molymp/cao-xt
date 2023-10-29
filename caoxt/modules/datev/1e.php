<?php

###
### Teil 1   - Buchungen, die durch eine eingehende Lieferantenrechnung ausgelöst werden (Vorgang 3).
###            (Wareneingang an Verbindlichkeit)

##
## Teil 1.e - Buchungen, die durch eine eingehende Versorger-Rechnung ausgelöst werden (Vorgang 10).
##            (diverse Konten an Verbindlichkeit)
##            Wir berücksichtigen hier nur Rechnungen von Adressen der Kundengruppe 998 (Versorger).

$sqlquery .= "
UNION
select
'EUR' as 'Waehrungskennung',
IF (jp20.GPREIS < 0,'S','H') as SollHabenKennzeichen,
CASE
	WHEN jp20.BRUTTO_FLAG = 'Y' # Abhängig von BRUTTO_FLAG geben wir den brutto-Wert direkt aus oder berechnen ihn erst:
	THEN
		CASE jp20.STEUER_CODE							# In JOURNALPOS sind die Artikelpreise BRUTTO. Wir brauchen brutto.
			when '0' then replace(ABS(jp20.GPREIS),'.',',')		#  0% MwSt.
			when '1' then replace(ABS(jp20.GPREIS),'.',',')		# 19% MwSt.
			when '2' then replace(ABS(jp20.GPREIS),'.',',')		#  7% MwSt.
		END
	ELSE
		CASE jp20.STEUER_CODE							# In JOURNALPOS sind die Artikelpreise NETTO. Wir brauchen brutto:
			when '0' then replace(ABS(round(jp20.GPREIS,2)),'.',',')			#  0% MwSt.
			when '1' then replace(ABS(round(jp20.GPREIS*1.19,2)),'.',',')	# 19% MwSt.
			when '2' then replace(ABS(round(jp20.GPREIS*1.07,2)),'.',',')	#  7% MwSt.
		END
END AS Umsatz,
'' as 'BUSchluessel',
CASE jp20.STEUER_CODE 							# Generiere aus Steuercode und A-Konto das Automatikkonto für Datev
	when '0' then concat('10',jp20.GEGENKTO)	#  0% MwSt.
	when '1' then concat('90',jp20.GEGENKTO)	# 19% MwSt.
	when '2' then concat('80',jp20.GEGENKTO)	#  7% MwSt.
END AS Gegenkonto,
j20.VRENUM as Belegfeld1,
'' as Belegfeld2,
date_format(j20.RDATUM,'%d%m') as Datum,
j20.GEGENKONTO as Konto,
j20.GEGENKONTO as Kostfeld1,
'' as Kostfeld2,
'' as Kostmenge,
'' as Skonto,
left(concat(left(A20.NAME1 ,19),'* ' ,j20.VRENUM,' ',COALESCE(jp20.BEZEICHNUNG,'')),60) as Buchungstext,
".$Festschreibungskennzeichen." as Festschreibung
from JOURNALPOS jp20
	left outer join JOURNAL j20 on j20.REC_ID = jp20.JOURNAL_ID
	left outer JOIN ADRESSEN A20 on j20.ADDR_ID = A20.REC_ID
where year(j20.RDATUM) = ".$year." and month(j20.RDATUM) = ".$month."
and j20.QUELLE in (5) and j20.QUELLE_SUB!=2
and j20.BSUMME_1 != 0 and j20.STADIUM < 127
and jp20.ARTIKELTYP != 'T'
and A20.KUNDENGRUPPE = 998";
?>