use std::process::ExitCode;

#[tokio::main]
async fn main() -> ExitCode {
    if let Err(err) = cascadia_proxy::run().await {
        eprintln!("fatal: {err:#}");
        return ExitCode::from(1);
    }
    ExitCode::from(0)
}
