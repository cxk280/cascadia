//! Prometheus metrics registry.
//!
//! The full cascade-routing metrics arrive in Phase 2. Phase 1 ships the
//! baseline: request counter and end-to-end latency histogram, both labeled
//! by upstream provider and status.

use prometheus::{
    register_histogram_vec_with_registry, register_int_counter_vec_with_registry, HistogramVec,
    IntCounterVec, Registry, TextEncoder,
};

pub struct Metrics {
    pub registry: Registry,
    pub requests_total: IntCounterVec,
    pub request_duration_seconds: HistogramVec,
}

impl Metrics {
    pub fn new() -> anyhow::Result<Self> {
        let registry = Registry::new();

        let requests_total = register_int_counter_vec_with_registry!(
            "cascadia_proxy_requests_total",
            "Total HTTP requests handled by the proxy, labeled by route, provider, and status.",
            &["route", "provider", "status"],
            registry
        )?;

        // Buckets tuned for LLM call latencies: 1 ms .. 60 s.
        let request_duration_seconds = register_histogram_vec_with_registry!(
            "cascadia_proxy_request_duration_seconds",
            "End-to-end request duration, labeled by route and provider.",
            &["route", "provider"],
            vec![0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
            registry
        )?;

        // Pre-touch the metric families so /metrics emits HELP/TYPE lines
        // and zero-valued samples even before the first request. Some
        // Prometheus scrapers treat an empty exposition as a parse error,
        // and operators wiring alerts against a fresh deployment need the
        // series names to exist immediately.
        for route in ["chat_completions", "chat_completions_stream"] {
            for provider in ["openai", "anthropic", "groq", "xai", "unknown"] {
                for status in ["ok", "upstream_error", "error"] {
                    let _ = requests_total
                        .with_label_values(&[route, provider, status]);
                }
                let _ = request_duration_seconds
                    .with_label_values(&[route, provider]);
            }
        }

        Ok(Self {
            registry,
            requests_total,
            request_duration_seconds,
        })
    }

    /// Render the registry in Prometheus text exposition format.
    pub fn render(&self) -> anyhow::Result<String> {
        let encoder = TextEncoder::new();
        let metric_families = self.registry.gather();
        Ok(encoder.encode_to_string(&metric_families)?)
    }
}
