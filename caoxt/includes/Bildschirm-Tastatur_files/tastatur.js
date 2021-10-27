function ergaenzeZeichen(zeichen) {
    taste = String.fromCharCode(zeichen);
    document.getElementById("text_box").innerHTML += taste;
}

function zeigeText() {
    alert(document.getElementById("text_box").innerHTML);
}

function loescheText() {
    document.getElementById("text_box").innerHTML = "";
}

function loeschenLetzten() {
    anzahl = document.getElementById("text_box").innerHTML.length;
    document.getElementById("text_box").innerHTML = document.getElementById("text_box").innerHTML.substr(0, anzahl-1);
}

function zeigeListe() {
    // mehrfaches  Einfuegen in die Liste vermeiden
    if (document.getElementById("text_box").innerHTML != "") {
        document.getElementById("listen_box").innerHTML += document.getElementById("text_box").innerHTML + '<br />';
    }
    // Loeschen nach Einfuegen, um Platz fuer neuen Namen zu machen
    loescheText();
}

function loescheListe() {
    document.getElementById("listen_box").innerHTML = "Liste:<br /><br />";
}

function macheKleineBuchstaben() {
    /*
    Die Redundanzen bei der Tastaturtabelle zu beseitigen lohnt sich nicht.
    Dazu sind die Tasten zu ungleichmaessig belegt.
    Um die Aufgabe trotzdem zu erfuellen, ergaenze ich eine Leiste mit den Kleinbuchstaben.
    Die sind lexikografisch geordnet, und dann ist eine Schleife sinnvoll.
    */
    for (var i = 97; i <= 122; ++i) {
        zeichen = String.fromCharCode(i);
        document.getElementById("kleine").innerHTML += '<button onclick="ergaenzeZeichen('+i+')">'+zeichen+'</button>';
    }
        document.getElementById("kleine").innerHTML += '<button onclick="ergaenzeZeichen(223)">ß</button>';
        document.getElementById("kleine").innerHTML += '<button onclick="ergaenzeZeichen(228)">ä</button>';
        document.getElementById("kleine").innerHTML += '<button onclick="ergaenzeZeichen(246)">ö</button>';
        document.getElementById("kleine").innerHTML += '<button onclick="ergaenzeZeichen(252)">ü</button>';
}

