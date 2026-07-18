# PRODUCT.md — Azure AI Continuous Assurance

## Register

**product** — design serves the assurance workbench. Users are in a task (review controls, evidence, findings, runs), not browsing a marketing page.

## Platform

**web** — Vite + React SPA (`apps/console`), Fluent UI React v9, local hash routing.

## Users

Primary: portfolio reviewers, assessors, and security/compliance practitioners evaluating a synthetic continuous-assurance demo.

Secondary: interviewers or hiring managers scanning the console for clarity and evidence integrity.

## Purpose

Make signed assessment posture, control conclusions, evidence health, findings/risks, and retest chains inspectable without implying certification or independent audit.

## Positioning

Evidence-first continuous internal-assurance simulation for a small Azure-hosted AI policy assistant — traceable from criteria through retest, with human reviewer authority preserved.

## Brand personality

Credible · Precise · Calm Azure enterprise

## Anti-references

- Purple-gradient SaaS landing pages
- Neon “cybersecurity” dashboards
- Playful consumer app chrome
- Generic AI-slop cards (Inter + purple + pill badges everywhere)
- Replacing Fluent patterns with shadcn/Tailwind unless explicitly migrating the stack

## Accessibility

- Respect `prefers-reduced-motion`
- Keep visible focus rings
- Prefer accessible names on icon buttons
- Do not rely on color alone for PASS/FAIL/severity

## Design principles

1. Clarity of assurance semantics over decorative novelty.
2. Reuse Fluent components and existing CSS tokens before inventing new ones.
3. Previews may interrupt navigation; they must never invent control verdicts.
4. Motion is feedback (dialogs, state change), not page choreography.
5. Public/demo modes must remain non-mutating and clearly labeled.
