-- Phase 7.1 surface: record whether the inbound request carried `tools=[]`.
-- The cascade explicitly bypasses escalation on tool-use traffic (mid-loop
-- escalation would diverge into incoherent tool-call sequences). Without this
-- column, the dashboard cannot distinguish a cluster that legitimately ran
-- 0% escalation because it's all tool-use from one that's misconfigured.

ALTER TABLE events ADD COLUMN IF NOT EXISTS tools_present BOOLEAN;
CREATE INDEX IF NOT EXISTS events_tools_present_idx ON events (tools_present);
