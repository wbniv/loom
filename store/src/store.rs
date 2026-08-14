//! The store itself: put, the read API, and `fsck`.
//!
//! What this type knows about a Loom object is exactly two things — its bytes,
//! and what the Python oracle said about them. It never interprets the bytes.
//! That is not a limitation being worked around; it is R1's line, and holding
//! it is what keeps Track G free of the differential-testing debt a ported
//! validator would carry.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use serde::Serialize;
use serde_json::{json, Value};

use crate::atomic::write_atomic;
use crate::error::{Result, StoreError};
use crate::hash::ObjectHash;
use crate::index::{self, IndexRow};
use crate::layout::{Layout, StoreMeta};
use crate::sidecar::Sidecar;

/// What a `put` did. Conclusion 4 — content-addressed identity is generation
/// equality — is why `Exists` is a success rather than a conflict.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PutOutcome {
    Written,
    Exists,
}

impl PutOutcome {
    pub fn as_str(&self) -> &'static str {
        match self {
            PutOutcome::Written => "written",
            PutOutcome::Exists => "exists",
        }
    }
}

/// One thing `fsck` found wrong, named precisely enough to act on.
#[derive(Debug, Clone, Serialize)]
pub struct Problem {
    pub kind: &'static str,
    pub hash: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct FsckReport {
    pub objects: usize,
    pub rows: usize,
    pub problems: Vec<Problem>,
}

impl FsckReport {
    pub fn healthy(&self) -> bool {
        self.problems.is_empty()
    }
}

pub struct Store {
    layout: Layout,
}

impl Store {
    /// Create the store if it is not there. Returns whether it was created.
    pub fn init(
        root: impl AsRef<std::path::Path>,
        contracts: serde_json::Map<String, Value>,
    ) -> Result<(Self, bool)> {
        let layout = Layout::new(root);
        let created = layout.init(contracts)?;
        Ok((Store { layout }, created))
    }

    /// Open an existing store, refusing a directory that is not one.
    pub fn open(root: impl AsRef<std::path::Path>) -> Result<Self> {
        let layout = Layout::new(root);
        layout.meta()?;
        Ok(Store { layout })
    }

    pub fn layout(&self) -> &Layout {
        &self.layout
    }

    pub fn meta(&self) -> Result<StoreMeta> {
        self.layout.meta()
    }

    // -- writing ------------------------------------------------------------

    /// Land an object and its sidecar, then the index row.
    ///
    /// The write order is the crash-safety argument, so it is stated rather
    /// than left to be inferred: **object, then sidecar, then index.** Every
    /// individual write is tmp-then-rename, so no file is ever torn. A crash
    /// between steps can leave an object with no index row — recoverable, and
    /// `fsck` reports it — but can never leave an index row pointing at an
    /// object that is not fully on disk, which is the direction that would
    /// make a reader return wrong bytes rather than an honest miss.
    pub fn put(&self, object: &[u8], sidecar_bytes: &[u8]) -> Result<(ObjectHash, PutOutcome)> {
        let hash = ObjectHash::of(object);
        let sidecar_path = self.layout.sidecar_path(&hash);
        let sidecar = Sidecar::parse(sidecar_bytes, &sidecar_path)?;
        let claimed = sidecar.object_hash()?;
        if claimed != hash {
            return Err(StoreError::Integrity {
                hash: hash.to_string(),
                detail: format!("sidecar claims {claimed} but the object bytes hash to {hash}"),
            });
        }

        let object_path = self.layout.object_path(&hash);
        let object_present = object_path.exists();
        if object_present {
            // A dedup hit still verifies: if what is already filed under this
            // name does not hash to it, saying "exists" would be a lie told by
            // the one component whose job is to not tell that lie.
            let stored =
                fs::read(&object_path).map_err(|error| StoreError::io(&object_path, error))?;
            let stored_hash = ObjectHash::of(&stored);
            if stored_hash != hash {
                return Err(StoreError::Integrity {
                    hash: hash.to_string(),
                    detail: format!("stored object hashes to {stored_hash}"),
                });
            }
        }
        let sidecar_present = sidecar_path.exists();
        let indexed = self.rows()?.iter().any(|row| row.hash == sidecar.hash);
        if object_present && sidecar_present && indexed {
            return Ok((hash, PutOutcome::Exists));
        }

        let tmp = self.layout.tmp_dir();
        if !object_present {
            write_atomic(&tmp, &object_path, object)?;
        }
        if !sidecar_present {
            write_atomic(&tmp, &sidecar_path, sidecar_bytes)?;
        }
        let row = IndexRow::from_sidecar(&sidecar, sidecar_bytes);
        self.upsert_row(row)?;
        Ok((hash, PutOutcome::Written))
    }

    fn upsert_row(&self, row: IndexRow) -> Result<()> {
        let mut rows = self.rows()?;
        rows.retain(|existing| existing.hash != row.hash);
        rows.push(row);
        let bytes = index::render(&mut rows)?;
        write_atomic(&self.layout.tmp_dir(), &self.layout.index_file(), &bytes)
    }

    /// Throw the index away and re-derive it from the sidecars. The explicit
    /// repair for the divergences `fsck` reports.
    pub fn reindex(&self) -> Result<usize> {
        let mut rows = index::rebuild(&self.layout)?;
        let count = rows.len();
        let bytes = index::render(&mut rows)?;
        write_atomic(&self.layout.tmp_dir(), &self.layout.index_file(), &bytes)?;
        Ok(count)
    }

    // -- reading ------------------------------------------------------------

    /// The object's canonical bytes, verified against the name they are filed
    /// under. R1 requires identity checked on every read, not only on write:
    /// the store's single invariant is worth nothing if it is only ever checked
    /// at the moment it is easiest to hold.
    pub fn get(&self, hash: &ObjectHash) -> Result<Vec<u8>> {
        let path = self.layout.object_path(hash);
        let bytes = match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Err(StoreError::NotFound {
                    hash: hash.to_string(),
                })
            }
            Err(error) => return Err(StoreError::io(&path, error)),
        };
        let actual = ObjectHash::of(&bytes);
        if actual != *hash {
            return Err(StoreError::Integrity {
                hash: hash.to_string(),
                detail: format!(
                    "object bytes hash to {actual}, not to the name they are filed under"
                ),
            });
        }
        Ok(bytes)
    }

    pub fn sidecar(&self, hash: &ObjectHash) -> Result<(Sidecar, Vec<u8>)> {
        let path = self.layout.sidecar_path(hash);
        let bytes = match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Err(StoreError::NotFound {
                    hash: hash.to_string(),
                })
            }
            Err(error) => return Err(StoreError::io(&path, error)),
        };
        let sidecar = Sidecar::parse(&bytes, &path)?;
        if sidecar.object_hash()? != *hash {
            return Err(StoreError::Integrity {
                hash: hash.to_string(),
                detail: format!("sidecar filed under {hash} claims {}", sidecar.hash),
            });
        }
        Ok((sidecar, bytes))
    }

    pub fn rows(&self) -> Result<Vec<IndexRow>> {
        index::read(&self.layout)
    }

    pub fn row(&self, hash: &ObjectHash) -> Result<IndexRow> {
        let wanted = hash.to_string();
        self.rows()?
            .into_iter()
            .find(|row| row.hash == wanted)
            .ok_or(StoreError::NotFound { hash: wanted })
    }

    /// The type surface a `ref` to this hash has — straight off the index, with
    /// no object parse, because this call sits on the decode hot path.
    pub fn type_of(&self, hash: &ObjectHash) -> Result<(String, String)> {
        let row = self.row(hash)?;
        match row.type_surface {
            Some(surface) => Ok((row.kind, surface)),
            None => Err(StoreError::NotApplicable {
                hash: hash.to_string(),
                kind: row.kind.clone(),
                detail: format!(
                    "a {} declaration is not referenceable as a term and has no ref type",
                    row.kind
                ),
            }),
        }
    }

    pub fn deps(&self, hash: &ObjectHash) -> Result<Vec<String>> {
        Ok(self.row(hash)?.deps)
    }

    /// Everything that declares an edge to this hash. An O(rows) scan, which is
    /// the honest cost of R2's no-database stance and the thing the plan's
    /// completion-criteria watch is watching.
    pub fn rdeps(&self, hash: &ObjectHash) -> Result<Vec<String>> {
        let wanted = hash.to_string();
        let rows = self.rows()?;
        if !rows.iter().any(|row| row.hash == wanted) {
            return Err(StoreError::NotFound { hash: wanted });
        }
        let mut found: Vec<String> = rows
            .into_iter()
            .filter(|row| row.deps.contains(&wanted))
            .map(|row| row.hash)
            .collect();
        found.sort();
        Ok(found)
    }

    pub fn list(&self, kind: Option<&str>) -> Result<Vec<IndexRow>> {
        if let Some(kind) = kind {
            if !crate::sidecar::KINDS.contains(&kind) {
                return Err(StoreError::Layout {
                    detail: format!(
                        "unknown kind {kind:?}; known kinds: {}",
                        crate::sidecar::KINDS.join(", ")
                    ),
                });
            }
        }
        let mut rows = self.rows()?;
        if let Some(kind) = kind {
            rows.retain(|row| row.kind == kind);
        }
        Ok(rows)
    }

    /// Every hash extending `prefix`. The masker's reference-hash trie is
    /// seeded from exactly this, so an empty answer is data (no completion is
    /// possible) rather than a miss.
    pub fn prefix(&self, prefix: &str) -> Result<Vec<String>> {
        if !crate::hash::is_hex_prefix(prefix) {
            return Err(StoreError::BadHash {
                text: prefix.to_string(),
                detail: "expected 1–64 lowercase hex digits".to_string(),
            });
        }
        Ok(self
            .rows()?
            .into_iter()
            .filter(|row| row.hash.starts_with(prefix))
            .map(|row| row.hash)
            .collect())
    }

    // -- checking -----------------------------------------------------------

    /// Re-verify the three invariants R2 and R4 name:
    ///
    /// 1. every object re-hashes to the name it is filed under;
    /// 2. every sidecar agrees with that name, and has an object behind it;
    /// 3. the stored index is byte-identical to one rebuilt from the sidecars.
    ///
    /// Orphan objects — bytes with no sidecar — are reported too. They are the
    /// visible shape of a crash between `put`'s first and second write, and
    /// leaving them unreported would make that crash silent.
    pub fn fsck(&self) -> Result<FsckReport> {
        let mut problems = Vec::new();
        let mut seen = BTreeSet::new();

        for path in index::sidecar_paths(&self.layout)? {
            let bytes = fs::read(&path).map_err(|error| StoreError::io(&path, error))?;
            let sidecar = match Sidecar::parse(&bytes, &path) {
                Ok(sidecar) => sidecar,
                Err(error) => {
                    problems.push(Problem {
                        kind: "sidecar_malformed",
                        hash: None,
                        detail: format!("{}: {error}", path.display()),
                    });
                    continue;
                }
            };
            let hash = sidecar.object_hash()?;
            seen.insert(hash);

            let expected = self.layout.sidecar_path(&hash);
            if expected != path {
                problems.push(Problem {
                    kind: "sidecar_misfiled",
                    hash: Some(hash.to_string()),
                    detail: format!("claims {hash} but is filed at {}", path.display()),
                });
            }

            match self.get(&hash) {
                Ok(_) => {}
                Err(StoreError::NotFound { .. }) => problems.push(Problem {
                    kind: "object_missing",
                    hash: Some(hash.to_string()),
                    detail: "sidecar present, object absent".to_string(),
                }),
                Err(StoreError::Integrity { detail, .. }) => problems.push(Problem {
                    kind: "object_corrupt",
                    hash: Some(hash.to_string()),
                    detail,
                }),
                Err(other) => return Err(other),
            }
        }

        for (hash, _) in self.object_files()? {
            if !seen.contains(&hash) {
                problems.push(Problem {
                    kind: "object_orphan",
                    hash: Some(hash.to_string()),
                    detail: "object present, no sidecar describes it".to_string(),
                });
            }
        }

        let stored = fs::read(self.layout.index_file()).unwrap_or_default();
        let mut rebuilt_rows = index::rebuild(&self.layout)?;
        let rows = rebuilt_rows.len();
        let rebuilt = index::render(&mut rebuilt_rows)?;
        if stored != rebuilt {
            problems.push(Problem {
                kind: "index_diverged",
                hash: None,
                detail: "the stored index is not what the sidecars re-derive; run `reindex`"
                    .to_string(),
            });
        }

        Ok(FsckReport {
            objects: seen.len(),
            rows,
            problems,
        })
    }

    /// Every object file, as (hash from its path, path).
    fn object_files(&self) -> Result<BTreeMap<ObjectHash, std::path::PathBuf>> {
        let objects = self.layout.objects_dir();
        let mut found = BTreeMap::new();
        let fanouts = match fs::read_dir(&objects) {
            Ok(entries) => entries,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(found),
            Err(error) => return Err(StoreError::io(&objects, error)),
        };
        for fanout in fanouts {
            let fanout = fanout.map_err(|error| StoreError::io(&objects, error))?;
            let directory = fanout.path();
            if !directory.is_dir() {
                continue;
            }
            let prefix = fanout.file_name().to_string_lossy().to_string();
            for entry in
                fs::read_dir(&directory).map_err(|error| StoreError::io(&directory, error))?
            {
                let entry = entry.map_err(|error| StoreError::io(&directory, error))?;
                let leaf = entry.file_name().to_string_lossy().to_string();
                match ObjectHash::parse(&format!("{prefix}{leaf}")) {
                    Ok(hash) => {
                        found.insert(hash, entry.path());
                    }
                    Err(_) => continue,
                }
            }
        }
        Ok(found)
    }

    // -- export -------------------------------------------------------------

    /// One document carrying everything the Python harness needs to build a
    /// resolver, so the experiment reads the store once instead of per token
    /// (conclusion 6).
    ///
    /// The objects are the sidecars themselves, re-emitted whole. Projecting a
    /// narrower shape here would create a second schema to keep in step with
    /// the first, and the first is already the oracle's statement of record.
    pub fn export_resolver(&self) -> Result<Value> {
        let meta = self.meta()?;
        let mut objects: Vec<(u64, String, Value)> = Vec::new();
        for path in index::sidecar_paths(&self.layout)? {
            let bytes = fs::read(&path).map_err(|error| StoreError::io(&path, error))?;
            let sidecar = Sidecar::parse(&bytes, &path)?;
            let value: Value = serde_json::from_slice(&bytes)
                .map_err(|error| StoreError::malformed(&path, error.to_string()))?;
            objects.push((sidecar.sequence, sidecar.hash.clone(), value));
        }
        // (sequence, hash): sequence is the admitter's presentation order,
        // which for the pinned corpus is the manifest's dependency order that
        // `ExperimentResolver.definitions()` promises. Hash breaks ties so the
        // document never depends on readdir order.
        objects.sort_by(|left, right| (left.0, &left.1).cmp(&(right.0, &right.1)));

        Ok(json!({
            "schema": crate::sidecar::SCHEMA,
            "store": {
                "layout_version": meta.layout_version,
                "identity_algorithm": meta.identity_algorithm,
                "store_version": meta.store_version,
                "contracts": meta.contracts,
            },
            "objects": objects.into_iter().map(|(_, _, value)| value).collect::<Vec<_>>(),
        }))
    }
}
