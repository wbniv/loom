//! Running the Python admission oracle.
//!
//! R1 puts Rust-side validation out of scope and R3 says why: re-deriving the
//! seven validation contracts in Rust is Track P's job, gated by a differential
//! harness that does not exist yet, and doing it here by accident would create
//! a second opinion with no referee. So `admit` is a subprocess call, and the
//! seam is deliberately narrow — the oracle writes two files and prints one
//! line of JSON, and a refusal comes back carrying the refusing layer's own
//! error class rather than something this side invented.
//!
//! The oracle is configurable (`--python`, `--prototype`) because the store
//! binary and the prototype tree are separately relocatable, and hardcoding a
//! relative path from the binary to a sibling checkout is the kind of thing
//! that works until the first time anything moves.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Deserialize;
use serde_json::Value;

use crate::error::{Result, StoreError};

/// One object the oracle emitted, as file names inside the output directory.
#[derive(Debug, Clone, Deserialize)]
pub struct Emitted {
    pub hash: String,
    pub kind: String,
    pub name: Option<String>,
    pub sequence: u64,
    pub object: String,
    pub sidecar: String,
}

#[derive(Debug, Clone)]
pub struct Oracle {
    pub python: String,
    pub prototype: PathBuf,
}

impl Oracle {
    pub fn new(python: impl Into<String>, prototype: impl AsRef<Path>) -> Self {
        Oracle {
            python: python.into(),
            prototype: prototype.as_ref().to_path_buf(),
        }
    }

    /// The contract-version map, for `init` to record.
    pub fn contracts(&self) -> Result<serde_json::Map<String, Value>> {
        let value = self.run(&["contracts".to_string()])?;
        match value {
            Value::Object(map) => Ok(map),
            other => Err(StoreError::Oracle {
                detail: format!("expected a contract map, got {other}"),
            }),
        }
    }

    /// Emit the whole pinned corpus into `out`, in seeding order.
    pub fn corpus(&self, out: &Path) -> Result<Vec<Emitted>> {
        let arguments = vec![
            "corpus".to_string(),
            "--out".to_string(),
            out.display().to_string(),
        ];
        self.emitted(self.run(&arguments)?)
    }

    /// Emit one definition source file, validated against `resolver` when one
    /// is supplied. Without a resolver the oracle falls back to the pinned
    /// corpus registry, which is the bootstrap case and nothing else.
    pub fn emit(
        &self,
        source: &Path,
        out: &Path,
        resolver: Option<&Path>,
        name: Option<&str>,
        spec: Option<&str>,
        sequence: u64,
    ) -> Result<Vec<Emitted>> {
        let mut arguments = vec![
            "emit".to_string(),
            "--out".to_string(),
            out.display().to_string(),
            "--sequence".to_string(),
            sequence.to_string(),
        ];
        if let Some(resolver) = resolver {
            arguments.push("--resolver".to_string());
            arguments.push(resolver.display().to_string());
        }
        if let Some(name) = name {
            arguments.push("--name".to_string());
            arguments.push(name.to_string());
        }
        if let Some(spec) = spec {
            arguments.push("--spec".to_string());
            arguments.push(spec.to_string());
        }
        arguments.push(source.display().to_string());
        self.emitted(self.run(&arguments)?)
    }

    fn emitted(&self, value: Value) -> Result<Vec<Emitted>> {
        let objects = value.get("objects").cloned().unwrap_or(Value::Null);
        serde_json::from_value(objects).map_err(|error| StoreError::Oracle {
            detail: format!("unreadable manifest: {error}"),
        })
    }

    fn run(&self, arguments: &[String]) -> Result<Value> {
        if !self.prototype.is_dir() {
            return Err(StoreError::Oracle {
                detail: format!(
                    "prototype directory {} does not exist",
                    self.prototype.display()
                ),
            });
        }
        let output = Command::new(&self.python)
            .arg("-m")
            .arg("store_admit")
            .args(arguments)
            .current_dir(&self.prototype)
            .output()
            .map_err(|error| StoreError::Oracle {
                detail: format!("could not run {} -m store_admit: {error}", self.python),
            })?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let line = stdout.lines().last().unwrap_or("").trim();
        let parsed: Option<Value> = serde_json::from_str(line).ok();

        if output.status.success() {
            return parsed.ok_or_else(|| StoreError::Oracle {
                detail: format!("oracle produced no JSON line (stdout: {stdout:?})"),
            });
        }

        // A refusal is the oracle working, not failing: it printed a typed
        // rejection and exited 5. Pass the layer's own class straight through.
        if let Some(body) = parsed.as_ref().filter(|body| body.get("error").is_some()) {
            return Err(StoreError::Refused {
                layer: field(body, "layer"),
                error_class: field(body, "error_class"),
                message: field(body, "message"),
            });
        }
        Err(StoreError::Oracle {
            detail: format!(
                "oracle exited {}: {}",
                output.status.code().unwrap_or(-1),
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        })
    }
}

fn field(body: &Value, key: &str) -> String {
    body.get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}
