# Login

> **Tier 1** · spec v0 · 2026-06-01 · `login.md`
> Pre-session view — does **not** inherit the [Dashboard shell](dashboard-shell.md) (no sidebar/topbar before a session exists). Inherits the global design tokens only.
> Backed by PLAN.md §9 (2026-06-01) — first-class email + password auth.

## Purpose

The front door to the operator dashboard. Replaces the browser-native HTTP Basic Auth popup the dashboard used to sit behind. An unauthenticated request to any gated route is redirected here with a `?next=` pointer so the user lands back where they were headed after signing in.

## Layout

```
                                                                                
                          Cascadia                                              
                       OPERATOR DASHBOARD                                       
                                                                                
            ┌──────────────────────────────────────────────┐                   
            │  Sign in                                       │                   
            │  Access your Cascadia operator dashboard.      │                   
            │                                                │                   
            │  Email                                         │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ you@company.com                          │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │  Password                                      │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ ••••••••                                  │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │                                                │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │               Sign in                    │ │  ← accent button   
            │  └──────────────────────────────────────────┘ │                   
            │                                                │                   
            │       New to Cascadia? Create an account       │                   
            └──────────────────────────────────────────────┘                   
                                                                                
```

## Sections

1. **Wordmark + "operator dashboard"** — centered above the card, mono wordmark, uppercase tracking-wider subtitle.
2. **Card** — `bg-surface`, `border`, rounded-lg, soft shadow; title + subtitle, then the form.
3. **Form** — email + password inputs (focus ring uses accent), full-width accent "Sign in" button.
4. **Cross-link** — to `/signup`.

## Components

`AuthScreen` (presentational chrome) + `AuthForm` (client, mode=`login`). Inputs reuse the dashboard input idiom (`bg-raised`, `border`, focus:border-accent). Error banner reuses the `accent-danger` tinted box from the calibration onboarding form.

## States

- **Default** — empty, email autofocused.
- **Submitting** — button shows `…`, disabled.
- **Invalid credentials** — generic danger banner: "invalid email or password" (never reveals whether the email exists).
- **Service unreachable** — "Couldn't reach the server. Please try again."
- **Already authenticated** — middleware never routes a valid session here; if reached, the form simply works as a re-login.

## Data / behavior

- POSTs to `/api/auth/login` (Next route handler → dashboard-api). On success the route sets the httpOnly `cascadia_session` cookie; the page never sees the raw token.
- Reads `?next` and redirects there on success, sanitized to internal single-slash paths (open-redirect guard).
- Session model + threat notes: PLAN.md §9 (2026-06-01) and SECURITY.md.
