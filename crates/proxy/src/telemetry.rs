//! Tracing + OpenTelemetry setup.
//!
//! - Always installs a `tracing-subscriber` layer (pretty or JSON) for stdout.
//! - When `CASCADIA_OTLP_ENDPOINT` is set, additionally installs an
//!   OTLP/HTTP exporter so spans flow to a collector (Tempo, Jaeger, etc.).
//!
//! OTel spans are created by:
//! - `tower_http::trace::TraceLayer` on each incoming HTTP request.
//! - `#[tracing::instrument]` on hot-path functions (`forward_chat`, etc.).
//!
//! Shutdown: we don't currently install a SIGTERM hook to flush spans on
//! shutdown. That's an acceptable Phase-1 corner — losing the last batch on
//! restart is fine — and lands when we add graceful shutdown.

use anyhow::Context;
use opentelemetry::{global, KeyValue};
use opentelemetry_otlp::{Protocol, WithExportConfig};
use opentelemetry_sdk::{propagation::TraceContextPropagator, trace::TracerProvider, Resource};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

use crate::config::Config;

pub fn init(config: &Config) -> anyhow::Result<()> {
    let filter = EnvFilter::try_from_default_env()
        .or_else(|_| EnvFilter::try_new(&config.log_level))
        .unwrap_or_else(|_| EnvFilter::new("info"));

    let fmt_layer = if config.log_json {
        tracing_subscriber::fmt::layer()
            .with_target(false)
            .json()
            .flatten_event(true)
            .boxed()
    } else {
        tracing_subscriber::fmt::layer().with_target(false).boxed()
    };

    let registry = tracing_subscriber::registry().with(filter).with(fmt_layer);

    if let Some(endpoint) = &config.otlp_endpoint {
        global::set_text_map_propagator(TraceContextPropagator::new());

        let exporter = opentelemetry_otlp::SpanExporter::builder()
            .with_http()
            .with_endpoint(endpoint.clone())
            .with_protocol(Protocol::HttpBinary)
            .build()
            .context("building OTLP span exporter")?;

        let resource = Resource::new(vec![
            KeyValue::new("service.name", "cascadia-proxy"),
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
        ]);

        let provider = TracerProvider::builder()
            .with_batch_exporter(exporter, opentelemetry_sdk::runtime::Tokio)
            .with_resource(resource)
            .build();

        let tracer = opentelemetry::trace::TracerProvider::tracer(&provider, "cascadia-proxy");
        let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
        global::set_tracer_provider(provider);

        registry.with(otel_layer).init();
        tracing::info!(endpoint, "OTLP trace export enabled");
    } else {
        registry.init();
    }

    Ok(())
}
