import { jsPDF } from 'jspdf';

const EXACT_DISCLAIMER = 'Heuristic indicator score, not a probability of fraud.';

const INK = [20, 20, 19];
const MUTED = [74, 72, 67];
const RULE = [200, 195, 184];
const PAPER = [250, 247, 242];
const CARD = [255, 255, 255];
const CHIP = [243, 239, 230];
const HIGH = [153, 27, 27];
const MID = [180, 83, 9];
const LOW = [22, 101, 52];

const GROUPS = [
  { status: 'indicator', heading: 'Raised the score', label: 'Indicator' },
  { status: 'clear', heading: 'Checked and did not raise the score', label: 'Clear' },
  { status: 'unknown', heading: 'Not checked', label: 'Not checked' },
];

function pdfSafe(value) {
  if (value == null) return '';
  return String(value)
    .replace(/\u2018|\u2019/g, "'")
    .replace(/\u201c|\u201d/g, '"')
    .replace(/\u2013|\u2014/g, '-')
    .replace(/\u2026/g, '...')
    .replace(/\u00a0/g, ' ')
    .replace(/[^\n\r\t\x20-\x7E\u00b7]/g, '');
}

function disclaimerText(report) {
  if (typeof report?.disclaimer === 'string' && report.disclaimer.length > 0) {
    return report.disclaimer;
  }
  return EXACT_DISCLAIMER;
}

function bandColor(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return INK;
  if (score >= 61) return HIGH;
  if (score >= 31) return MID;
  return LOW;
}

function formatReportDate(iso) {
  if (!iso) {
    return new Date().toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return pdfSafe(iso);
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function companyNameOf(report, companyFallback) {
  const name = report?.input_summary?.company_name || companyFallback || '';
  const trimmed = String(name).trim();
  return trimmed || 'Investigation';
}

export function reportPdfFilename(report, companyFallback = '') {
  const slug = pdfSafe(companyNameOf(report, companyFallback))
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48) || 'report';
  const score = report?.score == null || report.score === '' ? 'score' : String(report.score);
  return `TrustIntern-${slug}-${score}.pdf`;
}

function plannerLine(report) {
  if (!report?.planner_mode) return '';
  if (report.planner_mode === 'gemma') {
    return `Vision planner: open-weight ${report.model || 'Gemma 4'} (local Ollama)`;
  }
  return 'Vision planner: heuristic fallback (no live Gemma call)';
}

function createPainter(doc) {
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 54;
  const contentWidth = pageWidth - margin * 2;
  const footerTop = pageHeight - 40;
  let y = margin;

  function paintPaper() {
    doc.setFillColor(...PAPER);
    doc.rect(0, 0, pageWidth, pageHeight, 'F');
  }

  function continuation() {
    doc.addPage();
    paintPaper();
    y = 36;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(...INK);
    doc.text('TrustIntern', margin, y, { baseline: 'top' });
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(...MUTED);
    doc.text('Investigation report', pageWidth - margin, y + 1, {
      align: 'right',
      baseline: 'top',
    });
    doc.setDrawColor(...INK);
    doc.setLineWidth(0.8);
    doc.line(margin, y + 16, pageWidth - margin, y + 16);
    y = 64;
  }

  function ensure(height) {
    if (y + height > footerTop - 8) continuation();
  }

  function wrap(text, width, size, style, font = 'helvetica') {
    doc.setFont(font, style);
    doc.setFontSize(size);
    const lines = doc.splitTextToSize(text, width);
    if (Array.isArray(lines)) return lines.length ? lines : [''];
    return [String(lines)];
  }

  function writeLines(lines, x, size, style, color, lineGap, font = 'helvetica') {
    const lineHeight = size + lineGap;
    lines.forEach((line) => {
      ensure(lineHeight);
      doc.setFont(font, style);
      doc.setFontSize(size);
      doc.setTextColor(...color);
      doc.text(line, x, y, { baseline: 'top' });
      y += lineHeight;
    });
  }

  function writeWrapped(text, { size, style, color, width, indent = 0, lineGap = 4, font = 'helvetica', exact = false }) {
    const raw = exact ? String(text ?? '') : pdfSafe(text);
    const blocks = raw.split(/\n/);
    blocks.forEach((block, index) => {
      if (index > 0) y += 4;
      const lines = wrap(block.trim() === '' ? ' ' : block, width, size, style, font);
      writeLines(lines, margin + indent, size, style, color, lineGap, font);
    });
  }

  function gap(amount) {
    y += amount;
  }

  function hrule(weight, color, before = 0, after = 0) {
    y += before;
    ensure(weight + after + 2);
    doc.setDrawColor(...color);
    doc.setLineWidth(weight);
    doc.line(margin, y, pageWidth - margin, y);
    y += after;
  }

  return {
    doc,
    margin,
    pageWidth,
    contentWidth,
    footerTop,
    paintPaper,
    ensure,
    wrap,
    writeWrapped,
    gap,
    hrule,
    get y() {
      return y;
    },
    set y(value) {
      y = value;
    },
  };
}

function drawLetterhead(page, report, company) {
  const { doc, margin, pageWidth, contentWidth } = page;
  page.y = 42;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(20);
  doc.setTextColor(...INK);
  doc.text('TrustIntern', margin, page.y, { baseline: 'top' });

  const dateLabel = formatReportDate(report.created_at);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.setTextColor(...MUTED);
  doc.text(dateLabel, pageWidth - margin, page.y + 6, { align: 'right', baseline: 'top' });

  page.y += 24;
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(...MUTED);
  const kicker = report.id == null ? 'Investigation report' : `Investigation report  ·  No. ${report.id}`;
  doc.text(kicker, margin, page.y, { baseline: 'top' });
  page.y += 14;
  page.hrule(1.6, INK, 0, 14);

  page.writeWrapped(company, {
    size: 18,
    style: 'bold',
    color: INK,
    width: contentWidth,
    lineGap: 4,
  });

  const summary = report.input_summary || {};
  const identity = [summary.recruiter_name, summary.recruiter_email].filter(Boolean);
  if (identity.length) {
    page.gap(4);
    page.writeWrapped(identity.join('  |  '), {
      size: 10,
      style: 'normal',
      color: MUTED,
      width: contentWidth,
      lineGap: 3,
    });
  }
  if (summary.website_url) {
    page.gap(2);
    page.writeWrapped(summary.website_url, {
      size: 10,
      style: 'normal',
      color: MUTED,
      width: contentWidth,
      lineGap: 3,
    });
  }
  if (typeof summary.live_lookups === 'boolean') {
    page.gap(2);
    page.writeWrapped(summary.live_lookups ? 'Live lookups on' : 'Live lookups off', {
      size: 9,
      style: 'normal',
      color: MUTED,
      width: contentWidth,
      lineGap: 2,
    });
  }
  const planner = plannerLine(report);
  if (planner) {
    page.gap(2);
    page.writeWrapped(planner, {
      size: 9,
      style: 'italic',
      color: MUTED,
      width: contentWidth,
      lineGap: 2,
    });
  }
  page.gap(12);
}

function drawScoreCard(page, report) {
  const { doc, margin, contentWidth, wrap } = page;
  const score = report.score;
  const color = bandColor(score);
  const scoreLabel = score == null || score === '' ? '' : String(score);
  const risk = pdfSafe(report.risk_level || '');
  const disclaimer = disclaimerText(report);

  const pad = 14;
  const innerW = contentWidth - pad * 2 - 8;
  const riskColW = 240;
  const riskLines = risk ? wrap(risk, riskColW, 13, 'bold') : [];
  const disclaimerLines = wrap(disclaimer, innerW, 9, 'bold');
  const scoreSize = 42;
  const topBlock = Math.max(scoreSize, riskLines.length * 16);
  const disclaimerH = disclaimerLines.length * 13;
  const boxH = pad + topBlock + 10 + disclaimerH + pad;

  page.ensure(boxH + 4);
  const top = page.y;

  doc.setFillColor(...CARD);
  doc.setDrawColor(...INK);
  doc.setLineWidth(1.25);
  doc.roundedRect(margin, top, contentWidth, boxH, 5, 5, 'FD');
  doc.setFillColor(...color);
  doc.rect(margin + 1.5, top + 12, 4, boxH - 24, 'F');

  const textX = margin + pad + 6;
  if (scoreLabel) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(scoreSize);
    doc.setTextColor(...color);
    doc.text(scoreLabel, textX, top + pad - 2, { baseline: 'top' });
    const scoreWidth = doc.getTextWidth(scoreLabel);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(13);
    doc.setTextColor(...MUTED);
    doc.text('/100', textX + scoreWidth + 6, top + pad + 24, { baseline: 'top' });
  }

  if (riskLines.length) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(13);
    doc.setTextColor(...color);
    const riskHeight = riskLines.length * 16;
    let riskY = top + pad + Math.max(0, (scoreSize - riskHeight) / 2);
    riskLines.forEach((line) => {
      doc.text(line, margin + contentWidth - pad, riskY, { align: 'right', baseline: 'top' });
      riskY += 16;
    });
  }

  const ruleY = top + pad + topBlock + 6;
  doc.setDrawColor(...RULE);
  doc.setLineWidth(0.7);
  doc.line(textX, ruleY, margin + contentWidth - pad, ruleY);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(...INK);
  disclaimerLines.forEach((line, index) => {
    doc.text(line, textX, ruleY + 8 + index * 13, { baseline: 'top' });
  });

  page.y = top + boxH + 14;
}

function drawEquation(page, report) {
  const { doc, margin, pageWidth, contentWidth } = page;
  const items = Array.isArray(report.equation) ? report.equation : [];
  const chips = items.length
    ? items.map((item) => `${pdfSafe(item?.label || 'Indicator')} +${item?.points ?? 0}`)
    : ['No indicators triggered'];
  const total = report.score == null || report.score === '' ? '=' : `= ${report.score}`;

  page.writeWrapped('Score equation', {
    size: 11,
    style: 'bold',
    color: INK,
    width: contentWidth,
    lineGap: 3,
  });
  page.gap(8);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  const chipH = 18;
  const gap = 6;
  let x = margin;

  const parts = [
    ...chips.map((text) => ({ text, kind: 'chip' })),
    { text: total, kind: 'total' },
  ];

  parts.forEach((part) => {
    const label = part.kind === 'total' ? part.text : pdfSafe(part.text);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(part.kind === 'total' ? 12 : 9);
    const textW = doc.getTextWidth(label);
    const width = part.kind === 'total' ? textW + 2 : textW + 16;

    if (width > contentWidth) {
      if (x > margin) {
        x = margin;
        page.y += chipH + gap;
      }
      const lines = page.wrap(label, contentWidth - 16, 9, 'bold');
      const blockH = 10 + lines.length * 12;
      page.ensure(blockH);
      const top = page.y;
      doc.setFillColor(...CHIP);
      doc.setDrawColor(...INK);
      doc.setLineWidth(0.9);
      doc.roundedRect(margin, top, contentWidth, blockH, 4, 4, 'FD');
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      doc.setTextColor(...INK);
      lines.forEach((line, index) => {
        doc.text(line, margin + 8, top + 5 + index * 12, { baseline: 'top' });
      });
      page.y = top + blockH + gap;
      x = margin;
      return;
    }

    if (x > margin && x + width > pageWidth - margin) {
      x = margin;
      page.y += chipH + gap;
    }
    if (x === margin) page.ensure(chipH);
    const top = page.y;

    if (part.kind === 'chip') {
      doc.setFillColor(...CHIP);
      doc.setDrawColor(...INK);
      doc.setLineWidth(0.9);
      doc.roundedRect(x, top, width, chipH, 9, 9, 'FD');
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      doc.setTextColor(...INK);
      doc.text(label, x + 8, top + 4.5, { baseline: 'top' });
    } else {
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(12);
      doc.setTextColor(...INK);
      doc.text(label, x, top + 2, { baseline: 'top' });
    }
    x += width + gap;
  });

  page.y += chipH + 14;
}

function drawEvidenceItem(page, item, statusLabel) {
  const { doc, margin, contentWidth } = page;
  const title = pdfSafe(item?.title || 'Untitled check');
  const points = Number(item?.points) > 0 ? `+${item.points}` : '';
  const trailing = [points, statusLabel].filter(Boolean).join('   ');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  const trailingW = trailing ? doc.getTextWidth(trailing) + 12 : 0;
  const titleWidth = Math.max(120, contentWidth - trailingW);
  const titleLines = page.wrap(title, titleWidth, 11, 'bold');
  const reason = pdfSafe(item?.reason || '');
  const excerpt = pdfSafe(item?.excerpt || '').trim();
  const sourceBits = [];
  if (item?.source) sourceBits.push(`Source: ${pdfSafe(item.source)}`);
  if (item?.source_url) sourceBits.push(pdfSafe(item.source_url));
  const also = Array.isArray(item?.also_found_in) && item.also_found_in.length
    ? `Also found in: ${item.also_found_in.map((entry) => pdfSafe(entry)).filter(Boolean).join(', ')}`
    : '';

  const blockEstimate = 16 + titleLines.length * 15 + (reason ? 28 : 0) + (excerpt ? 28 : 0);
  page.ensure(Math.min(blockEstimate, 72));

  const titleTop = page.y;
  titleLines.forEach((line, index) => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(...INK);
    doc.text(line, margin, titleTop + index * 15, { baseline: 'top' });
  });
  if (trailing) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    doc.setTextColor(...MUTED);
    doc.text(trailing, margin + contentWidth, titleTop + 1, { align: 'right', baseline: 'top' });
  }
  page.y = titleTop + titleLines.length * 15 + 3;

  if (reason) {
    page.writeWrapped(reason, {
      size: 10,
      style: 'normal',
      color: INK,
      width: contentWidth,
      lineGap: 3,
    });
  }
  if (excerpt) {
    page.gap(3);
    page.writeWrapped(`"${excerpt}"`, {
      size: 10,
      style: 'italic',
      color: MUTED,
      width: contentWidth - 8,
      indent: 8,
      lineGap: 3,
      font: 'times',
    });
  }
  if (sourceBits.length) {
    page.gap(3);
    page.writeWrapped(sourceBits.join('  |  '), {
      size: 8,
      style: 'normal',
      color: MUTED,
      width: contentWidth,
      lineGap: 2,
    });
  }
  if (also) {
    page.gap(1);
    page.writeWrapped(also, {
      size: 8,
      style: 'italic',
      color: MUTED,
      width: contentWidth,
      lineGap: 2,
    });
  }
  page.gap(6);
}

function drawEvidence(page, report) {
  const evidence = Array.isArray(report.evidence) ? report.evidence : [];
  const present = GROUPS
    .map((group) => ({
      ...group,
      items: evidence.filter((item) => item?.status === group.status),
    }))
    .filter((group) => group.items.length > 0);

  if (!present.length) return;

  page.writeWrapped('Evidence', {
    size: 13,
    style: 'bold',
    color: INK,
    width: page.contentWidth,
    lineGap: 3,
  });
  page.gap(2);
  page.hrule(0.8, RULE, 0, 8);

  present.forEach((group) => {
    page.ensure(36);
    page.writeWrapped(group.heading, {
      size: 11,
      style: 'bold',
      color: INK,
      width: page.contentWidth,
      lineGap: 3,
    });
    page.gap(6);
    group.items.forEach((item) => drawEvidenceItem(page, item, group.label));
  });
}

function drawListSection(page, title, entries) {
  if (!entries.length) return;
  page.ensure(40);
  page.writeWrapped(title, {
    size: 13,
    style: 'bold',
    color: INK,
    width: page.contentWidth,
    lineGap: 3,
  });
  page.gap(2);
  page.hrule(0.8, RULE, 0, 8);
  entries.forEach((entry, index) => {
    page.writeWrapped(`${index + 1}.  ${entry}`, {
      size: 10,
      style: 'normal',
      color: INK,
      width: page.contentWidth,
      lineGap: 3,
    });
    page.gap(3);
  });
  page.gap(6);
}

function drawNarrative(page, report) {
  const narrative = typeof report.narrative === 'string' ? report.narrative.trim() : '';
  if (!narrative) return;
  page.ensure(40);
  page.writeWrapped('Narrative', {
    size: 13,
    style: 'bold',
    color: INK,
    width: page.contentWidth,
    lineGap: 3,
  });
  page.gap(4);
  page.hrule(0.8, RULE, 0, 10);
  page.writeWrapped(narrative, {
    size: 10,
    style: 'normal',
    color: INK,
    width: page.contentWidth,
    lineGap: 4,
  });
}

function drawFooters(page, report) {
  const { doc, margin, pageWidth, footerTop } = page;
  const total = doc.getNumberOfPages();
  const idLabel = report?.id == null ? 'Investigation report' : `Report ${report.id}`;
  for (let index = 1; index <= total; index += 1) {
    doc.setPage(index);
    doc.setDrawColor(...RULE);
    doc.setLineWidth(0.6);
    doc.line(margin, footerTop, pageWidth - margin, footerTop);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(...MUTED);
    doc.text(`TrustIntern   ·   ${idLabel}`, margin, footerTop + 14, { baseline: 'top' });
    doc.text(`${index} / ${total}`, pageWidth - margin, footerTop + 14, {
      align: 'right',
      baseline: 'top',
    });
  }
}

export function buildReportPdf(report, companyFallback = '') {
  const doc = new jsPDF({ unit: 'pt', format: 'letter', compress: false });
  const company = companyNameOf(report, companyFallback);
  const disclaimer = disclaimerText(report);
  doc.setProperties({
    title: pdfSafe(`TrustIntern - ${company}`),
    subject: disclaimer,
    creator: 'TrustIntern',
  });

  const page = createPainter(doc);
  page.paintPaper();
  drawLetterhead(page, report, company);
  drawScoreCard(page, report);
  drawEquation(page, report);
  drawEvidence(page, report || {});
  const recommendations = Array.isArray(report?.recommendations)
    ? report.recommendations.map((entry) => pdfSafe(entry)).filter((entry) => entry.trim())
    : [];
  drawListSection(page, 'Recommendations', recommendations);
  drawNarrative(page, report || {});
  drawFooters(page, report || {});
  return doc;
}

export function buildReportPdfBytes(report, companyFallback = '') {
  return new Uint8Array(buildReportPdf(report, companyFallback).output('arraybuffer'));
}

export function downloadReportPdf(report, companyFallback = '') {
  if (!report || typeof document === 'undefined') return;
  const filename = reportPdfFilename(report, companyFallback);
  const bytes = buildReportPdfBytes(report, companyFallback);
  const blob = new Blob([bytes], { type: 'application/pdf' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
