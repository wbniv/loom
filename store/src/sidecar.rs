//! The oracle's sidecar, as the store sees it.
//!
//! The store parses this to build index rows and to answer `type`/`deps`, and
//! it re-emits it verbatim in `export-resolver`. What it never does is
//! *rewrite* it: the bytes the oracle produced are the bytes stored, and their
//! SHA-256 goes into the index so `fsck` can tell that a sidecar changed under
//! it. Re-serializing here would make that digest a digest of the store's
//! opinion of the sidecar rather than of the oracle's statement, and the whole
//! point of the seam is that the oracle's statement is the record.
//!
//! Unknown fields are preserved (`extra`) rather than dropped, so an oracle that
//! learns to say more does not silently lose it on the way through a store that
//! has not learned to read it yet.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::{Result, StoreError};
use crate::hash::ObjectHash;

/// The sidecar schema version this binary understands.
pub const SCHEMA: u32 = 1;

pub const KIND_DEFINITION: &str = "definition";
pub const KIND_DATA: &str = "data";
pub const KIND_ABILITY: &str = "ability";
pub const KIND_EXTERN: &str = "extern";

pub const KINDS: [&str; 4] = [KIND_DEFINITION, KIND_DATA, KIND_ABILITY, KIND_EXTERN];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Sidecar {
    pub schema: u32,
    pub hash: String,
    pub kind: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub type_surface: Option<String>,
    #[serde(default)]
    pub deps: Vec<String>,
    #[serde(default)]
    pub surface: Option<String>,
    #[serde(default)]
    pub object: Option<Value>,
    #[serde(default)]
    pub spec: Option<String>,
    #[serde(default)]
    pub sequence: u64,
    #[serde(default)]
    pub provenance: Value,
    #[serde(default)]
    pub validation: Value,
    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}

impl Sidecar {
    /// Parse and check everything the store is able to check about a sidecar
    /// without understanding object bytes: schema, kind, and that its `deps`
    /// and `hash` are well-formed hashes.
    pub fn parse(bytes: &[u8], path: &std::path::Path) -> Result<Self> {
        let sidecar: Sidecar = serde_json::from_slice(bytes)
            .map_err(|error| StoreError::malformed(path, error.to_string()))?;
        if sidecar.schema != SCHEMA {
            return Err(StoreError::malformed(
                path,
                format!("sidecar schema {} is not {SCHEMA}", sidecar.schema),
            ));
        }
        if !KINDS.contains(&sidecar.kind.as_str()) {
            return Err(StoreError::malformed(
                path,
                format!("unknown object kind {:?}", sidecar.kind),
            ));
        }
        ObjectHash::parse(&sidecar.hash)?;
        for dependency in &sidecar.deps {
            ObjectHash::parse(dependency)?;
        }
        Ok(sidecar)
    }

    /// The hash this sidecar claims to describe.
    pub fn object_hash(&self) -> Result<ObjectHash> {
        ObjectHash::parse(&self.hash)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn minimal(kind: &str) -> String {
        format!(
            r#"{{"schema":1,"hash":"{}","kind":"{kind}","deps":[],"sequence":0}}"#,
            "ab".repeat(32)
        )
    }

    #[test]
    fn parses_a_minimal_sidecar_of_every_kind() {
        for kind in KINDS {
            let sidecar = Sidecar::parse(minimal(kind).as_bytes(), Path::new("x")).unwrap();
            assert_eq!(sidecar.kind, kind);
        }
    }

    #[test]
    fn refuses_an_unknown_kind_and_an_unknown_schema() {
        assert_eq!(
            Sidecar::parse(minimal("wombat").as_bytes(), Path::new("x"))
                .unwrap_err()
                .class(),
            "malformed"
        );
        let future = minimal("definition").replace("\"schema\":1", "\"schema\":2");
        assert_eq!(
            Sidecar::parse(future.as_bytes(), Path::new("x"))
                .unwrap_err()
                .class(),
            "malformed"
        );
    }

    #[test]
    fn keeps_fields_it_does_not_know_about() {
        let text = minimal("definition").replace("\"sequence\":0", "\"sequence\":0,\"future\":7");
        let sidecar = Sidecar::parse(text.as_bytes(), Path::new("x")).unwrap();
        assert_eq!(sidecar.extra["future"], 7);
    }

    #[test]
    fn refuses_a_malformed_dependency_edge() {
        let text = minimal("definition").replace("\"deps\":[]", "\"deps\":[\"nope\"]");
        assert_eq!(
            Sidecar::parse(text.as_bytes(), Path::new("x"))
                .unwrap_err()
                .class(),
            "bad_hash"
        );
    }
}
