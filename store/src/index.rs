//! `index/types.jsonl` — derived, sorted, and re-derivable.
//!
//! Conclusion 3 of the experiment put `reference_type` on the decode hot path
//! inside a per-token budget, so the type lookup must not parse an object. The
//! index is the answer: one line per object carrying the precomputed type
//! surface, the kind, the declared dependency edges and the name, sorted by
//! hash so the file is a function of its contents rather than of its history.
//!
//! Two properties are load-bearing and both are checked by `fsck`:
//!
//! * **Derived.** Deleting the index and rebuilding it from the sidecars must
//!   produce the same bytes. That is what makes the index safe to throw away,
//!   and it is what makes an index that disagrees with the sidecars a
//!   detectable fault rather than a quiet second opinion.
//! * **Covering.** Each row carries the SHA-256 of the sidecar file it was
//!   derived from, so *any* edit to *any* sidecar field — including fields the
//!   store does not interpret, like `spec` — makes the stored index and a fresh
//!   rebuild differ. Without that column, `fsck` could only catch edits to the
//!   handful of fields it happens to index, which would be an integrity check
//!   with a shape nobody could remember.

use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::{Result, StoreError};
use crate::hash::ObjectHash;
use crate::layout::Layout;
use crate::sidecar::Sidecar;

/// One index row. Field order here is the field order on disk — `serde_json`
/// emits struct fields in declaration order — which is part of what makes the
/// file byte-reproducible.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IndexRow {
    pub hash: String,
    pub kind: String,
    /// `provenance.origin` from the sidecar, lifted into the index so the read
    /// API can tell a generated object from a curated one without opening the
    /// sidecar. It is the one provenance field a *query* needs: the corpus loop
    /// plan's guardrail is that generated objects never pass for curated, and a
    /// guardrail nobody can see from `list` is a guardrail nobody checks.
    ///
    /// `None` only for a sidecar with no `provenance.origin` at all, which the
    /// oracle never emits; the store reports what it finds rather than
    /// inventing a default, because "unlabelled" and "curated" must not be the
    /// same answer.
    #[serde(default)]
    pub origin: Option<String>,
    pub name: Option<String>,
    pub type_surface: Option<String>,
    pub deps: Vec<String>,
    pub sequence: u64,
    pub sidecar_sha256: String,
}

impl IndexRow {
    pub fn from_sidecar(sidecar: &Sidecar, sidecar_bytes: &[u8]) -> Self {
        IndexRow {
            hash: sidecar.hash.clone(),
            kind: sidecar.kind.clone(),
            origin: sidecar
                .provenance
                .get("origin")
                .and_then(Value::as_str)
                .map(str::to_string),
            name: sidecar.name.clone(),
            type_surface: sidecar.type_surface.clone(),
            deps: sidecar.deps.clone(),
            sequence: sidecar.sequence,
            sidecar_sha256: ObjectHash::of(sidecar_bytes).to_string(),
        }
    }
}

/// Render rows as the canonical index file: sorted by hash, one JSON object per
/// line, trailing newline.
pub fn render(rows: &mut Vec<IndexRow>) -> Result<Vec<u8>> {
    rows.sort_by(|left, right| left.hash.cmp(&right.hash));
    rows.dedup_by(|left, right| left.hash == right.hash);
    let mut out = Vec::new();
    for row in rows.iter() {
        let line = serde_json::to_vec(row).map_err(|error| StoreError::Layout {
            detail: error.to_string(),
        })?;
        out.extend_from_slice(&line);
        out.push(b'\n');
    }
    Ok(out)
}

/// Read the stored index. A missing file is an empty index, not an error: a
/// store that has been `init`ed and never written to has no index yet, and
/// `fsck` on it should report "no rows" rather than "no file".
pub fn read(layout: &Layout) -> Result<Vec<IndexRow>> {
    let path = layout.index_file();
    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(StoreError::io(&path, error)),
    };
    parse(&bytes, &path)
}

pub fn parse(bytes: &[u8], path: &Path) -> Result<Vec<IndexRow>> {
    let text = std::str::from_utf8(bytes)
        .map_err(|error| StoreError::malformed(path, error.to_string()))?;
    let mut rows = Vec::new();
    for (number, line) in text.lines().enumerate() {
        if line.is_empty() {
            continue;
        }
        let row: IndexRow = serde_json::from_str(line).map_err(|error| {
            StoreError::malformed(path, format!("line {}: {error}", number + 1))
        })?;
        rows.push(row);
    }
    Ok(rows)
}

/// Rebuild every row from the sidecars on disk. This is the definition of what
/// the index *means*; the stored file is a cache of it.
pub fn rebuild(layout: &Layout) -> Result<Vec<IndexRow>> {
    let mut rows = Vec::new();
    for path in sidecar_paths(layout)? {
        let bytes = fs::read(&path).map_err(|error| StoreError::io(&path, error))?;
        let sidecar = Sidecar::parse(&bytes, &path)?;
        rows.push(IndexRow::from_sidecar(&sidecar, &bytes));
    }
    rows.sort_by(|left, right| left.hash.cmp(&right.hash));
    Ok(rows)
}

/// Every sidecar file under `meta/`, in sorted order so a caller never depends
/// on readdir order.
pub fn sidecar_paths(layout: &Layout) -> Result<Vec<std::path::PathBuf>> {
    let meta = layout.meta_dir();
    let mut found = Vec::new();
    let fanouts = match fs::read_dir(&meta) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(found),
        Err(error) => return Err(StoreError::io(&meta, error)),
    };
    for fanout in fanouts {
        let fanout = fanout.map_err(|error| StoreError::io(&meta, error))?;
        if !fanout
            .file_type()
            .map_err(|error| StoreError::io(fanout.path(), error))?
            .is_dir()
        {
            continue;
        }
        let directory = fanout.path();
        for entry in fs::read_dir(&directory).map_err(|error| StoreError::io(&directory, error))? {
            let entry = entry.map_err(|error| StoreError::io(&directory, error))?;
            let path = entry.path();
            if path.extension().and_then(|extension| extension.to_str()) == Some("json") {
                found.push(path);
            }
        }
    }
    found.sort();
    Ok(found)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(hash: &str) -> IndexRow {
        IndexRow {
            hash: hash.to_string(),
            kind: "definition".into(),
            origin: Some("transpiled".into()),
            name: None,
            type_surface: None,
            deps: Vec::new(),
            sequence: 0,
            sidecar_sha256: "0".repeat(64),
        }
    }

    #[test]
    fn render_sorts_by_hash_so_the_file_does_not_depend_on_insertion_order() {
        let mut forward = vec![row(&"aa".repeat(32)), row(&"11".repeat(32))];
        let mut backward = vec![row(&"11".repeat(32)), row(&"aa".repeat(32))];
        assert_eq!(
            render(&mut forward).unwrap(),
            render(&mut backward).unwrap()
        );
        assert!(render(&mut forward)
            .unwrap()
            .starts_with(b"{\"hash\":\"1111"));
    }

    #[test]
    fn render_and_parse_are_inverse() {
        let mut rows = vec![row(&"aa".repeat(32)), row(&"11".repeat(32))];
        let bytes = render(&mut rows).unwrap();
        assert_eq!(parse(&bytes, Path::new("x")).unwrap(), rows);
    }

    #[test]
    fn the_origin_column_is_lifted_from_the_sidecars_provenance() {
        let text = format!(
            r#"{{"schema":1,"hash":"{}","kind":"definition","deps":[],"sequence":0,"provenance":{{"origin":"generated","source":"runs/x"}}}}"#,
            "ab".repeat(32)
        );
        let sidecar = Sidecar::parse(text.as_bytes(), Path::new("x")).unwrap();
        let row = IndexRow::from_sidecar(&sidecar, text.as_bytes());
        assert_eq!(row.origin.as_deref(), Some("generated"));
    }

    #[test]
    fn a_sidecar_without_provenance_indexes_as_unlabelled_not_as_curated() {
        let text = format!(
            r#"{{"schema":1,"hash":"{}","kind":"definition","deps":[],"sequence":0}}"#,
            "ab".repeat(32)
        );
        let sidecar = Sidecar::parse(text.as_bytes(), Path::new("x")).unwrap();
        let row = IndexRow::from_sidecar(&sidecar, text.as_bytes());
        assert_eq!(row.origin, None);
    }

    #[test]
    fn a_missing_index_reads_as_empty_rather_than_failing() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        layout.init(serde_json::Map::new()).unwrap();
        assert!(read(&layout).unwrap().is_empty());
    }
}
