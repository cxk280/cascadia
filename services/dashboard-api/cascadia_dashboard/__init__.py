"""Cascadia dashboard read-API.

Phase 6 deliverable. Read-only by design: the proxy writes events, the
judge worker writes scores, the policy controller writes thresholds. This
service exposes those tables to the Next.js dashboard and nothing else.
"""
