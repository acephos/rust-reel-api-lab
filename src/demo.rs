//! Optional study UI. The five challenge routes work with this module disabled.
use std::path::PathBuf;

pub struct Demo {
    config: Vec<u8>,
    proof: Option<PathBuf>,
}

impl Demo {
    pub fn from_env() -> Option<Self> {
        let path = std::env::var_os("DEMO_CONFIG_PATH")?;
        let config = std::fs::read(path).expect("read DEMO_CONFIG_PATH");
        let value: serde_json::Value = serde_json::from_slice(&config).expect("demo config JSON");
        assert!(value["token"].is_string() && value["username"].is_string());
        Some(Self {
            config,
            proof: std::env::var_os("DEMO_PROOF_PATH").map(PathBuf::from),
        })
    }

    pub fn serve(&self, path: &str, out: &mut Vec<u8>) -> Option<u16> {
        match path {
            "/" => out.extend_from_slice(include_bytes!("../web/demo.html")),
            "/demo/config" => out.extend_from_slice(&self.config),
            "/demo/proof" => {
                // Reload the published report so a running demo gains the result
                // after a benchmark. No API/database query data is cached here.
                let report = self.proof.as_ref().and_then(|p| std::fs::read(p).ok());
                if let Some(report) = report {
                    out.extend_from_slice(&report);
                } else {
                    out.extend_from_slice(br#"{"status":"pending","notes":["Measurements are being collected on this machine."]}"#);
                }
            }
            _ => return None,
        }
        Some(200)
    }
}

pub fn content_type(frame: &crate::Frame<'_>, status: u16) -> &'static [u8] {
    if status == 200 && frame.path.split('?').next() == Some("/") {
        b"text/html; charset=utf-8"
    } else {
        b"application/json"
    }
}
