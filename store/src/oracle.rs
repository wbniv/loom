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

    /// Emit the default policy object — §5.3.2's three-byte base case — so
    /// `init` can preload it. The bytes are a SPEC literal, but the sidecar is
    /// the oracle's statement of record like every other sidecar, so the store
    /// asks for it rather than minting one and inventing contract versions.
    pub fn default_policy(&self, out: &Path) -> Result<Vec<Emitted>> {
        self.emitted(self.run(&[
            "policy".to_string(),
            "--default".to_string(),
            "--out".to_string(),
            out.display().to_string(),
        ])?)
    }

    /// Emit one policy object from a JSON-mirrored policy map.
    pub fn policy(
        &self,
        source: &Path,
        out: &Path,
        name: Option<&str>,
        sequence: u64,
    ) -> Result<Vec<Emitted>> {
        let mut arguments = vec![
            "policy".to_string(),
            "--out".to_string(),
            out.display().to_string(),
            "--sequence".to_string(),
            sequence.to_string(),
        ];
        if let Some(name) = name {
            arguments.push("--name".to_string());
            arguments.push(name.to_string());
        }
        arguments.push(source.display().to_string());
        self.emitted(self.run(&arguments)?)
    }

    /// Run §5.3.2 admission over a binding request. A refusal comes back as
    /// `StoreError::Refused` carrying the rule number in its message, exactly
    /// as a validator refusal does — admission is a validator here.
    pub fn bind(&self, request: &Path) -> Result<Value> {
        self.run(&["bind".to_string(), request.display().to_string()])
    }

    /// Apply §5.3.1 keys 5 and 6 to a lease request, returning the governing
    /// policy's hash for the lease event to record.
    ///
    /// A refusal becomes `StoreError::Lease` rather than `Refused`, because a
    /// caller polling for a lease (§5.3.3 has no queue) has to tell "not your
    /// namespace" from "try again later", and the exit code is how it does.
    pub fn lease_check(&self, request: &Path) -> Result<Value> {
        match self.invoke(&["lease".to_string(), request.display().to_string()])? {
            Ok(value) => Ok(value),
            Err(body) => Err(StoreError::Lease {
                reason: match body.get("reason").and_then(Value::as_str) {
                    Some(reason) => reason.to_string(),
                    // The oracle refused for a reason outside §5.3.3's lease
                    // vocabulary — a malformed policy on the chain, say. It is
                    // still a refusal of this acquisition, so it keeps the
                    // lease exit code and says honestly why.
                    None => "policy".to_string(),
                },
                detail: field(&body, "message"),
                context: Value::Object(serde_json::Map::new()),
            }),
        }
    }

    fn emitted(&self, value: Value) -> Result<Vec<Emitted>> {
        let objects = value.get("objects").cloned().unwrap_or(Value::Null);
        serde_json::from_value(objects).map_err(|error| StoreError::Oracle {
            detail: format!("unreadable manifest: {error}"),
        })
    }

    /// Run the oracle and separate its three outcomes: it worked
    /// (`Ok(Ok(body))`), it *refused* (`Ok(Err(body))` — the oracle working,
    /// not failing), or it could not run at all (`Err`).
    ///
    /// The refusal body comes back whole rather than pre-narrowed, because two
    /// callers want different fields out of it: `run` wants the v0 seam's
    /// layer/class/message, and `lease_check` wants §5.3.3's `reason`.
    fn invoke(&self, arguments: &[String]) -> Result<std::result::Result<Value, Value>> {
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
            return parsed.map(Ok).ok_or_else(|| StoreError::Oracle {
                detail: format!("oracle produced no JSON line (stdout: {stdout:?})"),
            });
        }
        if let Some(body) = parsed.filter(|body| body.get("error").is_some()) {
            return Ok(Err(body));
        }
        Err(StoreError::Oracle {
            detail: format!(
                "oracle exited {}: {}",
                output.status.code().unwrap_or(-1),
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        })
    }

    fn run(&self, arguments: &[String]) -> Result<Value> {
        // A refusal is the oracle working, not failing: it printed a typed
        // rejection and exited 5. Pass the layer's own class straight through.
        self.invoke(arguments)?.map_err(|body| StoreError::Refused {
            layer: field(&body, "layer"),
            error_class: field(&body, "error_class"),
            message: field(&body, "message"),
        })
    }
}

fn field(body: &Value, key: &str) -> String {
    body.get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}
