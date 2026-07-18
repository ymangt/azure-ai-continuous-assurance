# AI Tool Use Standard

- Policy ID: POL-016
- Owner: Application Security
- Classification: Internal (synthetic)
- Version: 1.1
- Effective: 2026-03-10

## 1. Authorization

The server authorizes every tool request independently of model output. Tool identities receive only the permissions required for the declared action, and arguments are schema validated.

## 2. Confirmation

A consequential tool requires a short-lived, single-use server-issued confirmation bound to actor, session, tool, and argument digest. Missing, expired, replayed, cancelled, actor-mismatched, or argument-mismatched confirmation denies execution.

## 3. Evidence

Log evaluation ID, tool name, authorization decision, confirmation state, outcome, and sanitized result. Never log the access token or confirmation token.
