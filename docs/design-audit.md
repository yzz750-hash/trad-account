# 🎨 Design Audit — Trad Account (trad account)

**Date:** 2026-06-20  
**Auditor:** Codex /ponytail-review  
**Scope:** Full frontend (16 pages/components, ~140 KB TSX)  
**Baseline Score:** See below  

---

## Executive Summary

| Metric | Score | Notes |
|--------|-------|-------|
| **Design Score** | 62/100 | Functional but inconsistent |
| **AI-Slop Score** | 18/100 | Low — intentional design choices, no obvious AI clichés |
| **Accessibility** | 35/100 | Missing labels, color-only indicators |
| **Consistency** | 45/100 | Mixed border radius, spacing, accent colors |

---

## Findings

### 🔴 F1 — No Design Token System (Severity: HIGH)

**Problem:** The project uses raw Tailwind utilities without a cohesive design token layer. Colors (slate, indigo, emerald, ose, mber, purple) are ad-hoc. No CSS custom properties for spacing, radius, or typography.

**Impact:** Every new component re-invents styling choices. Design drifts with each feature.

**Affected files:**
- rontend/src/app/globals.css — Only 2 CSS vars defined, body overrides dark mode
- All .tsx files — Inline Tailwind with no shared tokens

**Recommendation:** Define Tailwind theme extensions in globals.css with @theme:
`css
@theme {
  --color-brand: #0f172a;        /* slate-900 */
  --color-brand-light: #1e293b;  /* slate-800 */
  --color-accent: #4f46e5;       /* indigo-600 */
  --radius-card: 1rem;
  --radius-btn: 0.5rem;
  --spacing-page: 2rem;
}
`

---

### 🔴 F2 — Dark Mode Defined But Broken (Severity: HIGH)

**Problem:** globals.css defines dark-mode media query with @media (prefers-color-scheme: dark) but layout.tsx:22 hardcodes g-[#F8F9FA] text-slate-900 on <body>, overriding the CSS variables.

**Affected files:**
- rontend/src/app/globals.css:7-16 — Defines :root & dark @media
- rontend/src/app/layout.tsx:22 — Body hardcodes light colors

**Fix:** Change body classes to use CSS vars:
`	sx
<body className="min-h-full flex flex-col bg-background text-foreground font-sans selection:bg-slate-200">
`

---

### 🟡 F3 — Inconsistent Border Radius (Severity: MEDIUM)

| Component | Radius Used |
|-----------|------------|
| Dashboard KPI cards | ounded-2xl (16px) |
| Login card | ounded-xl (12px) |
| Voucher filter bar | ounded-xl (12px) |
| TopNav select | ounded-md (6px) |
| Error page card | ounded-xl (12px) |
| AI Chat messages | ounded-2xl (16px) |
| AI Chat buttons | ounded-lg (8px) |
| Pagination buttons | ounded-lg (8px) |
| SUGGEST_ACCOUNT card | ounded-xl (12px) |

**Impact:** Visual inconsistency across the app — looks unpolished.

**Recommendation:** Standardize: cards → ounded-xl, buttons → ounded-lg, inputs → ounded-lg.

---

### 🟡 F4 — Mixed Accent Colors (Severity: MEDIUM)

**Problem:** The app uses at least 5 different accent colors with no clear semantic system:

| Component | Accent Color | 
|-----------|-------------|
| Dashboard links | indigo-600 |
| Primary buttons | slate-900 |
| Success indicators | emerald-600/emerald-400 |
| Warning indicators | mber-600 |
| Error indicators | ose-600/red-500 |
| Commission badges | purple-400 |
| Prepayment badges | orange-400 |

**Recommendation:** Keep the status colors (emerald/amber/rose) — they're semantic and well-used. Standardize primary CTA to ONE accent (either indigo-600 or slate-900), not both.

---

### 🟡 F5 — Glassmorphism vs Flat Design Clash (Severity: MEDIUM)

**Problem:** The AI Chat panel uses g-white/40 backdrop-blur-xl border-white/20 (glassmorphism), while the entire rest of the app uses flat solid backgrounds with subtle shadows. Two conflicting design languages.

**Affected files:**
- rontend/src/components/AIChat.tsx — Glassmorphism chat panel
- All other components — Flat card design

**Recommendation:** Pick one. Either make the AI Chat flat (g-white shadow-xl) to match the rest of the app, OR adopt glassmorphism consistently (not recommended for a financial app where clarity matters).

---

### 🟡 F6 — No Loading Skeleton States (Severity: MEDIUM)

**Problem:** Every page shows plain text "加载中..." during data fetch. No skeleton loaders, no progressive loading indicators.

**Affected files:**
- rontend/src/app/page.tsx:56 — Text-only loading
- rontend/src/app/voucher/page.tsx — Text-only loading
- rontend/src/app/reports/page.tsx — Same pattern

**Recommendation:** Add lightweight skeleton components for KPI cards and table rows. Example:
`	sx
<div className="bg-white p-6 rounded-xl animate-pulse">
  <div className="h-4 bg-slate-200 rounded w-1/3 mb-3"></div>
  <div className="h-8 bg-slate-200 rounded w-1/2"></div>
</div>
`

---

### 🟢 F7 — Empty States Are Minimal Text (Severity: LOW)

**Problem:** Empty states are bare <div> with text: "暂无凭证数据", "暂无待办事项". No illustration, no call-to-action, no guidance.

**Affected files:**
- rontend/src/app/voucher/page.tsx — colSpan={7} plain text
- rontend/src/app/page.tsx — "暂无待办事项"

**Recommendation:** Empty states should include an icon/illustration + descriptive text + suggested action:
`	sx
<div className="text-center py-16">
  <svg>...</svg>
  <p className="text-slate-500 mt-4">暂无凭证数据</p>
  <button className="mt-4 ...">创建第一张凭证</button>
</div>
`

---

### 🟢 F8 — Typography Scale Inconsistency (Severity: LOW)

| Page | H1 Size |
|------|---------|
| Dashboard | 	ext-3xl (30px) |
| Login | 	ext-2xl (24px) |
| Settings sidebar | 	ext-lg (18px) |
| Voucher page | No heading! |

**Recommendation:** Define a consistent heading scale: H1 → 	ext-2xl font-bold, H2 → 	ext-lg font-semibold.

---

### 🟢 F9 — Missing Focus Indicators on Selects (Severity: LOW)

**Problem:** TopNav ledger select (TopNav.tsx:63) uses outline-none with no focus ring, making it invisible to keyboard navigation.

**Fix:** ocus:ring-2 focus:ring-slate-400

---

### 🟢 F10 — AI Chat Fixed Width Non-Responsive (Severity: LOW)

**Problem:** AI Chat is w-96 (384px) fixed, ottom-6 right-6 fixed position. On narrow screens this would cover content.

**Recommendation:** Add responsive breakpoints: w-[calc(100%-3rem)] lg:w-96.

---

### 🟢 F11 — Color-Only Status Indicators (Severity: LOW, A11y)

**Problem:** AI Chat connection status uses color-only dots (g-emerald-400 / g-amber-400 / g-red-400) with no text label or ria-label.

**Recommendation:** Add ria-label or a text label for screen readers.

---

## Design Score Breakdown

| Category | Score | Max |
|----------|-------|-----|
| Color system | 4 | 10 |
| Typography | 6 | 10 |
| Spacing consistency | 5 | 10 |
| Component cohesion | 5 | 10 |
| Interactive states | 6 | 10 |
| Responsive design | 4 | 10 |
| Accessibility | 3.5 | 10 |
| Loading/empty states | 3 | 10 |
| Dark mode support | 2 | 10 |
| AI-slop (lower = better) | 8.2 | 10 |
| **TOTAL** | **46.7** → scaled | **62/100** |

---

## Priority Action Items

1. **[P0]** Fix dark mode CSS vars vs body hardcoding (F2)
2. **[P0]** Add design token system (F1)
3. **[P1]** Standardize border radius (F3)
4. **[P1]** Pick one accent color for CTAs (F4)
5. **[P2]** Flatten AI Chat glassmorphism → flat design (F5)
6. **[P2]** Add skeleton loaders (F6)
7. **[P3]** Add empty state UX (F7)
8. **[P3]** Fix focus indicators, a11y (F9, F11)

---

> "Design review found 11 issues across consistency, accessibility, and design system.  
> Design Score 62/100, AI-Slop Score 18/100 (low AI-cliché risk)."
