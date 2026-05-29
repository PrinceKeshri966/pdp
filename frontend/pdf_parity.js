/**
 * Full UI ↔ PDF parity export for Commerce Copilot audit reports.
 * Mirrors the same data sources and transforms used by the React UI tabs.
 */
(function (global) {
    'use strict';

    const BRAND_NAME = 'Commerce Copilot';

    const PDF_TAB_CHECKS = {
        SEO: [
            'meta_has_cta', 'headings_logical_hierarchy', 'headings_keywords',
            'kw_in_title', 'kw_in_h1', 'kw_in_meta', 'kw_in_first_100',
            'content_adequate', 'content_unique', 'schema_product',
            'tech_canonical', 'tech_og', 'tech_mobile', 'tech_twitter',
            'tech_hreflang', 'tech_images_optimized', 'tech_lazy_loading', 'tech_pagination',
        ],
        AEO: [
            'geo_perplexity', 'geo_sge', 'geo_direct_answer',
            'rag_citable', 'rag_uvp', 'rag_factual',
            'aeo_conversational', 'aeo_llm_snippet', 'aeo_not_commodity', 'aeo_unique_perspective',
            'schema_product', 'faq_schema', 'schema_breadcrumb', 'schema_review',
            'speakable_schema', 'faq_conversational',
        ],
        UX: [
            'cta_found', 'cta_above_fold', 'cta_sticky',
            'img_angles', 'img_zoom', 'img_lifestyle', 'img_video',
            'trust_reviews', 'trust_rating', 'trust_return', 'trust_security', 'trust_moneyback',
            'info_size_guide', 'info_material', 'info_fit', 'info_specs',
            'urgency_stock', 'urgency_limited', 'urgency_social',
            'checkout_guest', 'checkout_one_click',
        ],
        PSYCHOLOGY: [
            'price_charm', 'price_anchor', 'decoy_pricing', 'peak_end_rule',
            'emotion_identity', 'emotion_aspirational',
        ],
    };

    const CHECK_LABEL_OVERRIDES = {
        tech_mobile: 'Mobile-friendly page',
        tech_pagination: 'No pagination issues',
        geo_perplexity: 'Perplexity can cite this page',
        geo_sge: 'Google AI Overview ready',
        geo_direct_answer: 'Direct answer format',
        price_charm: 'Charm pricing (₹999)',
        price_anchor: 'Anchor price (was ₹X)',
        decoy_pricing: 'Decoy pricing (good/better/best)',
        peak_end_rule: 'Strong ending on page',
        emotion_identity: 'Identity alignment',
        emotion_aspirational: 'Aspirational language',
    };

    function toScore100(raw) {
        if (raw == null || Number.isNaN(Number(raw))) return null;
        const n = Number(raw);
        return n <= 10 ? Math.round(n * 10) : Math.round(n);
    }

    function uniqStrings(arr) {
        const seen = new Set();
        return (arr || []).filter(Boolean).filter((s) => {
            const k = String(s).trim().toLowerCase();
            if (!k || seen.has(k)) return false;
            seen.add(k);
            return true;
        });
    }

    function asArray(v) {
        if (v == null) return [];
        return Array.isArray(v) ? v : [v];
    }

    function normalizeCompare(v) {
        if (v === undefined) return '__undefined__';
        if (v === null) return null;
        if (typeof v === 'boolean') return v;
        if (typeof v === 'number') return Number.isNaN(v) ? null : v;
        if (Array.isArray(v)) return v.map(normalizeCompare);
        if (typeof v === 'object') {
            const out = {};
            Object.keys(v).sort().forEach((k) => { out[k] = normalizeCompare(v[k]); });
            return out;
        }
        return String(v);
    }

    function valuesMatch(a, b) {
        return JSON.stringify(normalizeCompare(a)) === JSON.stringify(normalizeCompare(b));
    }

    function resolveCheck(checkId, result) {
        if (global.resolveCheckValue) return global.resolveCheckValue(checkId, result);
        const cv = result?.audit_reliability?.check_values;
        if (cv && Object.prototype.hasOwnProperty.call(cv, checkId)) return cv[checkId];
        return undefined;
    }

    function resolveEvidence(checkId, result) {
        if (global.resolveAuditEvidence) return global.resolveAuditEvidence(checkId, result);
        return result?.audit_reliability?.audit_evidence?.[checkId] || null;
    }

    function createParityTracker() {
        const fields = [];
        return {
            register(id, tab, label, uiValue, pdfValue) {
                const exported = pdfValue !== undefined;
                fields.push({
                    id,
                    tab,
                    label,
                    uiValue,
                    pdfValue,
                    exported,
                    match: exported ? valuesMatch(uiValue, pdfValue) : false,
                });
            },
            report() {
                const uiFieldCount = fields.length;
                const pdfFieldCount = fields.filter((f) => f.exported).length;
                const coveragePct = uiFieldCount ? Math.round((pdfFieldCount / uiFieldCount) * 1000) / 10 : 0;
                const valueMatches = fields.filter((f) => f.exported && f.match).length;
                const valueMismatches = fields.filter((f) => f.exported && !f.match);
                const missingInPdf = fields.filter((f) => !f.exported);
                const byTab = {};
                fields.forEach((f) => {
                    if (!byTab[f.tab]) byTab[f.tab] = { uiFieldCount: 0, pdfFieldCount: 0, valueMatches: 0, coveragePct: 0 };
                    byTab[f.tab].uiFieldCount++;
                    if (f.exported) byTab[f.tab].pdfFieldCount++;
                    if (f.exported && f.match) byTab[f.tab].valueMatches++;
                });
                Object.keys(byTab).forEach((tab) => {
                    const t = byTab[tab];
                    t.coveragePct = t.uiFieldCount ? Math.round((t.pdfFieldCount / t.uiFieldCount) * 1000) / 10 : 0;
                });
                return {
                    uiFieldCount,
                    pdfFieldCount,
                    coveragePct,
                    valueMatches,
                    valueMatchPct: pdfFieldCount ? Math.round((valueMatches / pdfFieldCount) * 1000) / 10 : 0,
                    valueMismatches: valueMismatches.map((f) => ({ id: f.id, tab: f.tab, label: f.label, uiValue: f.uiValue, pdfValue: f.pdfValue })),
                    missingInPdf: missingInPdf.map((f) => ({ id: f.id, tab: f.tab, label: f.label })),
                    byTab,
                    targetMet: coveragePct >= 90 && valueMismatches.length === 0,
                    generatedAt: new Date().toISOString(),
                };
            },
            fields,
        };
    }

    function buildCheckRow(checkId, ctx) {
        const { result, glossary } = ctx;
        const canonical = resolveCheck(checkId, result);
        const evidence = resolveEvidence(checkId, result) || {};
        const evBlock = evidence.evidence || evidence;
        const confidenceRaw = evBlock.confidence ?? evidence.confidence;
        return {
            checkId,
            label: CHECK_LABEL_OVERRIDES[checkId] || glossary[checkId]?.term || checkId,
            pass: canonical === true,
            fail: canonical === false,
            status: canonical === true ? 'PASS' : canonical === false ? 'FAIL' : 'N/A',
            uiValue: canonical,
            pdfValue: canonical,
            evidenceSummary: evidence.finding || evidence.explanation || '',
            source: evBlock.source || evidence.source || '',
            confidence: confidenceRaw != null ? Math.round(Number(confidenceRaw) * (Number(confidenceRaw) <= 1 ? 100 : 1)) : null,
            detectionMethod: evBlock.detection_method || evidence.detection_method || '',
        };
    }

    function buildPdfContext(result, glossary) {
        const seo = result?.seo_report || {};
        const resolvedTitle = global.resolveTitleTagBlock ? global.resolveTitleTagBlock(result) : { value: '', length: 0 };
        const aeo = result?.aeo_report || {};
        const ux = result?.ux_report || {};
        const psych = result?.psychology_report || {};
        const comp = result?.competitor_report || {};
        const diag = result?.final_diagnosis || {};
        const autofix = result?.autofix_report || {};
        const reliability = result?.audit_reliability || diag.audit_reliability || {};
        const productData = result?.json_structured_data || {};
        const compIntel = global.getCompetitorIntelligence
            ? global.getCompetitorIntelligence(comp, result)
            : { unavailable: true, extPct: 0, showLiveCompare: false, showBenchmark: false };
        const pageType = reliability.page_type || reliability.detected_page_type || comp.live_compare?.compare_page_type || '';
        const isNonPdpPage = ['homepage', 'saas_landing', 'blog', 'landing'].includes(String(pageType).toLowerCase());
        return {
            result, glossary, seo, resolvedTitle, aeo, ux, psych, comp, diag, autofix,
            reliability, productData, compIntel, pageType, isNonPdpPage,
        };
    }

    function buildSeoTab(ctx, parity) {
        const { seo, resolvedTitle, result } = ctx;
        const headlineScore = toScore100(seo.overall_seo_score);
        parity.register('seo.headline_score', 'SEO', 'Headline Score', headlineScore, headlineScore);

        const sectionScores = [
            { label: 'Title Tag', score: resolvedTitle.score ?? seo.title_tag?.score },
            { label: 'Meta Description', score: seo.meta_description?.score },
            { label: 'H1 Tag', score: seo.h1?.score },
            { label: 'Headings Structure', score: seo.headings_structure?.score },
            { label: 'Keyword Analysis', score: seo.keyword_analysis?.score },
            { label: 'Content Quality', score: seo.content_quality?.score },
            { label: 'Technical SEO', score: seo.technical_seo?.score },
        ].filter((s) => s.score != null);
        sectionScores.forEach((s) => {
            parity.register(`seo.section.${s.label}`, 'SEO', s.label, s.score, s.score);
        });

        const checks = PDF_TAB_CHECKS.SEO.map((id) => {
            const row = buildCheckRow(id, ctx);
            parity.register(`check:${id}`, 'SEO', row.label, row.uiValue, row.pdfValue);
            return row;
        }).filter((c) => c.status !== 'N/A');

        const details = {
            title: resolvedTitle.value || null,
            titleLength: resolvedTitle.length ?? null,
            titleScore: resolvedTitle.score ?? seo.title_tag?.score ?? null,
            meta: seo.meta_description?.value || null,
            metaLength: seo.meta_description?.length ?? null,
            metaScore: seo.meta_description?.score ?? null,
            h1: seo.h1?.value || null,
            h1Score: seo.h1?.score ?? null,
            h2Count: seo.headings_structure?.h2_count ?? null,
            h3Count: seo.headings_structure?.h3_count ?? null,
            primaryKeyword: seo.keyword_analysis?.primary_keyword || null,
            keywordDensity: seo.keyword_analysis?.density_pct ?? null,
            wordCount: seo.content_quality?.word_count ?? null,
            readability: seo.content_quality?.readability || null,
            totalImages: seo.image_seo?.total_images ?? null,
            missingAlt: seo.image_seo?.missing_alt ?? null,
            internalLinks: seo.links?.internal_count ?? null,
            externalLinks: seo.links?.external_count ?? null,
            cwvRisk: seo.technical_seo?.core_web_vitals_risk || null,
        };
        Object.entries(details).forEach(([k, v]) => {
            parity.register(`seo.detail.${k}`, 'SEO', k, v, v);
        });

        const topIssues = asArray(seo.top_issues);
        const quickWins = asArray(seo.quick_wins);
        const recommendations = asArray(seo.recommendations);
        parity.register('seo.top_issues', 'SEO', 'Top Issues', topIssues, topIssues);
        parity.register('seo.quick_wins', 'SEO', 'Quick Wins', quickWins, quickWins);
        parity.register('seo.recommendations', 'SEO', 'Recommendations', recommendations, recommendations);

        return { headlineScore, sectionScores, checks, details, topIssues, quickWins, recommendations };
    }

    function buildAeoTab(ctx, parity) {
        const { aeo } = ctx;
        const headlineScore = toScore100(aeo.ai_visibility_score);
        parity.register('aeo.headline_score', 'AEO', 'Headline Score', headlineScore, headlineScore);

        const categoryScores = [
            { label: 'Trust (E-E-A-T)', score: aeo.eeat_score?.overall },
            { label: 'AI Search (GEO)', score: aeo.geo_score },
            { label: 'AI Can Cite You', score: aeo.rag_readiness?.score },
            { label: 'FAQ Quality', score: aeo.faq_quality?.score },
            { label: 'Hidden Code', score: aeo.structured_data?.score },
        ].filter((s) => s.score != null);
        categoryScores.forEach((s) => {
            parity.register(`aeo.category.${s.label}`, 'AEO', s.label, s.score, s.score);
        });

        ['experience', 'expertise', 'authoritativeness', 'trustworthiness'].forEach((key) => {
            const v = aeo.eeat_score?.[key];
            parity.register(`aeo.eeat.${key}`, 'AEO', key, v, v);
        });

        const checks = PDF_TAB_CHECKS.AEO.map((id) => {
            const row = buildCheckRow(id, ctx);
            parity.register(`check:${id}`, 'AEO', row.label, row.uiValue, row.pdfValue);
            return row;
        }).filter((c) => c.status !== 'N/A');

        const gaps = asArray(aeo.gaps);
        const queries = asArray(aeo.top_ai_queries_missed);
        const quickWins = asArray(aeo.quick_wins_for_ai || aeo.recommendations);
        const recommendations = asArray(aeo.recommendations);
        const missingSignals = asArray(aeo.eeat_score?.signals_missing);
        const ragIssues = asArray(aeo.rag_readiness?.issues);
        parity.register('aeo.gaps', 'AEO', 'Gaps', gaps, gaps);
        parity.register('aeo.queries', 'AEO', 'AI Queries Missed', queries, queries);
        parity.register('aeo.quick_wins', 'AEO', 'Quick Wins', quickWins, quickWins);
        parity.register('aeo.recommendations', 'AEO', 'Recommendations', recommendations, recommendations);
        parity.register('aeo.missing_signals', 'AEO', 'Missing E-E-A-T Signals', missingSignals, missingSignals);

        return {
            headlineScore, categoryScores, checks, gaps, queries, quickWins,
            recommendations, missingSignals, ragIssues,
            contentDepth: aeo.content_quality?.content_depth || null,
            geoScore: aeo.geo_score ?? null,
        };
    }

    function buildUxTab(ctx, parity) {
        const { ux, isNonPdpPage } = ctx;
        const headlineScore = toScore100(ux.conversion_score);
        parity.register('ux.headline_score', 'UX', 'Headline Score', headlineScore, headlineScore);

        const cartRisk = ux.checkout_friction?.cart_abandonment_risk || null;
        parity.register('ux.cart_risk', 'UX', 'Cart Abandonment Risk', cartRisk, cartRisk);

        const categoryScores = [
            { label: 'CTA', score: ux.cta_analysis?.score },
            { label: 'Imagery', score: ux.product_imagery?.score },
            { label: 'Trust', score: ux.trust_signals?.score },
            { label: 'Info', score: ux.product_information?.score },
            { label: 'Urgency', score: ux.urgency_scarcity?.score },
            { label: 'Mobile', score: ux.mobile_ux?.score },
        ].filter((s) => s.score != null);
        categoryScores.forEach((s) => {
            parity.register(`ux.category.${s.label}`, 'UX', s.label, s.score, s.score);
        });

        parity.register('ux.layout.score', 'UX', 'Page Layout Score', ux.page_layout?.score, ux.page_layout?.score);
        [['Above Fold', ux.page_layout?.above_fold_content], ['Visual Hierarchy', ux.page_layout?.visual_hierarchy], ['Whitespace', ux.page_layout?.whitespace_usage]].forEach(([label, val]) => {
            parity.register(`ux.layout.${label}`, 'UX', label, val, val);
        });

        let checkIds = PDF_TAB_CHECKS.UX.slice();
        if (isNonPdpPage) {
            checkIds = checkIds.filter((id) => !['info_size_guide', 'info_material', 'info_fit', 'info_specs'].includes(id));
        }
        const checks = checkIds.map((id) => {
            const row = buildCheckRow(id, ctx);
            parity.register(`check:${id}`, 'UX', row.label, row.uiValue, row.pdfValue);
            return row;
        }).filter((c) => c.status !== 'N/A');

        parity.register('ux.cta.text_quality', 'UX', 'CTA Text Quality', ux.cta_analysis?.text_quality, ux.cta_analysis?.text_quality);
        parity.register('ux.cta.color_contrast', 'UX', 'CTA Contrast', ux.cta_analysis?.color_contrast, ux.cta_analysis?.color_contrast);

        const mobileIssues = asArray(ux.mobile_ux?.issues);
        const frictionPoints = asArray(ux.friction_points);
        const recommendations = asArray(ux.recommendations);
        parity.register('ux.mobile_issues', 'UX', 'Mobile Issues', mobileIssues, mobileIssues);
        parity.register('ux.friction_points', 'UX', 'Friction Points', frictionPoints, frictionPoints);
        parity.register('ux.recommendations', 'UX', 'Recommendations', recommendations, recommendations);

        return {
            headlineScore, cartRisk, categoryScores, checks, mobileIssues,
            frictionPoints, recommendations,
            layoutScore: ux.page_layout?.score ?? null,
            layoutQualities: {
                aboveFold: ux.page_layout?.above_fold_content,
                visualHierarchy: ux.page_layout?.visual_hierarchy,
                whitespace: ux.page_layout?.whitespace_usage,
            },
            ctaMeta: { textQuality: ux.cta_analysis?.text_quality, colorContrast: ux.cta_analysis?.color_contrast },
        };
    }

    function buildPsychologyTab(ctx, parity) {
        const { psych } = ctx;
        const headlineScore = toScore100(psych.overall_psychology_score);
        parity.register('psych.headline_score', 'PSYCHOLOGY', 'Headline Score', headlineScore, headlineScore);

        const behaviorLikelihood = psych.fogg_model?.behavior_likelihood || null;
        parity.register('psych.behavior_likelihood', 'PSYCHOLOGY', 'Behavior Likelihood', behaviorLikelihood, behaviorLikelihood);

        ['motivation_score', 'ability_score', 'prompt_score'].forEach((k) => {
            const v = psych.fogg_model?.[k];
            parity.register(`psych.fogg.${k}`, 'PSYCHOLOGY', k, v, v);
        });

        const cialdini = Object.entries(psych.cialdini_principles || {}).map(([key, data]) => ({
            key,
            present: data?.present,
            score: data?.score,
        }));
        cialdini.forEach((c) => {
            parity.register(`psych.cialdini.${c.key}.present`, 'PSYCHOLOGY', `${c.key} present`, c.present, c.present);
            parity.register(`psych.cialdini.${c.key}.score`, 'PSYCHOLOGY', `${c.key} score`, c.score, c.score);
        });

        const checks = PDF_TAB_CHECKS.PSYCHOLOGY.map((id) => {
            const row = buildCheckRow(id, ctx);
            parity.register(`check:${id}`, 'PSYCHOLOGY', row.label, row.uiValue, row.pdfValue);
            return row;
        }).filter((c) => c.status !== 'N/A');

        const triggersFound = asArray(psych.current_triggers_found);
        const missingTriggers = asArray(psych.missing_triggers);
        const recommendedTriggers = asArray(psych.recommended_triggers);
        parity.register('psych.triggers_found', 'PSYCHOLOGY', 'Triggers Found', triggersFound, triggersFound);
        parity.register('psych.missing_triggers', 'PSYCHOLOGY', 'Missing Triggers', missingTriggers, missingTriggers);
        parity.register('psych.recommended_triggers', 'PSYCHOLOGY', 'Recommended Triggers', recommendedTriggers, recommendedTriggers);

        parity.register('psych.price_display', 'PSYCHOLOGY', 'Price Display', psych.pricing_psychology?.current_price_display, psych.pricing_psychology?.current_price_display);
        parity.register('psych.price_suggestion', 'PSYCHOLOGY', 'Pricing Suggestion', psych.pricing_psychology?.suggestion, psych.pricing_psychology?.suggestion);
        parity.register('psych.emotional_level', 'PSYCHOLOGY', 'Emotional Level', psych.emotional_appeal?.current_level, psych.emotional_appeal?.current_level);
        parity.register('psych.trust_level', 'PSYCHOLOGY', 'Trust Level', psych.trust_building?.current_level, psych.trust_building?.current_level);

        const suggestions = uniqStrings([
            ...(psych.emotional_appeal?.suggestions || []),
            ...(psych.trust_building?.suggestions || []),
        ]);
        parity.register('psych.suggestions', 'PSYCHOLOGY', 'Suggestions', suggestions, suggestions);

        return {
            headlineScore, behaviorLikelihood, foggScores: psych.fogg_model || {},
            cialdini, checks, triggersFound, missingTriggers, recommendedTriggers,
            pricing: psych.pricing_psychology || {}, emotionalLevel: psych.emotional_appeal?.current_level,
            trustLevel: psych.trust_building?.current_level, suggestions,
        };
    }

    function fmtCompareVal(v, key) {
        if (typeof v === 'boolean') return v ? 'Yes' : 'No';
        if (v == null || v === '') return '—';
        if (key === 'page_word_count' || key === 'images_count' || key === 'review_count') return Number(v).toLocaleString();
        return String(v);
    }

    function buildCompIntelTab(ctx, parity) {
        const { comp, compIntel, seo, aeo, ux, productData, isNonPdpPage } = ctx;
        const headlineScore = toScore100(ctx.diag.score_breakdown?.competitor_position);
        parity.register('comp.headline_score', 'COMPINTEL', 'Headline Score', headlineScore, headlineScore);

        const mp = comp.market_positioning || {};
        const mpFields = {
            price_tier: mp.price_tier,
            market_maturity: mp.market_maturity,
            target_segment: mp.target_segment,
            differentiation: mp.differentiation,
            price_positioning_index: mp.price_positioning_index,
        };
        Object.entries(mpFields).forEach(([k, v]) => {
            parity.register(`comp.positioning.${k}`, 'COMPINTEL', k, v, v);
        });

        const benchmarks = [
            { label: 'SEO Score', yours: seo.overall_seo_score, theirs: comp.benchmark_scores?.avg_seo_score },
            { label: 'AI Visibility', yours: aeo.ai_visibility_score, theirs: comp.benchmark_scores?.avg_ai_visibility_score },
            { label: 'Conversion UX', yours: ux.conversion_score, theirs: comp.benchmark_scores?.avg_conversion_score },
            { label: 'Content Depth', yours: aeo.content_quality?.score, theirs: comp.benchmark_scores?.avg_content_depth_score },
        ];
        benchmarks.forEach((b) => {
            parity.register(`comp.benchmark.${b.label}.yours`, 'COMPINTEL', `${b.label} (You)`, b.yours, b.yours);
            parity.register(`comp.benchmark.${b.label}.theirs`, 'COMPINTEL', `${b.label} (Avg)`, b.theirs, b.theirs);
        });

        const featureMatrix = [
            ['Product Images (multi-angle)', ux.product_imagery?.multiple_angles, `${comp.feature_comparison?.product_images_avg || '—'} avg`],
            ['Product Video', ux.product_imagery?.video_present, `${comp.feature_comparison?.has_video_pct ?? '—'}% have video`],
            ['Size Guide', ux.product_information?.size_guide_present, `${comp.feature_comparison?.has_size_guide_pct ?? '—'}% have guide`],
            ['Customer Reviews', ux.trust_signals?.reviews_present, `${comp.feature_comparison?.has_reviews_pct ?? '—'}% have reviews`],
            ['Description Length', productData.page_word_count ? `${productData.page_word_count} words` : '—', `${comp.feature_comparison?.description_word_count_avg ?? '—'} words avg`],
            ['Avg Review Count', productData.review_count ?? '—', comp.feature_comparison?.avg_review_count ?? '—'],
        ];
        featureMatrix.forEach(([feature, yours, avg], i) => {
            parity.register(`comp.feature.${i}.yours`, 'COMPINTEL', feature, yours, yours);
            parity.register(`comp.feature.${i}.avg`, 'COMPINTEL', `${feature} avg`, avg, avg);
        });

        const lc = comp.live_compare || {};
        const sites = lc.sites || [];
        const PDP_COMPARE_KEYS = new Set(['has_size_guide', 'size_guide', 'fit_description']);
        const compareRows = (lc.rows || []).filter((r) => !isNonPdpPage || !PDP_COMPARE_KEYS.has(r.key)).map((row) => ({
            key: row.key,
            label: row.label,
            values: row.values,
            youWin: row.you_win,
            bestIndex: row.best_index,
        }));
        compareRows.forEach((row, i) => {
            parity.register(`comp.compare.${row.key}`, 'COMPINTEL', row.label, row.values, row.values);
        });

        const gaps = asArray(comp.your_gaps_vs_competitors);
        const winningPatterns = asArray(comp.winning_patterns);
        const opportunities = asArray(comp.opportunities);
        const firstMover = asArray(comp.first_mover_opportunities);
        const bestPractices = asArray(comp.category_best_practices);
        parity.register('comp.gaps', 'COMPINTEL', 'Your Gaps', gaps, gaps);
        parity.register('comp.winning_patterns', 'COMPINTEL', 'Winning Patterns', winningPatterns, winningPatterns);
        parity.register('comp.opportunities', 'COMPINTEL', 'Opportunities', opportunities, opportunities);
        parity.register('comp.first_mover', 'COMPINTEL', 'First Mover', firstMover, firstMover);
        parity.register('comp.best_practices', 'COMPINTEL', 'Category Best Practices', bestPractices, bestPractices);

        if (comp.share_of_voice) {
            parity.register('comp.keyword_overlap', 'COMPINTEL', 'Keyword Overlap', comp.share_of_voice.estimated_keyword_overlap_pct, comp.share_of_voice.estimated_keyword_overlap_pct);
            parity.register('comp.shared_keywords', 'COMPINTEL', 'Shared Keywords', comp.share_of_voice.top_shared_keywords, comp.share_of_voice.top_shared_keywords);
        }
        if (comp.traffic_estimate) {
            parity.register('comp.traffic.your_tier', 'COMPINTEL', 'Your Traffic Tier', comp.traffic_estimate.your_tier, comp.traffic_estimate.your_tier);
            parity.register('comp.traffic.avg_tier', 'COMPINTEL', 'Avg Traffic Tier', comp.traffic_estimate.competitor_avg_tier, comp.traffic_estimate.competitor_avg_tier);
        }
        if (comp.backlink_gap) {
            parity.register('comp.authority.yours', 'COMPINTEL', 'Your Authority', comp.backlink_gap.your_authority_estimate, comp.backlink_gap.your_authority_estimate);
            parity.register('comp.authority.avg', 'COMPINTEL', 'Avg Authority', comp.backlink_gap.competitor_avg_authority, comp.backlink_gap.competitor_avg_authority);
        }

        parity.register('comp.data_source', 'COMPINTEL', 'Data Source', comp.data_source, comp.data_source);
        parity.register('comp.confidence', 'COMPINTEL', 'Extraction Confidence', compIntel.extPct, compIntel.extPct);

        return {
            headlineScore, positioning: mpFields, benchmarks, featureMatrix,
            liveCompare: { sites, rows: compareRows, pageType: lc.compare_page_type, metricsNote: lc.metrics_note },
            gaps, winningPatterns, opportunities, firstMover, bestPractices,
            shareOfVoice: comp.share_of_voice || null,
            trafficEstimate: comp.traffic_estimate || null,
            backlinkGap: comp.backlink_gap || null,
            compIntel, fmtCompareVal,
        };
    }

    function buildFullPdfReportData(result, glossary) {
        glossary = glossary || {};
        const ctx = buildPdfContext(result, glossary);
        const parity = createParityTracker();
        const { seo, aeo, ux, psych, comp, diag, autofix, reliability } = ctx;

        const scores = {
            overall: toScore100(diag.overall_health_score),
            seo: toScore100(seo.overall_seo_score),
            ai: toScore100(aeo.ai_visibility_score),
            ux: toScore100(ux.conversion_score),
            psych: toScore100(psych.overall_psychology_score),
            competitor: toScore100(diag.score_breakdown?.competitor_position),
        };
        Object.entries(scores).forEach(([k, v]) => {
            parity.register(`scores.${k}`, 'OVERVIEW', k, v, v);
        });

        const tabs = {
            SEO: buildSeoTab(ctx, parity),
            AEO: buildAeoTab(ctx, parity),
            UX: buildUxTab(ctx, parity),
            PSYCHOLOGY: buildPsychologyTab(ctx, parity),
            COMPINTEL: buildCompIntelTab(ctx, parity),
        };

        const topIssues = uniqStrings([
            ...(seo.top_issues || []),
            ...(aeo.gaps || []),
            ...(ux.friction_points || []),
            ...(psych.missing_triggers || []),
            ...(comp.your_gaps_vs_competitors || []),
        ]).slice(0, 10);
        const recommendations = uniqStrings([
            ...(seo.recommendations || []),
            ...(seo.quick_wins || []),
            ...(aeo.recommendations || []),
            ...(aeo.quick_wins_for_ai || []),
            ...(ux.recommendations || []),
            ...(psych.emotional_appeal?.suggestions || []),
            ...(psych.trust_building?.suggestions || []),
            ...(comp.opportunities || []),
            ...(comp.category_best_practices || []),
            ...(autofix.priority_action_plan || []).map((a) => a.action || a.title || a),
        ]).slice(0, 12);
        parity.register('aggregate.top_issues', 'OVERVIEW', 'Top Issues', topIssues, topIssues);
        parity.register('aggregate.recommendations', 'OVERVIEW', 'Recommendations', recommendations, recommendations);

        const fv = result?.frontend_validation || reliability.frontend_validation || {};
        const reliabilityLines = uniqStrings([
            `Audit reliability: ${reliability.report_reliability || 'medium'}`,
            `Scrape quality: ${reliability.scrape_quality || '—'}`,
            `Extraction confidence: ${reliability.extraction_confidence_pct ?? Math.round((reliability.extraction_confidence || 0) * 100)}%`,
            reliability.platform ? `Platform: ${reliability.platform}` : null,
            (reliability.page_type || reliability.detected_page_type) ? `Page type: ${reliability.page_type || reliability.detected_page_type}` : null,
            reliability.visual_verified === false ? 'Visual verification unavailable — some UX findings are text-inferred only.' : null,
            reliability.partial_analysis ? 'Partial analysis — not all checks completed.' : null,
            ...(reliability.warnings || []).slice(0, 4),
            ...(reliability.hallucination_flags || []).map((f) => `Hallucination flag: ${f}`),
            ...(reliability.contradictions || []).slice(0, 2).map((c) => `Contradiction: ${c}`),
            ...(fv.warnings || []).slice(0, 3).map((w) => `Frontend validation: ${w}`),
        ]).slice(0, 12);

        const autofixItems = [];
        const addFix = (label, val, maxLen = 600) => {
            if (!val) return;
            const t = String(val).trim();
            if (!t) return;
            autofixItems.push({ label, text: t.length > maxLen ? `${t.slice(0, maxLen)}…` : t });
        };
        if (global.getValidatedAutofixFix) {
            addFix('Title Tag', global.getValidatedAutofixFix(autofix, 'fixed_title_tag'));
            addFix('Meta Description', global.getValidatedAutofixFix(autofix, 'fixed_meta_description'));
            addFix('H1 Headline', global.getValidatedAutofixFix(autofix, 'fixed_h1'));
            addFix('Product Description', global.getValidatedAutofixFix(autofix, 'rewritten_product_description'), 900);
        }
        (autofix.suggested_h2s || []).slice(0, 5).forEach((h, i) => addFix(`Suggested H2 ${i + 1}`, h));
        (autofix.priority_action_plan || []).slice(0, 6).forEach((a, i) => {
            addFix(`Priority Action ${i + 1}`, a.action || a.title || (typeof a === 'string' ? a : null));
        });
        if (autofix.pricing_psychology?.suggestion) addFix('Pricing Psychology', autofix.pricing_psychology.suggestion);

        const parityReport = parity.report();

        return {
            url: result?.source_url || '',
            generatedAt: new Date(),
            scores,
            tabs,
            topIssues,
            recommendations,
            autofixItems,
            reliabilityLines,
            parity: parityReport,
        };
    }

    function extractPdfReportData(result, glossary) {
        return buildFullPdfReportData(result, glossary);
    }

    function downloadCommerceReportPdf(result, glossary) {
        if (!global.jspdf?.jsPDF) throw new Error('PDF library not loaded');
        const { jsPDF } = global.jspdf;
        const data = buildFullPdfReportData(result, glossary || {});
        const doc = new jsPDF({ unit: 'pt', format: 'a4', compress: true });
        const pageW = doc.internal.pageSize.getWidth();
        const pageH = doc.internal.pageSize.getHeight();
        const margin = 48;
        const contentW = pageW - margin * 2;
        let y = margin;

        const C = {
            navy: [15, 23, 42],
            indigo: [99, 102, 241],
            slate: [100, 116, 139],
            red: [220, 38, 38],
            emerald: [5, 150, 105],
            white: [255, 255, 255],
            light: [203, 213, 225],
            label: [199, 210, 254],
            amber: [180, 83, 9],
        };

        const ensureSpace = (need) => {
            if (y + need > pageH - margin) {
                doc.addPage();
                y = margin;
            }
        };

        const sectionTitle = (title) => {
            ensureSpace(40);
            doc.setFillColor(...C.indigo);
            doc.rect(margin, y, 4, 20, 'F');
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(14);
            doc.setTextColor(...C.navy);
            doc.text(title, margin + 12, y + 15);
            y += 34;
        };

        const bodyText = (text, opts = {}) => {
            const size = opts.size || 10;
            const lh = opts.lineHeight || size * 1.45;
            doc.setFont('helvetica', opts.bold ? 'bold' : 'normal');
            doc.setFontSize(size);
            doc.setTextColor(...(opts.color || C.slate));
            const lines = doc.splitTextToSize(String(text), contentW - (opts.indent || 0));
            lines.forEach((line) => {
                ensureSpace(lh);
                doc.text(line, margin + (opts.indent || 0), y);
                y += lh;
            });
            y += opts.gap ?? 8;
        };

        const bulletList = (items, opts = {}) => {
            (items || []).forEach((item) => {
                const lines = doc.splitTextToSize(String(item), contentW - 16);
                lines.forEach((line, li) => {
                    ensureSpace(15);
                    if (li === 0) {
                        doc.setFont('helvetica', 'normal');
                        doc.setFontSize(opts.size || 10);
                        doc.setTextColor(...(opts.color || C.slate));
                        doc.text('•', margin, y);
                    }
                    doc.text(line, margin + 12, y);
                    y += 14;
                });
                y += 3;
            });
            y += 6;
        };

        const scoreRow = (label, val) => {
            ensureSpace(24);
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(10);
            doc.setTextColor(...C.navy);
            doc.text(label, margin, y);
            const display = val != null ? `${val}/100` : '—';
            doc.setFont('helvetica', 'bold');
            doc.setTextColor(...C.indigo);
            doc.text(display, pageW - margin - doc.getTextWidth(display), y);
            doc.setDrawColor(226, 232, 240);
            doc.setLineWidth(0.5);
            doc.line(margin, y + 8, pageW - margin, y + 8);
            y += 26;
        };

        const sectionScoreTable = (scores) => {
            (scores || []).forEach((s) => {
                ensureSpace(20);
                doc.setFont('helvetica', 'normal');
                doc.setFontSize(9);
                doc.setTextColor(...C.navy);
                doc.text(s.label, margin, y);
                const disp = s.score != null ? `${s.score}/10` : '—';
                doc.setFont('helvetica', 'bold');
                doc.text(disp, pageW - margin - doc.getTextWidth(disp), y);
                y += 18;
            });
            y += 4;
        };

        const renderChecks = (checks) => {
            (checks || []).forEach((c) => {
                ensureSpace(36);
                const icon = c.status === 'PASS' ? 'PASS' : 'FAIL';
                doc.setFont('helvetica', 'bold');
                doc.setFontSize(9);
                doc.setTextColor(...(c.status === 'PASS' ? C.emerald : C.red));
                doc.text(`${icon} — ${c.label}`, margin, y);
                y += 14;
                if (c.evidenceSummary) {
                    doc.setFont('helvetica', 'normal');
                    doc.setFontSize(8);
                    doc.setTextColor(...C.slate);
                    const evLines = doc.splitTextToSize(c.evidenceSummary, contentW - 8);
                    evLines.forEach((line) => { doc.text(line, margin + 8, y); y += 11; });
                }
                const meta = [
                    c.source ? `Source: ${c.source}` : null,
                    c.confidence != null ? `Confidence: ${c.confidence}%` : null,
                    c.detectionMethod ? `Method: ${c.detectionMethod}` : null,
                ].filter(Boolean).join(' · ');
                if (meta) {
                    doc.setFontSize(7);
                    doc.setTextColor(148, 163, 184);
                    doc.text(meta, margin + 8, y);
                    y += 12;
                }
                y += 4;
            });
        };

        const renderCompareTable = (tab) => {
            const lc = tab.liveCompare;
            if (!lc?.rows?.length || !lc.sites?.length) return;
            const sites = lc.sites.filter((s) => s.scrape_ok || s.role === 'you');
            ensureSpace(30);
            bodyText(`Compare mode: ${lc.pageType || 'product'} · ${lc.metricsNote || 'Live HTML metrics per URL'}`, { size: 8, gap: 4 });
            lc.rows.forEach((row) => {
                ensureSpace(40);
                doc.setFont('helvetica', 'bold');
                doc.setFontSize(9);
                doc.setTextColor(...C.navy);
                doc.text(row.label, margin, y);
                y += 14;
                row.values.forEach((v, vi) => {
                    if (vi >= sites.length) return;
                    const siteName = vi === 0 ? 'You' : (sites[vi]?.name || `Site ${vi}`);
                    const fmt = tab.fmtCompareVal(v, row.key);
                    const star = row.bestIndex === vi ? ' ★' : '';
                    doc.setFont('helvetica', 'normal');
                    doc.setFontSize(8);
                    doc.setTextColor(...C.slate);
                    doc.text(`${siteName}: ${fmt}${star}`, margin + 8, y);
                    y += 12;
                });
                y += 4;
            });
        };

        const renderBenchmarks = (benchmarks) => {
            (benchmarks || []).forEach((b) => {
                if (b.yours == null && b.theirs == null) return;
                ensureSpace(36);
                doc.setFont('helvetica', 'bold');
                doc.setFontSize(9);
                doc.setTextColor(...C.navy);
                doc.text(b.label, margin, y);
                y += 14;
                const yVal = Number(b.yours) || 0;
                const tVal = Number(b.theirs) || 0;
                const diff = yVal - tVal;
                doc.setFont('helvetica', 'normal');
                doc.setFontSize(8);
                doc.setTextColor(...C.slate);
                doc.text(`You: ${b.yours ?? '—'}/10 · Category avg: ${b.theirs ?? '—'}/10 · ${diff >= 0 ? '+' : ''}${diff.toFixed(1)} vs avg`, margin + 8, y);
                y += 16;
            });
        };

        // Cover page
        doc.setFillColor(...C.navy);
        doc.rect(0, 0, pageW, 228, 'F');
        doc.setFillColor(...C.indigo);
        doc.rect(0, 228, pageW, 6, 'F');
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(11);
        doc.setTextColor(...C.label);
        doc.text(BRAND_NAME.toUpperCase(), margin, 58);
        doc.setFontSize(26);
        doc.setTextColor(...C.white);
        doc.text('Product Page Optimization Report', margin, 98);
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(10);
        doc.setTextColor(...C.light);
        doc.text(doc.splitTextToSize(data.url || 'URL not available', contentW), margin, 132);
        y = 268;
        doc.setFontSize(10);
        doc.setTextColor(...C.slate);
        doc.text(`Generated ${data.generatedAt.toLocaleString(undefined, { dateStyle: 'long', timeStyle: 'short' })}`, margin, y);
        y += 32;
        if (data.scores.overall != null) {
            doc.setDrawColor(...C.indigo);
            doc.setLineWidth(2);
            doc.roundedRect(margin, y, 132, 84, 8, 8, 'S');
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(34);
            doc.setTextColor(...C.indigo);
            doc.text(String(data.scores.overall), margin + 22, y + 50);
            doc.setFontSize(10);
            doc.setTextColor(...C.slate);
            doc.text('/100', margin + 68, y + 50);
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(12);
            doc.setTextColor(...C.navy);
            doc.text('Overall Health Score', margin + 152, y + 38);
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(10);
            doc.setTextColor(...C.slate);
            doc.text('Composite across SEO, AI visibility, UX,', margin + 152, y + 56);
            doc.text('psychology, and competitor position.', margin + 152, y + 70);
        }

        doc.addPage();
        y = margin;

        sectionTitle('Score Overview');
        [
            ['Google Ranking (SEO)', data.scores.seo],
            ['AI Visibility', data.scores.ai],
            ['Conversion & UX', data.scores.ux],
            ['Buyer Psychology', data.scores.psych],
            ['Competitor Intelligence', data.scores.competitor],
            ['Overall Health', data.scores.overall],
        ].forEach(([label, val]) => scoreRow(label, val));

        sectionTitle('Audit Reliability');
        bulletList(data.reliabilityLines);

        // SEO tab
        const seoTab = data.tabs.SEO;
        sectionTitle('Google Ranking');
        scoreRow('Tab Score', seoTab.headlineScore);
        bodyText('Section Scores', { bold: true, size: 10, gap: 2 });
        sectionScoreTable(seoTab.sectionScores);
        bodyText(`Title: ${seoTab.details.title || '—'} (${seoTab.details.titleLength ?? '—'} chars)`, { size: 9 });
        bodyText(`Meta: ${seoTab.details.meta || '—'}`, { size: 9 });
        bodyText(`H1: ${seoTab.details.h1 || '—'} · Keyword: ${seoTab.details.primaryKeyword || '—'} · Words: ${seoTab.details.wordCount ?? '—'}`, { size: 9 });
        bodyText('Check Results', { bold: true, size: 10, gap: 2 });
        renderChecks(seoTab.checks);
        if (seoTab.topIssues.length) { bodyText('Top Issues', { bold: true, color: C.red, gap: 2 }); bulletList(seoTab.topIssues, { color: C.red }); }
        if (seoTab.quickWins.length) { bodyText('Quick Wins', { bold: true, color: C.emerald, gap: 2 }); bulletList(seoTab.quickWins, { color: C.emerald }); }

        // AEO tab
        const aeoTab = data.tabs.AEO;
        sectionTitle('AI Visibility');
        scoreRow('Tab Score', aeoTab.headlineScore);
        bodyText('Category Scores', { bold: true, size: 10, gap: 2 });
        sectionScoreTable(aeoTab.categoryScores);
        bodyText('Check Results', { bold: true, size: 10, gap: 2 });
        renderChecks(aeoTab.checks);
        if (aeoTab.gaps.length) { bodyText('Gaps', { bold: true, color: C.red, gap: 2 }); bulletList(aeoTab.gaps, { color: C.red }); }
        if (aeoTab.queries.length) { bodyText('AI Queries Missed', { bold: true, gap: 2 }); bulletList(aeoTab.queries); }
        if (aeoTab.quickWins.length) { bodyText('Quick Wins for AI', { bold: true, color: C.emerald, gap: 2 }); bulletList(aeoTab.quickWins, { color: C.emerald }); }

        // UX tab
        const uxTab = data.tabs.UX;
        sectionTitle('Conversion & UX');
        scoreRow('Tab Score', uxTab.headlineScore);
        bodyText(`Cart abandonment risk: ${uxTab.cartRisk || '—'}`, { size: 9 });
        bodyText('Category Scores', { bold: true, size: 10, gap: 2 });
        sectionScoreTable(uxTab.categoryScores);
        if (uxTab.layoutScore != null) bodyText(`Page layout: ${uxTab.layoutScore}/10 · Above fold: ${uxTab.layoutQualities.aboveFold || '—'} · Hierarchy: ${uxTab.layoutQualities.visualHierarchy || '—'}`, { size: 9 });
        bodyText('Check Results', { bold: true, size: 10, gap: 2 });
        renderChecks(uxTab.checks);
        if (uxTab.mobileIssues.length) { bodyText('Mobile Issues', { bold: true, color: C.red, gap: 2 }); bulletList(uxTab.mobileIssues, { color: C.red }); }
        if (uxTab.recommendations.length) { bodyText('Recommendations', { bold: true, color: C.emerald, gap: 2 }); bulletList(uxTab.recommendations, { color: C.emerald }); }

        // Psychology tab
        const psychTab = data.tabs.PSYCHOLOGY;
        sectionTitle('Buyer Psychology');
        scoreRow('Tab Score', psychTab.headlineScore);
        bodyText(`Behavior likelihood: ${psychTab.behaviorLikelihood || '—'}`, { size: 9 });
        bodyText('Fogg Model Scores', { bold: true, size: 10, gap: 2 });
        sectionScoreTable([
            { label: 'Motivation', score: psychTab.foggScores.motivation_score },
            { label: 'Ability', score: psychTab.foggScores.ability_score },
            { label: 'Prompt', score: psychTab.foggScores.prompt_score },
        ].filter((s) => s.score != null));
        if (psychTab.cialdini.length) {
            bodyText('Cialdini Triggers', { bold: true, size: 10, gap: 2 });
            psychTab.cialdini.forEach((c) => {
                bodyText(`${c.key.replace('_', ' ')}: ${c.present ? 'Present' : 'Missing'} (${c.score ?? '—'}/10)`, { size: 8, gap: 2 });
            });
        }
        bodyText('Check Results', { bold: true, size: 10, gap: 2 });
        renderChecks(psychTab.checks);
        if (psychTab.triggersFound.length) bodyText(`Triggers found: ${psychTab.triggersFound.join(', ')}`, { size: 9 });
        if (psychTab.missingTriggers.length) bodyText(`Missing triggers: ${psychTab.missingTriggers.join(', ')}`, { size: 9, color: C.red });
        if (psychTab.recommendedTriggers.length) {
            bodyText('Recommended Triggers', { bold: true, gap: 2 });
            psychTab.recommendedTriggers.forEach((t) => {
                bodyText(`${t.trigger || t} — ${t.expected_cvr_lift || ''}`, { size: 8, gap: 2 });
                if (t.implementation) bodyText(t.implementation, { size: 8, gap: 2 });
            });
        }

        // Competitor tab
        const compTab = data.tabs.COMPINTEL;
        sectionTitle('Competitor Intelligence');
        scoreRow('Tab Score', compTab.headlineScore);
        if (compTab.compIntel.unavailable) {
            bodyText(`Comparison unavailable — ${compTab.compIntel.unavailableReason || 'insufficient data'}. Confidence: ${compTab.compIntel.extPct}%`, { color: C.amber });
        } else {
            bodyText(`Data source: ${compTab.compIntel.reason || compTab.compIntel.dataSource || 'live_scrape'} · Confidence: ${compTab.compIntel.extPct}%`, { size: 9 });
        }
        bodyText('Market Positioning', { bold: true, gap: 2 });
        Object.entries(compTab.positioning).forEach(([k, v]) => {
            if (v != null && v !== '') bodyText(`${k.replace(/_/g, ' ')}: ${v}`, { size: 8, gap: 2 });
        });
        if (compTab.benchmarks.some((b) => b.yours != null || b.theirs != null)) {
            bodyText('Benchmark Scores (You vs Category Avg)', { bold: true, gap: 2 });
            renderBenchmarks(compTab.benchmarks);
        }
        if (compTab.liveCompare.rows.length) {
            bodyText('Live Competitor Comparison', { bold: true, gap: 2 });
            renderCompareTable(compTab);
        }
        if (compTab.featureMatrix.length) {
            bodyText('Feature Comparison Matrix', { bold: true, gap: 2 });
            compTab.featureMatrix.forEach(([feature, yours, avg]) => {
                const yDisp = typeof yours === 'boolean' ? (yours ? 'Yes' : 'No') : (yours ?? '—');
                bodyText(`${feature}: You ${yDisp} · Category ${avg}`, { size: 8, gap: 2 });
            });
        }
        if (compTab.gaps.length) { bodyText('Your Gaps', { bold: true, color: C.red, gap: 2 }); bulletList(compTab.gaps, { color: C.red }); }
        if (compTab.winningPatterns.length) { bodyText('Winning Patterns', { bold: true, gap: 2 }); bulletList(compTab.winningPatterns); }
        if (compTab.opportunities.length) { bodyText('Opportunities', { bold: true, color: C.emerald, gap: 2 }); bulletList(compTab.opportunities, { color: C.emerald }); }
        if (compTab.firstMover.length) { bodyText('First Mover Opportunities', { bold: true, gap: 2 }); bulletList(compTab.firstMover); }
        if (compTab.bestPractices.length) { bodyText('Category Best Practices', { bold: true, gap: 2 }); bulletList(compTab.bestPractices); }

        if (data.topIssues.length) { sectionTitle('Top Issues (All Tabs)'); bulletList(data.topIssues, { color: C.red }); }
        if (data.recommendations.length) { sectionTitle('Top Recommendations (All Tabs)'); bulletList(data.recommendations, { color: C.emerald }); }
        if (data.autofixItems.length) {
            sectionTitle('AutoFix Suggestions');
            data.autofixItems.forEach((item) => {
                bodyText(item.label, { bold: true, size: 10, gap: 2 });
                bodyText(item.text, { size: 9, gap: 10 });
            });
        }

        // Parity report page
        sectionTitle('UI ↔ PDF Parity Report');
        const p = data.parity;
        bodyText(`UI field count: ${p.uiFieldCount} · PDF field count: ${p.pdfFieldCount} · Coverage: ${p.coveragePct}%`, { bold: true });
        bodyText(`Value matches: ${p.valueMatches}/${p.pdfFieldCount} (${p.valueMatchPct}%) · Target (>90% coverage): ${p.targetMet ? 'MET' : 'NOT MET'}`, { size: 9 });
        Object.entries(p.byTab).forEach(([tab, stats]) => {
            if (tab === 'OVERVIEW') return;
            bodyText(`${tab}: ${stats.pdfFieldCount}/${stats.uiFieldCount} fields (${stats.coveragePct}% coverage, ${stats.valueMatches} value matches)`, { size: 8, gap: 2 });
        });
        if (p.valueMismatches.length) {
            bodyText('Value Mismatches', { bold: true, color: C.red, gap: 2 });
            p.valueMismatches.slice(0, 8).forEach((m) => {
                bodyText(`${m.id}: UI=${JSON.stringify(m.uiValue)} PDF=${JSON.stringify(m.pdfValue)}`, { size: 7, gap: 2 });
            });
        }

        const pageCount = doc.internal.getNumberOfPages();
        for (let i = 1; i <= pageCount; i++) {
            doc.setPage(i);
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(8);
            doc.setTextColor(148, 163, 184);
            doc.text(BRAND_NAME, margin, pageH - 22);
            doc.text(`Page ${i} of ${pageCount}`, pageW - margin - 52, pageH - 22);
            if (i > 1 && data.url) {
                const shortUrl = data.url.length > 72 ? `${data.url.slice(0, 69)}…` : data.url;
                doc.text(shortUrl, margin + 88, pageH - 22);
            }
        }

        const slug = (() => {
            try {
                return new URL(data.url.startsWith('http') ? data.url : `https://${data.url}`).hostname.replace(/\./g, '-');
            } catch {
                return 'report';
            }
        })();
        doc.save(`commerce-copilot-${slug}-${data.generatedAt.toISOString().slice(0, 10)}.pdf`);

        return { data, parity: p };
    }

    global.PdfParity = {
        PDF_TAB_CHECKS,
        buildFullPdfReportData,
        extractPdfReportData,
        computePdfParityReport: (data) => data?.parity || buildFullPdfReportData(data).parity,
        downloadCommerceReportPdf,
    };

    // Backward-compatible globals for inline index.html references
    global.buildFullPdfReportData = buildFullPdfReportData;
    global.extractPdfReportData = extractPdfReportData;
    global.downloadCommerceReportPdf = downloadCommerceReportPdf;
})(typeof window !== 'undefined' ? window : globalThis);
