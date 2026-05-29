#!/usr/bin/env node
/** Run buildFullPdfReportData in Node for CI parity validation (no browser). */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const samplePath = process.argv[2] || path.join(root, 'exports', 'pdf_parity_sample.json');
const outPath = process.argv[3] || path.join(root, 'exports', 'pdf_parity_report.json');

global.window = global;
global.resolveCheckValue = (checkId, result) => {
    const cv = result?.audit_reliability?.check_values;
    if (cv && Object.prototype.hasOwnProperty.call(cv, checkId)) return cv[checkId];
    return undefined;
};
global.resolveAuditEvidence = (checkId, result) =>
    result?.audit_reliability?.audit_evidence?.[checkId] || null;
global.resolveTitleTagBlock = (result) => {
    const seo = result?.seo_report || {};
    const base = seo.title_tag || {};
    const value = base.value || result?.dom_technical_seo?.title_tag || 'Sample Product Title';
    return { ...base, value, length: value.length };
};
global.getCompetitorIntelligence = (comp, mode1Result) => {
    const reliability = mode1Result?.audit_reliability || {};
    const extConf = Number(reliability.extraction_confidence || 0);
    const extPct = reliability.extraction_confidence_pct ?? Math.round(extConf * 100);
    const competitorSites = ((comp?.live_compare?.sites || []).filter((s) => s.role === 'competitor' && s.scrape_ok)).length;
    const showLiveCompare = extConf >= 0.45 && competitorSites > 0;
    const hasBenchmark = Boolean(comp?.benchmark_scores?.avg_seo_score != null);
    return {
        weak: false,
        quality: 'good',
        reason: `${competitorSites} competitor page(s) scraped live`,
        extConf,
        extPct,
        confidenceOk: extConf >= 0.45,
        showLiveCompare,
        showBenchmark: hasBenchmark,
        unavailable: !showLiveCompare && !hasBenchmark,
        unavailableReason: null,
        competitorSites,
    };
};
global.getValidatedAutofixFix = () => null;

require(path.join(root, 'frontend', 'pdf_parity.js'));

if (!fs.existsSync(samplePath)) {
    console.error(`Sample not found: ${samplePath}`);
    process.exit(1);
}

const sample = JSON.parse(fs.readFileSync(samplePath, 'utf8'));
const glossary = sample._glossary || {};
const data = global.buildFullPdfReportData(sample, glossary);

const report = {
    summary: {
        uiFieldCount: data.parity.uiFieldCount,
        pdfFieldCount: data.parity.pdfFieldCount,
        coveragePct: data.parity.coveragePct,
        valueMatches: data.parity.valueMatches,
        valueMatchPct: data.parity.valueMatchPct,
        targetMet: data.parity.targetMet,
        targetCoverage: 90,
    },
    byTab: data.parity.byTab,
    valueMismatches: data.parity.valueMismatches,
    missingInPdf: data.parity.missingInPdf,
    checkCounts: {
        SEO: data.tabs.SEO.checks.length,
        AEO: data.tabs.AEO.checks.length,
        UX: data.tabs.UX.checks.length,
        PSYCHOLOGY: data.tabs.PSYCHOLOGY.checks.length,
    },
    generatedAt: data.parity.generatedAt,
};

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report.summary, null, 2));
process.exit(report.summary.targetMet ? 0 : 1);
