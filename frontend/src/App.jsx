import React, { useState, useEffect, useRef } from 'react';
import {
  fetchHealth,
  fetchSamples,
  submitInvestigation,
  startAgentRun,
  fetchInvestigations,
  fetchInvestigationById,
  ApiError,
} from './api';
import { downloadReportPdf } from './reportPdf';

const STATIC_DISCLAIMER = 'Heuristic indicator score, not a probability of fraud.';

export default function App() {
  // Form state
  const [companyName, setCompanyName] = useState('');
  const [recruiterName, setRecruiterName] = useState('');
  const [recruiterEmail, setRecruiterEmail] = useState('');
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [message, setMessage] = useState('');
  const [liveLookups, setLiveLookups] = useState(true);
  const [pdfFile, setPdfFile] = useState(null);
  const [imageFile, setImageFile] = useState(null);
  const [gemmaStatus, setGemmaStatus] = useState(null);

  // Validation errors from 422: { field_name: errorMessage }
  const [fieldErrors, setFieldErrors] = useState({});

  // General error banner (e.g. Network error)
  const [globalError, setGlobalError] = useState(null);

  // In-flight state
  const [isLoading, setIsLoading] = useState(false);

  // Current active report
  const [report, setReport] = useState(null);

  // Fictional sample banner
  const [isSampleLoaded, setIsSampleLoaded] = useState(false);

  // Samples cache from GET /api/samples
  const [samplesCache, setSamplesCache] = useState(null);

  // History list from GET /api/investigations
  const [historyList, setHistoryList] = useState([]);

  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);

  // Load history on mount
  useEffect(() => {
    loadHistory();
    fetchHealth()
      .then(setGemmaStatus)
      .catch(() => setGemmaStatus(null));
  }, []);

  // Helper to compute unique key for an investigation
  function getInvestigationKey(item) {
    const s = item.input_summary || {};
    const company = (s.company_name || item.company_name || '').trim().toLowerCase();
    const message = (s.message_preview || item.message || '').trim().toLowerCase();
    return `${company}:::${message}`;
  }

  // Deduplicate investigations keeping only the newest unique entries
  function deduplicateInvestigations(items) {
    if (!Array.isArray(items)) return [];
    const seen = new Set();
    const unique = [];
    for (const item of items) {
      const key = getInvestigationKey(item);
      if (key && !seen.has(key)) {
        seen.add(key);
        unique.push(item);
      }
    }
    return unique;
  }

  async function loadHistory() {
    try {
      const items = await fetchInvestigations();
      if (Array.isArray(items)) {
        setHistoryList(deduplicateInvestigations(items));
      }
    } catch (err) {
      if (err.isNetworkError) {
        setGlobalError('API is not running. Start the backend on port 8000.');
      }
    }
  }

  // Score band class helper
  function getScoreBandClass(score) {
    if (score >= 61) return 'band-high';
    if (score >= 31) return 'band-mid';
    return 'band-low';
  }

  // Handle clicking sample buttons
  async function handleSampleClick(sampleKey) {
    setGlobalError(null);
    setFieldErrors({});
    setIsLoading(true);

    try {
      let samples = samplesCache;
      if (!samples) {
        samples = await fetchSamples();
        setSamplesCache(samples);
      }

      const sample = samples.find((s) => s.id === sampleKey);
      if (!sample) {
        throw new Error(`Sample ${sampleKey} not found`);
      }

      // Populate form fields
      setCompanyName(sample.company_name || '');
      setRecruiterName(sample.recruiter_name || '');
      setRecruiterEmail(sample.recruiter_email || '');
      setWebsiteUrl(sample.website_url || '');
      setMessage(sample.message || '');
      setLiveLookups(false); // lookups off for samples
      setPdfFile(null);
      setImageFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      if (imageInputRef.current) {
        imageInputRef.current.value = '';
      }

      setIsSampleLoaded(true);

      // Check if an investigation for this sample already exists in history
      const sampleKeyStr = `${(sample.company_name || '').trim().toLowerCase()}:::${(sample.message || '').slice(0, 180).trim().toLowerCase()}`;
      const existing = historyList.find((h) => getInvestigationKey(h) === sampleKeyStr);

      if (existing) {
        // Only log unique investigations: reuse existing report without duplicate log
        setReport(existing);
      } else {
        // POST to /api/investigations with live_lookups=false
        const payload = {
          company_name: sample.company_name,
          recruiter_name: sample.recruiter_name || '',
          recruiter_email: sample.recruiter_email || '',
          website_url: sample.website_url || '',
          message: sample.message,
          live_lookups: false,
        };

        const result = await submitInvestigation(payload);
        setReport(result);
        await loadHistory();
      }
    } catch (err) {
      if (err.isNetworkError) {
        setGlobalError('API is not running. Start the backend on port 8000.');
      } else if (err instanceof ApiError && err.status === 422) {
        setFieldErrors(err.fields || {});
      } else {
        setGlobalError(err.message || 'An error occurred while loading the sample.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  // Handle manual form submit
  async function handleInvestigate(e) {
    if (e) e.preventDefault();
    setGlobalError(null);
    setFieldErrors({});
    setIsLoading(true);

    try {
      // Check if exact investigation already exists and lookups are off
      const currentKey = `${companyName.trim().toLowerCase()}:::${message.slice(0, 180).trim().toLowerCase()}`;
      const existing = historyList.find((h) => {
        const s = h.input_summary || {};
        return (
          getInvestigationKey(h) === currentKey &&
          s.live_lookups === liveLookups &&
          !pdfFile &&
          !imageFile
        );
      });

      if (existing && !liveLookups) {
        setReport(existing);
        setIsSampleLoaded(false);
        setIsLoading(false);
        return;
      }

      const formData = new FormData();
      formData.append('company_name', companyName);
      formData.append('message', message);
      if (recruiterName) formData.append('recruiter_name', recruiterName);
      if (recruiterEmail) formData.append('recruiter_email', recruiterEmail);
      if (websiteUrl) formData.append('website_url', websiteUrl);
      formData.append('live_lookups', liveLookups ? 'true' : 'false');
      if (pdfFile) {
        formData.append('pdf', pdfFile);
      }
      if (imageFile) {
        formData.append('image', imageFile);
      }

      const useVisionRun = Boolean(pdfFile || imageFile);
      const result = useVisionRun
        ? await startAgentRun(formData)
        : await submitInvestigation(formData);
      setReport(result);
      setIsSampleLoaded(false); // Manual run completed
      await loadHistory();
    } catch (err) {
      if (err.isNetworkError) {
        setGlobalError('API is not running. Start the backend on port 8000.');
      } else if (err instanceof ApiError && err.status === 422) {
        setFieldErrors(err.fields || {});
      } else {
        setGlobalError(err.message || 'An unexpected error occurred.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  // Handle history item click
  async function handleReopenHistory(id) {
    setGlobalError(null);
    setIsLoading(true);
    try {
      const investigation = await fetchInvestigationById(id);
      setReport(investigation);
      setIsSampleLoaded(false);

      if (investigation.input_summary) {
        setCompanyName(investigation.input_summary.company_name || '');
        setRecruiterName(investigation.input_summary.recruiter_name || '');
        setRecruiterEmail(investigation.input_summary.recruiter_email || '');
        setWebsiteUrl(investigation.input_summary.website_url || '');
        if (!message) {
          setMessage(investigation.input_summary.message_preview || '');
        }
        setLiveLookups(investigation.input_summary.live_lookups ?? true);
      }
    } catch (err) {
      if (err.isNetworkError) {
        setGlobalError('API is not running. Start the backend on port 8000.');
      } else {
        setGlobalError(err.message || 'Failed to reopen investigation.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  function handleDownloadReport() {
    if (!report) return;
    downloadReportPdf(report, companyName);
  }

  // Format timestamp for history list
  function formatTime(isoString) {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (_) {
      return isoString;
    }
  }

  const activeDisclaimer = report?.disclaimer || STATIC_DISCLAIMER;

  // Split evidence into groups
  const indicatorEvidence = (report?.evidence || []).filter((e) => e.status === 'indicator');
  const clearEvidence = (report?.evidence || []).filter((e) => e.status === 'clear');
  const unknownEvidence = (report?.evidence || []).filter((e) => e.status === 'unknown');

  return (
    <div className="desk-container">
      {/* Top of the page, always visible */}
      <header className="top-bar">
        <div className="header-row">
          <h1 className="app-title">TrustIntern</h1>
          <div className="disclaimer-banner">{activeDisclaimer}</div>
          {gemmaStatus && (
            <div className="disclaimer-banner">
              {gemmaStatus.gemma_configured
                ? `Open-weight ${gemmaStatus.model} is running locally in Ollama. Screenshots and PDF pages go to Gemma vision; scoring stays in scoring.py.`
                : `Local Gemma is not reachable. Start Ollama and run: ollama pull ${gemmaStatus.model || 'gemma4:e2b'}. Until then, vision stays on phrase rules.`}
            </div>
          )}
        </div>

        <div className="samples-row">
          <span className="sample-label">Fictional samples:</span>
          <button
            type="button"
            className="btn-sample"
            onClick={() => handleSampleClick('suspicious')}
            disabled={isLoading}
          >
            Suspicious offer
          </button>
          <button
            type="button"
            className="btn-sample"
            onClick={() => handleSampleClick('consistent')}
            disabled={isLoading}
          >
            Consistent offer
          </button>
          <button
            type="button"
            className="btn-sample"
            onClick={() => handleSampleClick('limited')}
            disabled={isLoading}
          >
            Limited evidence
          </button>
        </div>

        {isSampleLoaded && (
          <div className="sample-active-note">
            Fictional sample. Live website and domain-age lookups are off so the score stays stable.
          </div>
        )}
      </header>

      {/* Global Error Banner (API Down, Network, etc.) */}
      {globalError && <div className="error-bar">{globalError}</div>}

      <div className="main-grid">
        {/* Left Column: Form (380px) */}
        <section className="form-panel">
          <form onSubmit={handleInvestigate}>
            {/* Company */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="company">
                  Company
                </label>
                {fieldErrors.company_name && (
                  <span className="field-error">{fieldErrors.company_name}</span>
                )}
              </div>
              <input
                id="company"
                type="text"
                className={`form-input ${fieldErrors.company_name ? 'has-error' : ''}`}
                value={companyName}
                onChange={(e) => {
                  setCompanyName(e.target.value);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* Recruiter */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="recruiter">
                  Recruiter
                </label>
                {fieldErrors.recruiter_name && (
                  <span className="field-error">{fieldErrors.recruiter_name}</span>
                )}
              </div>
              <input
                id="recruiter"
                type="text"
                className={`form-input ${fieldErrors.recruiter_name ? 'has-error' : ''}`}
                value={recruiterName}
                onChange={(e) => {
                  setRecruiterName(e.target.value);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* Recruiter email */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="recruiter_email">
                  Recruiter email
                </label>
                {fieldErrors.recruiter_email && (
                  <span className="field-error">{fieldErrors.recruiter_email}</span>
                )}
              </div>
              <input
                id="recruiter_email"
                type="text"
                className={`form-input ${fieldErrors.recruiter_email ? 'has-error' : ''}`}
                value={recruiterEmail}
                onChange={(e) => {
                  setRecruiterEmail(e.target.value);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* Website */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="website">
                  Website
                </label>
                {fieldErrors.website_url && (
                  <span className="field-error">{fieldErrors.website_url}</span>
                )}
              </div>
              <input
                id="website"
                type="text"
                className={`form-input ${fieldErrors.website_url ? 'has-error' : ''}`}
                value={websiteUrl}
                onChange={(e) => {
                  setWebsiteUrl(e.target.value);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* Recruitment message */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="message">
                  Recruitment message
                </label>
                {fieldErrors.message && (
                  <span className="field-error">{fieldErrors.message}</span>
                )}
              </div>
              <textarea
                id="message"
                className={`form-textarea ${fieldErrors.message ? 'has-error' : ''}`}
                rows={5}
                value={message}
                onChange={(e) => {
                  setMessage(e.target.value);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* Offer letter PDF */}
            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="pdf">
                  Offer letter PDF
                </label>
                {fieldErrors.pdf && <span className="field-error">{fieldErrors.pdf}</span>}
              </div>
              <input
                id="pdf"
                type="file"
                accept=".pdf,application/pdf"
                ref={fileInputRef}
                className="file-input"
                onChange={(e) => {
                  setPdfFile(e.target.files?.[0] || null);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <div className="form-label-row">
                <label className="form-label" htmlFor="offer-image">
                  Offer screenshot
                </label>
                {fieldErrors.image && <span className="field-error">{fieldErrors.image}</span>}
              </div>
              <input
                id="offer-image"
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                ref={imageInputRef}
                className="file-input"
                onChange={(e) => {
                  setImageFile(e.target.files?.[0] || null);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
            </div>

            {/* checkbox Run live website and domain-age lookups */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={liveLookups}
                onChange={(e) => {
                  setLiveLookups(e.target.checked);
                  setIsSampleLoaded(false);
                }}
                disabled={isLoading}
              />
              <span>Run live website and domain-age lookups</span>
            </label>

            {/* Primary button Investigate */}
            <button
              type="submit"
              className="btn-primary"
              disabled={isLoading}
            >
              {isLoading ? 'Checking the offer...' : 'Investigate'}
            </button>
          </form>

          {/* History list */}
          <div className="history-section">
            <h3 className="history-heading">Investigation History</h3>
            {historyList.length === 0 ? (
              <div style={{ fontSize: '13px', color: 'var(--ink-muted)' }}>
                No past investigations yet.
              </div>
            ) : (
              <ul className="history-list">
                {historyList.map((item) => (
                  <li
                    key={item.id}
                    className="history-item"
                    onClick={() => handleReopenHistory(item.id)}
                    title={`Click to reopen report #${item.id}`}
                  >
                    <span className="history-company">
                      {item.input_summary?.company_name || 'Investigation'}
                    </span>
                    <span className={`history-score ${getScoreBandClass(item.score)}`}>
                      {item.score}/100
                    </span>
                    <span className="history-time">{formatTime(item.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Right Column: Report fluid */}
        <section className="report-panel">
          {isLoading && (
            <div className="in-flight-banner">Checking the offer...</div>
          )}

          {!isLoading && !report && (
            <div className="report-empty">
              Submit an offer or load a fictional sample.
            </div>
          )}

          {report && (
            <>
              {/* Sticky Score Block */}
              <div className="score-block">
                <div className="score-main-row">
                  <div className={`score-number ${getScoreBandClass(report.score)}`}>
                    {report.score}/100
                  </div>
                  <div className={`risk-level-badge ${getScoreBandClass(report.score)}`}>
                    {report.risk_level}
                  </div>
                </div>
                {report.planner_mode && (
                  <div className="equation-row">
                    {report.planner_mode === 'gemma'
                      ? `Vision planner: open-weight ${report.model || 'Gemma 4'} (local Ollama)`
                      : 'Vision planner: heuristic fallback (no live Gemma call)'}
                  </div>
                )}

                {/* Equation: one chip per equation item, {label} +{points}, then = {score} */}
                <div className="equation-row">
                  {report.equation && report.equation.length > 0 && (
                    report.equation.map((item, idx) => (
                      <span key={idx} className="equation-chip">
                        {item.label} +{item.points}
                      </span>
                    ))
                  )}
                  <span className="equation-equals">= {report.score}</span>
                </div>
              </div>

              {/* Group Evidence by Status */}
              <div className="evidence-section">
                {/* indicator heading Raised the score */}
                {indicatorEvidence.length > 0 && (
                  <div>
                    <h3 className="evidence-group-title group-indicator">Raised the score</h3>
                    {indicatorEvidence.map((item, idx) => (
                      <EvidenceCard key={`ind-${idx}`} item={item} />
                    ))}
                  </div>
                )}

                {/* clear heading Checked and did not raise the score */}
                {clearEvidence.length > 0 && (
                  <div>
                    <h3 className="evidence-group-title group-clear">
                      Checked and did not raise the score
                    </h3>
                    {clearEvidence.map((item, idx) => (
                      <EvidenceCard key={`clr-${idx}`} item={item} />
                    ))}
                  </div>
                )}

                {/* unknown heading Not checked */}
                {unknownEvidence.length > 0 && (
                  <div>
                    <h3 className="evidence-group-title group-unknown">Not checked</h3>
                    {unknownEvidence.map((item, idx) => (
                      <EvidenceCard key={`unk-${idx}`} item={item} />
                    ))}
                  </div>
                )}
              </div>

              {/* Recommendations as a short list */}
              {report.recommendations && report.recommendations.length > 0 && (
                <div className="recommendations-box">
                  <h4 className="recommendations-title">Recommendations</h4>
                  <ul className="recommendations-list">
                    {report.recommendations.map((rec, idx) => (
                      <li key={idx}>{rec}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Button Download report */}
              <div className="report-actions">
                <button
                  type="button"
                  className="btn-download"
                  onClick={handleDownloadReport}
                >
                  Download PDF
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

// Subcomponent for each Evidence Card
function EvidenceCard({ item }) {
  const statusLabels = {
    indicator: 'Indicator',
    clear: 'Clear',
    unknown: 'Not checked',
  };

  const statusLabel = statusLabels[item.status] || item.status;

  return (
    <article className="evidence-card">
      <div className="evidence-card-header">
        <h4 className="evidence-title">{item.title}</h4>
        <div className="evidence-header-right">
          {item.points > 0 && (
            <span className="evidence-points">+{item.points}</span>
          )}
          {/* Print the status word on the card. Do not rely on color alone. */}
          <span className={`evidence-status-pill status-${item.status}`}>
            {statusLabel}
          </span>
        </div>
      </div>

      <p className="evidence-reason">{item.reason}</p>

      {/* excerpt in quotation marks when non-empty */}
      {item.excerpt && item.excerpt.trim() !== '' && (
        <blockquote className="evidence-excerpt">
          &ldquo;{item.excerpt}&rdquo;
        </blockquote>
      )}

      <div className="evidence-footer">
        <span className="evidence-source">Source: {item.source}</span>
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="evidence-link"
          >
            {item.source_url}
          </a>
        )}
      </div>

      {/* If also_found_in is non-empty, add Also found in: ... */}
      {item.also_found_in && item.also_found_in.length > 0 && (
        <div className="evidence-also">
          Also found in: {item.also_found_in.join(', ')}
        </div>
      )}
    </article>
  );
}
