// Minimal single-page PDF writer (no dependencies). Used only when the real
// fixture PDFs in data/samples/ are not there yet, so the preview pane has
// something to show.

const WIN_ANSI = { '€': 0x80, '–': 0x96, '—': 0x97, '’': 0x92, '“': 0x93, '”': 0x94, '£': 0xa3, 'µ': 0xb5, '×': 0xd7, 'ß': 0xdf, 'ä': 0xe4, 'é': 0xe9, 'ö': 0xf6, 'ü': 0xfc, 'Ä': 0xc4, 'Ö': 0xd6, 'Ü': 0xdc, '°': 0xb0 };

function pdfString(s) {
  let out = '';
  for (const ch of s) {
    const code = ch.codePointAt(0);
    if (ch === '\\' || ch === '(' || ch === ')') out += '\\' + ch;
    else if (code >= 0x20 && code < 0x7f) out += ch;
    else if (WIN_ANSI[ch]) out += '\\' + WIN_ANSI[ch].toString(8).padStart(3, '0');
    else out += '?';
  }
  return `(${out})`;
}

/**
 * @param {{ heading: string, lines: string[], footer: string, scanned?: boolean }} doc
 * @returns {Buffer}
 */
export function buildPdf({ heading, lines, footer, scanned = false }) {
  const ops = [];
  if (scanned) {
    // A faint grey wash and a slight rotation hint that this stands in for a scan.
    ops.push('0.96 0.96 0.94 rg 0 0 595 842 re f');
  }
  ops.push('0.12 0.16 0.22 rg');
  ops.push(`BT /F2 16 Tf 1 0 0 1 56 780 Tm ${pdfString(heading)} Tj ET`);
  let y = 752;
  for (const raw of lines) {
    if (raw === '') { y -= 8; continue; }
    const bold = raw === 'INVOICE' || raw.startsWith('Description');
    const size = raw === 'INVOICE' ? 13 : 10;
    ops.push(`BT /${bold ? 'F2' : 'F1'} ${size} Tf 1 0 0 1 56 ${y} Tm ${pdfString(raw)} Tj ET`);
    y -= size + 6;
  }
  ops.push('0.45 0.5 0.56 rg');
  ops.push(`BT /F1 8 Tf 1 0 0 1 56 40 Tm ${pdfString(footer)} Tj ET`);
  const content = ops.join('\n');

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>',
    `<< /Length ${Buffer.byteLength(content, 'latin1')} >>\nstream\n${content}\nendstream`,
  ];
  let body = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n';
  const offsets = [];
  objects.forEach((o, i) => {
    offsets.push(Buffer.byteLength(body, 'latin1'));
    body += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body, 'latin1');
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.forEach((off) => { body += `${String(off).padStart(10, '0')} 00000 n \n`; });
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}
