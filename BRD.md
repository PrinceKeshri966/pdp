=============================================================
         MULTI-AGENT COMMERCE OS - SYSTEM ARCHITECTURE
=============================================================

[ MODE 1: PDP Analysis Flow ]

  ( URL Input )
       │
       ▼
 ┌────────────────────┐       ▤ TOOLS USED: Jina Reader API, Playwright (Fallback)
 │   Scraper Agent    │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. E-commerce page ka raw HTML DOM pull karna.
       │                        2. Shopify/JS-heavy sites ke liye browser execution.
       │                        3. Smart fallback check (<800 chars par Playwright).
       ├─ ✖ BOTH FAIL ──────▶ [ DB: status=failed ] (Pipeline Aborts)
       │
       ▼ (Success)
 ┌────────────────────┐       ▤ TOOLS USED: Claude Haiku (Fast Parse)
 │  Extractor Agent   │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Raw text se headers/footers/ads filter karna.
       │                        2. Data ko structured JSON schema mein map karna.
       ▼                        3. Core attributes (Price, Name, Reviews) nikalna.

 ┌────────────────────┐       ▤ TOOLS USED: Claude Haiku + Python (Deterministic)
 │     SEO Agent      │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Meta title/description ki length validate karna.
       │                        2. H1, H2, H3 tag hierarchy structure check karna.
       ▼                        3. Image Alt tags aur Schema markup scan karna.

 ┌────────────────────┐       ▤ TOOLS USED: Claude Sonnet (Reasoning)
 │   AutoFix Agent    │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Missing metadata ke liye optimized copy rewrite karna.
       │                        2. Copy-paste ready JSON-LD schema generate karna.
       ▼                        3. Merchant ke liye priority action plan banana.

[( Save to Postgres DB )]
      (status=completed)


-------------------------------------------------------------


[ MODE 2: Blueprint Generation Flow ]

  ( Merchant Brief )
       │
       ▼
 ┌────────────────────┐       ▤ TOOLS USED: Claude Sonnet (Intent Extract)
 │   Business Agent   │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Unstructured text se marketing intent samajhna.
       │                        2. Target audience aur buying motivations segment karna.
       ▼                        3. Brand ke USPs aur competitors identify karna.

 ┌────────────────────┐       ▤ TOOLS turning: Claude Haiku (Benchmarking)
 │ PDPResearcher Agent│ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Category ke e-commerce benchmarks fetch karna.
       │                        2. High-converting trust signals aur layouts track karna.
       ▼                        3. Top competitors ke conversion strategies compare karna.

 ┌────────────────────┐       ▤ TOOLS USED: Claude Sonnet (Synthesis)
 │  Blueprint Agent   │ ────▶ ❖ USE CASES:
 └────────────────────┘         1. Research data synthesize karke operational plan banana.
       │                        2. Naye PDP ke liye landing page architecture design karna.
       ▼                        3. A/B testing recommendations aur KPIs project karna.

[( Save to Postgres DB )]
      (status=completed)



=============================================================
         DATABASE SCHEMA — WHAT GETS SAVED
=============================================================

[ TABLE 1: analysis_reports ]  ← Mode 1 ka output

  ┌─────────────────────┬──────────────────────────────────────────────────┐
  │ Column              │ What is saved                                    │
  ├─────────────────────┼──────────────────────────────────────────────────┤
  │ id (UUID)           │ Auto-generated unique report ID                  │
  │ tenant_id (FK)      │ Kis company/brand ka request tha                 │
  │ user_id (FK)        │ Kis user ne request kiya                         │
  │ source_url          │ Original product page URL                        │
  │ raw_markdown        │ Scraper ka full output (Jina/Playwright text)    │
  │ seo_report (JSONB)  │ SEO Agent ka complete JSON output                │
  │ autofix_report(JSONB)│ AutoFix Agent ka complete JSON output            │
  │ agent_logs (JSONB)  │ Har agent ka audit log (model, tokens, duration) │
  │ scraper_method      │ jina ya playwright - kaunsa path use hua         │
  │ total_tokens        │ Pipeline mein use hue total input+output tokens  │
  │ seo_score           │ Overall SEO score (float, e.g. 7.4)              │
  │ overall_score       │ Combined pipeline score                          │
  │ status              │ pending → running → completed / failed           │
  │ error_message       │ Agar pipeline fail hua toh reason                │
  │ created_at          │ Request aane ka time                             │
  │ completed_at        │ Pipeline finish hone ka time                     │
  └─────────────────────┴──────────────────────────────────────────────────┘

  NOTE: agent_logs stores full audit trail - every agent that ran,
        which model it used, tokens consumed, and duration_ms.
        Enables per-tenant cost tracking and production debugging.


[ TABLE 2: blueprints ]  ← Mode 2 ka output

  ┌──────────────────────────┬───────────────────────────────────────────────┐
  │ Column                   │ What is saved                                 │
  ├──────────────────────────┼───────────────────────────────────────────────┤
  │ id (UUID)                │ Auto-generated unique blueprint ID            │
  │ tenant_id (FK)           │ Kis company/brand ka request tha              │
  │ user_id (FK)             │ Kis user ne request kiya                      │
  │ business_input           │ Merchant ka original raw text brief           │
  │ business_understanding   │ BusinessAgent ka full JSON output (JSONB)     │
  │ pdp_research (JSONB)     │ PDPResearcher Agent ka full JSON output       │
  │ final_blueprint (JSONB)  │ BlueprintAgent ka complete final output       │
  │ title                    │ Blueprint ka auto-generated title             │
  │ version                  │ Blueprint version number (default: 1)         │
  │ status                   │ pending → running → completed / failed        │
  │ error_message            │ Agar pipeline fail hua toh reason             │
  │ created_at               │ Request aane ka time                          │
  │ completed_at             │ Pipeline finish hone ka time                  │
  └──────────────────────────┴───────────────────────────────────────────────┘


[ TABLE 3: tenants ]  ← Multi-tenancy isolation

  ┌──────────────────┬─────────────────────────────────────────────────────┐
  │ Column           │ What is saved                                       │
  ├──────────────────┼─────────────────────────────────────────────────────┤
  │ id (UUID)        │ Tenant ka unique ID                                 │
  │ clerk_org_id     │ Clerk SSO Organization ID (for JWT mapping)         │
  │ name             │ Brand/Company name                                  │
  │ slug             │ URL-safe unique identifier (e.g. "killer-jeans")    │
  │ plan             │ Subscription plan: free / pro / enterprise          │
  │ is_active        │ Account active hai ya suspended                     │
  │ settings (JSONB) │ Tenant-level AI preferences, brand tone config      │
  │ created_at       │ Account creation timestamp                          │
  └──────────────────┴─────────────────────────────────────────────────────┘


[ TABLE 4: users ]  ← User identity mapping

  ┌──────────────────┬─────────────────────────────────────────────────────┐
  │ Column           │ What is saved                                       │
  ├──────────────────┼─────────────────────────────────────────────────────┤
  │ id (UUID)        │ User ka unique DB ID                                │
  │ clerk_user_id    │ Clerk SSO User ID (e.g. "user_2NxAbc...")           │
  │ tenant_id (FK)   │ Kis tenant se belong karta hai                      │
  │ email            │ User email address                                  │
  │ role             │ owner / admin / member                              │
  │ is_superadmin    │ Platform-level superadmin flag                      │
  │ last_login_at    │ Last login timestamp                                │
  └──────────────────┴─────────────────────────────────────────────────────┘


[ DB WRITE SEQUENCE — Request Lifecycle ]

  1. API request aata hai
       │
       ▼
  2. DB mein record CREATE hota hai (status = "running")
     → Client ko turant ID mil jaati hai
       │
       ▼
  3. LangGraph pipeline run hoti hai
       │
       ├─ SUCCESS → seo_report / final_blueprint save hota hai
       │            status = "completed", completed_at = now()
       │
       └─ FAILURE → error_message save hota hai
                    status = "failed"


=============================================================
         ERROR HANDLING MATRIX
=============================================================

  ┌──────────────────────────────┬─────────────────────────────┬──────────────────────────┬─────────────────────────┐
  │ Failure Scenario             │ Agent / Layer               │ Action Taken             │ DB Updated?             │
  ├──────────────────────────────┼─────────────────────────────┼──────────────────────────┼─────────────────────────┤
  │ URL missing in request       │ ScraperAgent                │ status=failed, error log │ ✅ Yes — error_message  │
  │ Jina Reader HTTP 4xx/5xx     │ ScraperAgent                │ Auto Playwright fallback │ ❌ No — pipeline continues│
  │ Jina returns < 800 chars     │ ScraperAgent                │ Auto Playwright fallback │ ❌ No — pipeline continues│
  │ Playwright crash / timeout   │ ScraperAgent                │ status=failed, abort     │ ✅ Yes — error_message  │
  │ Both Jina + Playwright fail  │ ScraperAgent                │ status=failed, abort     │ ✅ Yes — error_message  │
  │ No markdown_content in state │ ExtractorAgent              │ Error appended, skip     │ ❌ No — non-fatal       │
  │ Claude Haiku timeout         │ Extractor / SEO / PDP Agent │ status=failed, abort     │ ✅ Yes — error_message  │
  │ Claude JSON parse failure    │ Any LLM Agent               │ safe_json_parse() retry  │ ❌ No — auto-recovered  │
  │ No seo_report in state       │ AutoFixAgent                │ Error appended, skip     │ ❌ No — non-fatal       │
  │ Claude Sonnet timeout        │ AutoFix / Business / Blueprint│ status=failed, abort   │ ✅ Yes — error_message  │
  │ No business_input in state   │ BusinessAgent               │ status=failed, abort     │ ✅ Yes — error_message  │
  │ Missing understanding/research│ BlueprintAgent             │ status=failed, abort     │ ✅ Yes — error_message  │
  │ Unhandled pipeline exception │ FastAPI route handler       │ HTTP 500, status=failed  │ ✅ Yes — error_message  │
  │ Pipeline completes fully     │ AutoFix / BlueprintAgent    │ status=completed         │ ✅ Yes — completed_at   │
  └──────────────────────────────┴─────────────────────────────┴──────────────────────────┴─────────────────────────┘


[ ERROR FLOW DIAGRAM ]

  Any Agent Failure
       │
       ▼
  state["errors"].append(error_message)
       │
       ├─ NON-FATAL (missing optional data)
       │       │
       │       ▼
       │  Pipeline continues to next node
       │
       └─ FATAL (scraper fail / Claude fail / missing required input)
               │
               ▼
         state["status"] = "failed"
               │
               ▼
         _should_continue() → returns "abort"
               │
               ▼
         LangGraph routes to END (skips remaining nodes)
               │
               ▼
         DB record updated: status=failed + error_message saved


[ SAFE JSON PARSE — Auto Recovery ]

  Claude ka raw output → safe_json_parse() runs 7 recovery attempts:
    1. Raw JSON parse
    2. Strip markdown fences (``` blocks)
    3. Escape control characters inside strings
    4. Strip // and /* */ comments
    5. Fix trailing commas
    6. Extract first { } block from surrounding text
    7. Recover truncated JSON (token limit hit mid-response)

  Only if ALL 7 attempts fail → JSONDecodeError raised → pipeline aborts


=============================================================
         COST ESTIMATION
=============================================================

  Pricing (Anthropic API):
  ┌─────────────────────────────┬──────────────┬───────────────┐
  │ Model                       │ Input / 1M   │ Output / 1M   │
  ├─────────────────────────────┼──────────────┼───────────────┤
  │ claude-sonnet-4-6           │ $3.00        │ $15.00        │
  │ claude-haiku-4-5-20251001   │ $0.80        │ $4.00         │
  └─────────────────────────────┴──────────────┴───────────────┘

  Per Request Estimate:
  ┌──────────────────────────────────┬────────────────────────┐
  │ Scenario                         │ Estimated Cost         │
  ├──────────────────────────────────┼────────────────────────┤
  │ Mode 1 — Jina works (best case)  │ ~$0.14 / request       │
  │ Mode 1 — Playwright fallback     │ ~$0.14 + server compute│
  │ Mode 2 — Blueprint generation    │ ~$0.25 / request       │
  └──────────────────────────────────┴────────────────────────┘

  Monthly at 1,000 requests/day (50/50 split):
  ┌──────────────────────────────────┬────────────────────────┐
  │ Mode 1 (500 req/day = 15k/month) │ ~$2,100 / month        │
  │ Mode 2 (500 req/day = 15k/month) │ ~$3,750 / month        │
  │ TOTAL ESTIMATED LLM COST         │ ~$5,850 / month        │
  └──────────────────────────────────┴────────────────────────┘


=============================================================
         END OF DOCUMENT
=============================================================
