//! The error taxonomy, which is also the exit-code taxonomy and the output
//! format.
//!
//! Conclusion 2 of the masked-generation experiment ("lookup misses are data,
//! not errors") is the reason this module exists as a first-class thing rather
//! than as `Box<dyn Error>` plus `eprintln!`. A consulting layer has to be able
//! to tell *a hash that is not here* from *a hash whose bytes are wrong* from
//! *the disk is broken*, and to tell them apart from a shell script, without
//! parsing prose. So every failure has:
//!
//! * a stable `error` class string,
//! * a stable process exit code,
//! * a one-line JSON rendering on **stdout** — the same channel as success,
//!   because a caller that pipes stdout into a JSON reader should not have to
//!   special-case failure.
//!
//! Human prose goes to stderr, and only under `--verbose`.

use std::fmt;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

/// Exit codes. Chosen once, and part of the CLI's contract with the harness.
///
/// `2` is left to `clap` for usage errors, which is where it puts them by
/// default; the store never returns 2 itself.
pub mod exit {
    /// Everything worked.
    pub const OK: i32 = 0;
    /// The store or the filesystem under it is unusable.
    pub const STORE: i32 = 1;
    /// A malformed hash on the command line — a usage error about a value.
    pub const USAGE: i32 = 2;
    /// The hash is well formed and simply is not here. A *miss*, not a fault.
    pub const NOT_FOUND: i32 = 3;
    /// Something on disk does not hash to what it claims. `fsck` returns this.
    pub const INTEGRITY: i32 = 4;
    /// The admission oracle refused the object.
    pub const REFUSED: i32 = 5;
    /// The object is here, but this query does not apply to its kind.
    pub const NOT_APPLICABLE: i32 = 6;
}

#[derive(Debug)]
pub enum StoreError {
    /// The filesystem said no.
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    /// The directory is not a store, or is a store this binary cannot read.
    Layout { detail: String },
    /// A well-formed hash with nothing behind it. The typed miss.
    NotFound { hash: String },
    /// Bytes on disk disagree with the name they are filed under, an index row
    /// disagrees with the sidecars it is derived from, or a sidecar disagrees
    /// with its own hash field.
    Integrity { hash: String, detail: String },
    /// A file that should be JSON in a known shape is not.
    Malformed { path: PathBuf, detail: String },
    /// The oracle refused, and this carries the refusing layer's own class.
    Refused {
        layer: String,
        error_class: String,
        message: String,
    },
    /// The object exists but the query does not apply to it — asking a data
    /// declaration for the type a `ref` to it would have, for instance.
    NotApplicable {
        hash: String,
        kind: String,
        detail: String,
    },
    /// A hash that is not 64 lowercase hex digits.
    BadHash { text: String, detail: String },
    /// The oracle could not be run at all (as opposed to running and refusing).
    Oracle { detail: String },
}

impl StoreError {
    pub fn io(path: impl AsRef<Path>, source: std::io::Error) -> Self {
        StoreError::Io {
            path: path.as_ref().to_path_buf(),
            source,
        }
    }

    pub fn malformed(path: impl AsRef<Path>, detail: impl Into<String>) -> Self {
        StoreError::Malformed {
            path: path.as_ref().to_path_buf(),
            detail: detail.into(),
        }
    }

    /// The stable, greppable class name. Callers branch on this.
    pub fn class(&self) -> &'static str {
        match self {
            StoreError::Io { .. } => "io",
            StoreError::Layout { .. } => "layout",
            StoreError::NotFound { .. } => "not_found",
            StoreError::Integrity { .. } => "integrity",
            StoreError::Malformed { .. } => "malformed",
            StoreError::Refused { .. } => "refused",
            StoreError::NotApplicable { .. } => "not_applicable",
            StoreError::BadHash { .. } => "bad_hash",
            StoreError::Oracle { .. } => "oracle",
        }
    }

    pub fn exit_code(&self) -> i32 {
        match self {
            StoreError::Io { .. } | StoreError::Layout { .. } | StoreError::Oracle { .. } => {
                exit::STORE
            }
            StoreError::NotFound { .. } => exit::NOT_FOUND,
            StoreError::Integrity { .. } | StoreError::Malformed { .. } => exit::INTEGRITY,
            StoreError::Refused { .. } => exit::REFUSED,
            StoreError::NotApplicable { .. } => exit::NOT_APPLICABLE,
            StoreError::BadHash { .. } => exit::USAGE,
        }
    }

    /// The one-line JSON body. Every variant names the thing it failed on —
    /// a miss without the hash in it is not data, it is a complaint.
    pub fn to_json(&self) -> Value {
        let mut value = match self {
            StoreError::Io { path, source } => {
                json!({ "path": path.display().to_string(), "message": source.to_string() })
            }
            StoreError::Layout { detail } => json!({ "message": detail }),
            StoreError::NotFound { hash } => {
                json!({ "hash": hash, "message": "no object with that hash" })
            }
            StoreError::Integrity { hash, detail } => json!({ "hash": hash, "message": detail }),
            StoreError::Malformed { path, detail } => {
                json!({ "path": path.display().to_string(), "message": detail })
            }
            StoreError::Refused {
                layer,
                error_class,
                message,
            } => {
                json!({ "layer": layer, "error_class": error_class, "message": message })
            }
            StoreError::NotApplicable { hash, kind, detail } => {
                json!({ "hash": hash, "kind": kind, "message": detail })
            }
            StoreError::BadHash { text, detail } => json!({ "hash": text, "message": detail }),
            StoreError::Oracle { detail } => json!({ "message": detail }),
        };
        value["error"] = json!(self.class());
        value
    }
}

impl fmt::Display for StoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let body = self.to_json();
        let message = body.get("message").and_then(Value::as_str).unwrap_or("");
        write!(formatter, "{}: {message}", self.class())
    }
}

impl std::error::Error for StoreError {}

pub type Result<T> = std::result::Result<T, StoreError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_miss_names_the_hash_and_exits_three() {
        let error = StoreError::NotFound {
            hash: "ab".repeat(32),
        };
        assert_eq!(error.exit_code(), exit::NOT_FOUND);
        let body = error.to_json();
        assert_eq!(body["error"], "not_found");
        assert_eq!(body["hash"], "ab".repeat(32));
    }

    #[test]
    fn corruption_is_its_own_class_and_code() {
        let error = StoreError::Integrity {
            hash: "00".repeat(32),
            detail: "bytes hash to …".into(),
        };
        assert_eq!(error.class(), "integrity");
        assert_eq!(error.exit_code(), exit::INTEGRITY);
        assert_ne!(
            error.exit_code(),
            StoreError::NotFound {
                hash: String::new()
            }
            .exit_code()
        );
    }

    #[test]
    fn every_error_body_carries_its_class() {
        let errors = [
            StoreError::Layout { detail: "x".into() },
            StoreError::Refused {
                layer: "scope".into(),
                error_class: "ScopeError".into(),
                message: "x".into(),
            },
            StoreError::BadHash {
                text: "zz".into(),
                detail: "x".into(),
            },
            StoreError::Oracle { detail: "x".into() },
        ];
        for error in errors {
            assert_eq!(error.to_json()["error"], error.class());
        }
    }
}
