# Dorfkern – Brand Assets

Single-Source-of-Truth für das Dorfkern-Logo und die Markenfarben. Wird von
allen 4 Apps (kasse / kiosk / orga / admin) unter der URL `/brand/...`
ausgeliefert; jede App stellt die Route selbst bereit.

## Dateien

| Datei | Zweck |
|---|---|
| `dorfkern-logo.js` | Einbindbares JS-Embed für das animierte Logo (horizontal / vertical / mark). Einzige Runtime-Datei. |
| `dorfkern-logo-demo.html` | Referenz-Demo (Claude.ai/design-Export); nicht in Produktion ausgeliefert. |
| `dk-brand.jsx` | React-Referenzimplementierung der statischen Marke (Claude.ai/design-Export); nicht in Produktion ausgeliefert. |

## Farb-Tokens

```
--ink             #141414
--cream           #f2ede3
--paper           #faf7f0
--sage            #d9dcc9
--terracotta      #b65c3a
--terracottaLight #e08a66
--nightInk        #1b2027
```

## Einbindung im Template

```html
<script src="/brand/dorfkern-logo.js" defer></script>
<div data-dorfkern-logo="horizontal" data-size="120" data-dot="true"></div>
```

Attribute: siehe Kopf der `dorfkern-logo.js`.

## Update-Prozess

Neue Version aus Claude.ai/design exportieren und diese Datei 1:1 ersetzen –
alle Apps ziehen das Update beim nächsten Deploy. Kein Build-Schritt nötig.
