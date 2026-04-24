// Shared Dorfkern mark + brand tokens, as plain-JSX functions.
// Included by both the animation file and the product-screens file.

const BRAND = {
  ink: '#141414',
  cream: '#f2ede3',
  paper: '#faf7f0',
  sage: '#d9dcc9',
  terracotta: '#b65c3a',
  terracottaLight: '#e08a66',
  nightInk: '#1b2027',
};

// Static mark
function DKMark({ size = 80, stroke = 3.2, color = BRAND.ink, accent = BRAND.terracotta, solidFloor = true }) {
  const dots = [];
  for (let r = 0; r < 4; r++) for (let c = 0; c < 5; c++) {
    const dx = c - 2, dy = r - 1.5;
    if (dx*dx + dy*dy > 4.8) continue;
    const isCenter = (r === 2 && c === 2);
    dots.push(
      <circle key={`${r}-${c}`} cx={22 + c*9} cy={34 + r*9} r={2.4}
        fill={isCenter ? accent : color}/>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 80 80">
      <path d="M6 28 L 40 4 L 74 28" fill="none" stroke={color} strokeWidth={stroke}
        strokeLinejoin="miter" strokeLinecap="square"/>
      <path d="M6 28 L 11 28" stroke={color} strokeWidth={stroke} strokeLinecap="square"/>
      <path d="M69 28 L 74 28" stroke={color} strokeWidth={stroke} strokeLinecap="square"/>
      {dots}
      {solidFloor && <path d="M10 72 L 70 72" stroke={color} strokeWidth={stroke} strokeLinecap="square"/>}
    </svg>
  );
}

function DKWordmark({ color = BRAND.ink, size = 40 }) {
  return (
    <span style={{ font:`500 ${size}px/1 Fraunces, serif`, letterSpacing:-0.8, color }}>Dorfkern</span>
  );
}

function DKLockup({ color = BRAND.ink, accent = BRAND.terracotta, size = 44, wmSize = 22, gap = 12 }) {
  return (
    <div style={{ display:'flex', alignItems:'center', gap }}>
      <DKMark size={size} stroke={size > 60 ? 3.0 : 2.4} color={color} accent={accent}/>
      <DKWordmark color={color} size={wmSize}/>
    </div>
  );
}

Object.assign(window, { BRAND, DKMark, DKWordmark, DKLockup });
