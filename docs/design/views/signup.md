# Signup

> **Tier 2** · spec v0 · 2026-06-01 · `signup.md`
> Pre-session view — same chrome as [Login](login.md) (no dashboard shell). Inherits global design tokens only.
> Backed by PLAN.md §9 (2026-06-01) — first-class email + password auth.

## Purpose

Account creation for a new operator. Email + password (display name optional). On success the new account is signed in immediately (the route handler sets the session cookie) and dropped at the dashboard.

## Layout

```
                          Cascadia                                              
                       OPERATOR DASHBOARD                                       
                                                                                
            ┌──────────────────────────────────────────────┐                   
            │  Create your account                           │                   
            │  Set up access to the Cascadia operator …      │                   
            │                                                │                   
            │  Email                                         │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ you@company.com                          │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │  Display name (optional)                       │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ Chris King                               │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │  Password                                      │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ At least 8 characters                    │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │  Confirm password                              │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │ ••••••••                                  │ │                   
            │  └──────────────────────────────────────────┘ │                   
            │  ┌──────────────────────────────────────────┐ │                   
            │  │            Create account                │ │  ← accent button   
            │  └──────────────────────────────────────────┘ │                   
            │     Already have an account? Sign in           │                   
            └──────────────────────────────────────────────┘                   
```

## Sections

Same chrome as Login. Form adds: optional display-name field and a confirm-password field.

## Components

`AuthScreen` + `AuthForm` (mode=`signup`). Same input/button idiom as Login.

## States

- **Default** — empty, email autofocused.
- **Password too short** — client-side guard: "Password must be at least 8 characters." (no round-trip).
- **Passwords don't match** — client-side guard: "Passwords don't match."
- **Email already registered** — server 409 → "an account with this email already exists." (Signup intentionally reveals this; login never does — see PLAN.md §9.)
- **Submitting / Service unreachable** — same as Login.

## Data / behavior

- POSTs to `/api/auth/signup` (Next route → dashboard-api `POST /api/auth/signup`, which Argon2id-hashes the password and mints a session). 201 → cookie set → redirect to `?next` (or `/`).
- Validation contract (email shape, 8–128 char password) lives in `services/dashboard-api/cascadia_dashboard/auth/types.py`.
