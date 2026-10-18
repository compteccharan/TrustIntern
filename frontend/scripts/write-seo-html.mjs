/**
 * Writes crawlable HTML for the Vite frontend.
 * Source of truth for the landing copy, About, FAQ, and FAQPage JSON-LD
 * so the structured data matches the visible answers.
 */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const SITE = 'https://trustintern.charancodes.com';
const TITLE = 'TrustIntern – Free Internship Offer Scam Checker for Students';
const DISCLAIMER = 'Heuristic indicator score, not a probability of fraud.';
const DEV_POST =
  'https://dev.to/noahosmont/trustintern-i-built-a-scam-detective-for-internship-offers-in-55-hours-and-my-agents-kept-1446';
const CONTRACT =
  'https://github.com/compteccharan/TrustIntern/blob/main/backend/CONTRACT.md';
const LICENSE =
  'https://github.com/compteccharan/TrustIntern/blob/main/LICENSE';
const REPO = 'https://github.com/compteccharan/TrustIntern';

const HOME_DESC =
  'Heuristic indicator score, not a probability of fraud. Free beta for students in India checking internship offers (UPI fees, WhatsApp recruiters, Aadhaar or OTP). Job offers can be checked too. Paid college tiers are planned.';
const ABOUT_DESC =
  'How TrustIntern scores an internship offer for students in India. Heuristic indicator score, not a probability of fraud. Built for DEV Hacktoberfest Week 2 in 5.5 hours, open source under MIT. A teammate built the front end.';
const FAQ_DESC =
  'FAQ for students in India checking internship offers. Heuristic indicator score, not a probability of fraud. Covers UPI fees, WhatsApp recruiters, Aadhaar or OTP requests, and fictional composite examples.';

const STEPS = [
  'Fixed checkers look at the email domain, domain age (RDAP), website and message text.',
  'Gemma 4 plans which research agents to launch: company, recruiter, complaints, domain, document, follow-up. Only allowlisted agent types run; at most 8 agents and depth 2.',
  'Gemma 4 vision reads the offer letter (PDF or screenshot) and flags inconsistencies.',
  'Deterministic scoring (backend/app/scoring.py) adds up fixed indicator points: upfront fee 25, domain mismatch 20, sensitive data 20, young domain 15, offer conflict 15, unrelated domain 10, urgency 10, personal email 5. The total is capped at 100 and never reduced. Gemma never assigns points.',
  'Progress streams to the React desk over SSE; Gemma then writes a plain-language summary of the evidence.',
];

const INDICATORS = [
  ['Upfront fee', '25'],
  ['Email domain mismatch', '20'],
  ['Sensitive data request', '20'],
  ['Newly registered domain', '15'],
  ['Offer letter conflict', '15'],
  ['Company not in domain', '10'],
  ['Urgency or guarantee', '10'],
  ['Personal email provider', '5'],
];

const FAQS = [
  {
    q: 'What is TrustIntern?',
    a: 'TrustIntern is an investigation desk for students in India. It looks at the company name, recruiter email, website, message text, and an offer-letter PDF or screenshot. Internship offers come first, including placement-season messages, UPI registration fees, WhatsApp recruiters, and requests for Aadhaar or an OTP. Job offers can be checked with the same desk.',
  },
  {
    q: 'Is TrustIntern free?',
    a: 'The public site is a free beta for students. Paid tiers for colleges and placement cells are planned. It is not a promise that the checker is free for everyone.',
  },
  {
    q: 'What does the score mean?',
    a: 'Heuristic indicator score, not a probability of fraud. It runs from 0 to 100. Every point is tied to a piece of evidence, and anyone can recompute it by hand from backend/CONTRACT.md. The score does not call any company a scammer.',
  },
  {
    q: 'Who assigns the points?',
    a: 'Fixed rules assign the points. Gemma plans which research agents to launch, reads the offer letter or screenshot, and writes the plain-language summary. Gemma never scores.',
  },
  {
    q: 'Should I pay a UPI registration fee for an internship?',
    a: 'An upfront fee is the heaviest indicator, worth 25 points. A placement-season message that asks for a registration, training, kit, or certificate fee, often over UPI on WhatsApp, raises that indicator. The result is still a heuristic indicator score, not a probability of fraud.',
  },
  {
    q: 'What if a recruiter asks for Aadhaar or an OTP?',
    a: 'A request for Aadhaar, PAN, bank details, or an OTP is the sensitive-data indicator, worth 20 points. Paste the message into the desk and read the evidence next to the points.',
  },
  {
    q: 'Why does a Gmail or WhatsApp recruiter change the score?',
    a: 'A personal email provider such as Gmail is worth 5 points. An email domain that does not match the company is worth 20 points. Internship notes that arrive on WhatsApp are checked as message text. Job-offer messages use the same indicators.',
  },
  {
    q: 'Does an offer letter stay on my device?',
    a: 'The hosted site falls back to the Gemini API, so a PDF or screenshot submitted there is sent to that API for Gemma to read. A local install can run Gemma through Ollama instead. The score does not depend on the model.',
  },
  {
    q: 'Are the example offers real?',
    a: 'No. The built-in examples are fictional composites. The suspicious composite scores 90 when live lookups are off. That number demonstrates the arithmetic. It is not a label on a real company.',
  },
  {
    q: 'How do the points add up?',
    a: 'Upfront fee 25, domain mismatch 20, sensitive data 20, young domain 15, offer conflict 15, unrelated domain 10, urgency 10, and personal email 5. The total is capped at 100 and is never reduced. The rules are written in backend/CONTRACT.md and backend/app/scoring.py.',
  },
];

function esc(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function escAttr(value) {
  return esc(value).replaceAll('"', '&quot;');
}

function faqJsonLd() {
  return JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: FAQS.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: {
          '@type': 'Answer',
          text: item.a,
        },
      })),
    },
    null,
    2,
  );
}

function head({ description, path, jsonLd }) {
  const canonical = path === '/' ? `${SITE}/` : `${SITE}${path}`;
  const ld = jsonLd
    ? `\n    <script type="application/ld+json">\n${jsonLd}\n    </script>`
    : '';
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
${path === '/' ? '    <meta name="google-site-verification" content="hyYnsGp1geOQcFtJvb2O4qtMfsL0EeY9_0JrQfH6YsM" />\n' : ''}    <title>${esc(TITLE)}</title>
    <meta name="description" content="${escAttr(description)}" />
    <link rel="canonical" href="${canonical}" />
    <meta property="og:title" content="${escAttr(TITLE)}" />
    <meta property="og:description" content="${escAttr(description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${canonical}" />
    <meta property="og:site_name" content="TrustIntern" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="${escAttr(TITLE)}" />
    <meta name="twitter:description" content="${escAttr(description)}" />
    <link rel="stylesheet" href="/seo.css" />${ld}
  </head>`;
}

function nav(current) {
  const item = (href, label) => {
    const currentAttr = href === current ? ' aria-current="page"' : '';
    return `<a href="${href}"${currentAttr}>${label}</a>`;
  };
  return `<nav class="seo-nav" aria-label="Pages">
        ${item('/', 'Checker')}
        ${item('/about', 'About')}
        ${item('/faq', 'FAQ')}
      </nav>`;
}

function stepsHtml() {
  return `<ol class="seo-steps">
${STEPS.map((step) => `        <li>${esc(step)}</li>`).join('\n')}
      </ol>`;
}

function faqHtml(heading) {
  return FAQS.map(
    (item) => `        <article class="faq-item">
          <${heading}>${esc(item.q)}</${heading}>
          <p>${esc(item.a)}</p>
        </article>`,
  ).join('\n');
}

function indicatorTable() {
  const rows = INDICATORS.map(
    ([label, points]) =>
      `            <tr><td>${esc(label)}</td><td>${esc(points)}</td></tr>`,
  ).join('\n');
  return `<table>
          <caption>Fixed indicator points. The total is capped at 100 and never reduced.</caption>
          <thead>
            <tr><th scope="col">Indicator</th><th scope="col">Points</th></tr>
          </thead>
          <tbody>
${rows}
          </tbody>
        </table>`;
}

const hostedNote =
  'On the hosted site, Gemma falls back to the Gemini API. A local install can run Gemma through Ollama, and if no model is reachable a heuristic planner finishes the investigation. The score never depends on the model. Gemma plans, reads, and summarizes, but never scores.';

const origin =
  'TrustIntern was built for DEV\'s Hacktoberfest Open-Source AI Challenge Week 2 in 5.5 hours and is open source under the MIT license. A teammate built the front end.';

function homePage() {
  return `${head({ description: HOME_DESC, path: '/', jsonLd: faqJsonLd() })}
  <body>
    <div id="root"></div>
    <main class="seo-static" id="how-trustintern-works">
      <div class="seo-wrap">
      ${nav('/')}
        <p class="seo-kicker">Students in India · free beta</p>
        <h1>Check an internship offer</h1>
        <p class="seo-lead">An investigation desk that shows its working. Paste the company name, recruiter email, website, and message, or attach an offer-letter PDF or screenshot.</p>
        <p>During placement season the note often arrives on WhatsApp: pay a registration fee over UPI, share Aadhaar, and send the OTP. TrustIntern is for that internship check. Job offers can be submitted on the same desk.</p>
        <p>Students can use this live beta without paying. Paid tiers for colleges and placement cells are planned.</p>
        <blockquote class="seo-callout"><p>${esc(DISCLAIMER)}</p></blockquote>
        <p>The score runs from 0 to 100. Every point is tied to a piece of evidence, and anyone can recompute it by hand from <a href="${CONTRACT}">backend/CONTRACT.md</a>. Gemma plans, reads, and summarizes, but never scores.</p>
        <h2>How it works</h2>
        ${stepsHtml()}
        <p>${esc(hostedNote)}</p>
        <h2>Questions students ask</h2>
${faqHtml('h3')}
        <p class="seo-footer">${esc(origin)} <a href="${DEV_POST}">Read the DEV write-up</a>. More detail is on the <a href="/about">About</a> page. The built-in examples are fictional composites.</p>
      </div>
    </main>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
`;
}

function aboutPage() {
  return `${head({ description: ABOUT_DESC, path: '/about' })}
  <body class="seo-page">
    <main class="seo-wrap">
      ${nav('/about')}
      <p class="seo-kicker">About and methodology</p>
      <h1>How TrustIntern scores an offer</h1>
      <p class="seo-lead">For students in India checking an internship offer. Placement-season messages, UPI fees, WhatsApp recruiters, and Aadhaar or OTP requests come first. Job offers can be checked with the same rules.</p>
      <blockquote class="seo-callout"><p>${esc(DISCLAIMER)}</p></blockquote>
      <h2>Who it is for</h2>
      <p>The live site is a free beta for students. Paid tiers for colleges and placement cells are planned. It is not a promise that every check is free for everyone.</p>
      <h2>How it was built</h2>
      <p>${esc(origin)} The write-up is <a href="${DEV_POST}">on DEV</a>. The code is <a href="${REPO}">on GitHub</a> under the <a href="${LICENSE}">MIT license</a>.</p>
      <h2>How it works</h2>
      ${stepsHtml()}
      <p>${esc(hostedNote)}</p>
      <h2>Recompute the score</h2>
      <p>The score runs from 0 to 100. Every point is tied to a piece of evidence. Anyone can recompute it by hand from <a href="${CONTRACT}">backend/CONTRACT.md</a>. Only those fixed weights create points. Gemma never assigns points, and the score does not call any company a scammer.</p>
      ${indicatorTable()}
      <h2>Fictional composites</h2>
      <p>The built-in examples are fictional composites, not real companies or real recruiters. With live lookups off, the suspicious composite scores 90. That locked number is the arithmetic, which the tests check.</p>
      <p class="seo-footer"><a href="/">Open the checker</a> · <a href="/faq">FAQ</a></p>
    </main>
  </body>
</html>
`;
}

function faqPage() {
  return `${head({ description: FAQ_DESC, path: '/faq', jsonLd: faqJsonLd() })}
  <body class="seo-page">
    <main class="seo-wrap">
      ${nav('/faq')}
      <p class="seo-kicker">FAQ</p>
      <h1>Questions about checking an internship offer</h1>
      <p class="seo-lead">Short answers for students in India. Internships come first: placement season, UPI fees, WhatsApp recruiters, and Aadhaar or OTP requests. Job offers use the same desk.</p>
      <blockquote class="seo-callout"><p>${esc(DISCLAIMER)}</p></blockquote>
      <p>The public site is a free beta for students. Paid tiers for colleges and placement cells are planned.</p>
${faqHtml('h2')}
      <p class="seo-footer"><a href="/">Open the checker</a> · <a href="/about">How scoring works</a> · <a href="${CONTRACT}">backend/CONTRACT.md</a></p>
    </main>
  </body>
</html>
`;
}

const robots = `User-agent: *
Allow: /

Sitemap: ${SITE}/sitemap.xml
`;

const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${SITE}/</loc>
  </url>
  <url>
    <loc>${SITE}/about</loc>
  </url>
  <url>
    <loc>${SITE}/faq</loc>
  </url>
</urlset>
`;

const pages = [
  ['index.html', homePage()],
  ['public/about.html', aboutPage()],
  ['public/faq.html', faqPage()],
  ['public/robots.txt', robots],
  ['public/sitemap.xml', sitemap],
];

const banned = [
  'AI detects scams',
  'detects scams',
  'accuracy',
  'never leave',
  'fully local',
  'built solo',
  'by myself',
  '100%',
];

for (const [rel, html] of pages) {
  if (rel.endsWith('.html')) {
    if (!html.includes(`<title>${TITLE}</title>`)) {
      throw new Error(`${rel} is missing the exact title`);
    }
    if (!html.includes(DISCLAIMER)) {
      throw new Error(`${rel} is missing the score disclaimer`);
    }
    const remainder = html
      .split('not a probability of fraud')
      .join('')
      .split('does not call any company a scammer')
      .join('');
    if (remainder.toLowerCase().includes('probability of fraud')) {
      throw new Error(`${rel} uses "probability of fraud" outside the disclaimer`);
    }
    if (remainder.toLowerCase().includes('scammer')) {
      throw new Error(`${rel} calls someone a scammer outside the denial`);
    }
  }
  for (const phrase of banned) {
    if (html.toLowerCase().includes(phrase.toLowerCase())) {
      throw new Error(`${rel} contains banned phrase: ${phrase}`);
    }
  }
  writeFileSync(join(root, rel), html);
}

const faqHtmlText = faqPage();
for (const item of FAQS) {
  if (!faqHtmlText.includes(`<p>${esc(item.a)}</p>`)) {
    throw new Error(`FAQ answer missing from visible HTML: ${item.q}`);
  }
  if (!faqHtmlText.includes(JSON.stringify(item.a))) {
    throw new Error(`FAQ answer missing from JSON-LD: ${item.q}`);
  }
}

console.log('Wrote crawlable HTML, robots.txt, and sitemap.xml');
