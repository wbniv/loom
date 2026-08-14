//! Where things live, and the one file that says what "here" is.
//!
//! ```text
//! <root>/
//!   store.json                    layout version, identity algorithm, contracts
//!   objects/<2-hex>/<62-hex>      canonical object bytes, named by SHA-256
//!   meta/<2-hex>/<62-hex>.json    the oracle's sidecar, byte for byte as emitted
//!   index/types.jsonl             derived: one sorted row per object
//!   tmp/                          same-filesystem scratch for atomic writes
//! ```
//!
//! `store.json` is written once, at `init`, and never mutated. A file the store
//! rewrites is a file that can be torn or can disagree with itself; the only
//! thing that legitimately changes as objects arrive is the index, and the index
//! is derived data that `fsck` re-derives from scratch.
//!
//! The contract versions recorded here are therefore *the versions this store
//! was initialized under*, not a running summary. The authoritative,
//! per-object record is each sidecar's `validation.contracts`, which is what R3
//! actually needs: "a future MAJOR bump can find every object that predates
//! it" is a query over objects, not over the store.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::{Result, StoreError};
use crate::hash::ObjectHash;

/// Bumped when the directory layout changes shape. A store written by a newer
/// layout is refused rather than read optimistically.
pub const LAYOUT_VERSION: u32 = 1;

pub const STORE_FILE: &str = "store.json";
pub const OBJECTS_DIR: &str = "objects";
pub const META_DIR: &str = "meta";
pub const INDEX_DIR: &str = "index";
pub const INDEX_FILE: &str = "index/types.jsonl";
pub const TMP_DIR: &str = "tmp";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoreMeta {
    pub layout_version: u32,
    /// Named rather than assumed, so a future store that changes it has to say
    /// so in a file an old binary will refuse.
    pub identity_algorithm: String,
    pub store_version: String,
    /// The oracle's contract-version map at `init`, or `{}` when initialized
    /// without one.
    #[serde(default)]
    pub contracts: serde_json::Map<String, serde_json::Value>,
}

impl StoreMeta {
    pub fn new(contracts: serde_json::Map<String, serde_json::Value>) -> Self {
        StoreMeta {
            layout_version: LAYOUT_VERSION,
            identity_algorithm: "sha256".to_string(),
            store_version: env!("CARGO_PKG_VERSION").to_string(),
            contracts,
        }
    }
}

/// Path arithmetic over a store root. Holds no open handles and no cache, so it
/// is cheap to construct and impossible to have stale.
#[derive(Debug, Clone)]
pub struct Layout {
    root: PathBuf,
}

impl Layout {
    pub fn new(root: impl AsRef<Path>) -> Self {
        Layout {
            root: root.as_ref().to_path_buf(),
        }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn store_file(&self) -> PathBuf {
        self.root.join(STORE_FILE)
    }

    pub fn objects_dir(&self) -> PathBuf {
        self.root.join(OBJECTS_DIR)
    }

    pub fn meta_dir(&self) -> PathBuf {
        self.root.join(META_DIR)
    }

    pub fn index_file(&self) -> PathBuf {
        self.root.join(INDEX_FILE)
    }

    pub fn tmp_dir(&self) -> PathBuf {
        self.root.join(TMP_DIR)
    }

    pub fn object_path(&self, hash: &ObjectHash) -> PathBuf {
        let (directory, leaf) = hash.fanout();
        self.objects_dir().join(directory).join(leaf)
    }

    pub fn sidecar_path(&self, hash: &ObjectHash) -> PathBuf {
        let (directory, leaf) = hash.fanout();
        self.meta_dir().join(directory).join(format!("{leaf}.json"))
    }

    /// Create the directory skeleton and `store.json`. Idempotent: re-running
    /// over an existing store of the same layout is a no-op that reports so.
    pub fn init(&self, contracts: serde_json::Map<String, serde_json::Value>) -> Result<bool> {
        for directory in [
            self.objects_dir(),
            self.meta_dir(),
            self.root.join(INDEX_DIR),
            self.tmp_dir(),
        ] {
            fs::create_dir_all(&directory).map_err(|error| StoreError::io(&directory, error))?;
        }
        if self.store_file().exists() {
            self.meta()?;
            return Ok(false);
        }
        let meta = StoreMeta::new(contracts);
        let mut bytes = serde_json::to_vec_pretty(&meta).map_err(|error| StoreError::Layout {
            detail: error.to_string(),
        })?;
        bytes.push(b'\n');
        crate::atomic::write_atomic(&self.tmp_dir(), &self.store_file(), &bytes)?;
        Ok(true)
    }

    /// Read and validate `store.json`. This is what makes "is this directory a
    /// store?" a typed question rather than a guess about whether `objects/`
    /// happens to exist.
    pub fn meta(&self) -> Result<StoreMeta> {
        let path = self.store_file();
        let bytes = fs::read(&path).map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                StoreError::Layout {
                    detail: format!(
                        "{} is not a loom store (no store.json)",
                        self.root.display()
                    ),
                }
            } else {
                StoreError::io(&path, error)
            }
        })?;
        let meta: StoreMeta = serde_json::from_slice(&bytes)
            .map_err(|error| StoreError::malformed(&path, error.to_string()))?;
        if meta.layout_version != LAYOUT_VERSION {
            return Err(StoreError::Layout {
                detail: format!(
                    "store layout version {} is not {LAYOUT_VERSION}",
                    meta.layout_version
                ),
            });
        }
        if meta.identity_algorithm != "sha256" {
            return Err(StoreError::Layout {
                detail: format!("unknown identity algorithm {:?}", meta.identity_algorithm),
            });
        }
        Ok(meta)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_is_idempotent_and_second_run_reports_no_change() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        assert!(layout.init(serde_json::Map::new()).unwrap());
        assert!(!layout.init(serde_json::Map::new()).unwrap());
        assert_eq!(layout.meta().unwrap().layout_version, LAYOUT_VERSION);
    }

    #[test]
    fn a_bare_directory_is_not_a_store() {
        let root = tempfile::tempdir().unwrap();
        let error = Layout::new(root.path()).meta().unwrap_err();
        assert_eq!(error.class(), "layout");
    }

    #[test]
    fn a_future_layout_is_refused_rather_than_read() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        layout.init(serde_json::Map::new()).unwrap();
        fs::write(
            layout.store_file(),
            br#"{"layout_version":99,"identity_algorithm":"sha256","store_version":"9"}"#,
        )
        .unwrap();
        assert_eq!(layout.meta().unwrap_err().class(), "layout");
    }

    #[test]
    fn object_and_sidecar_paths_fan_out_on_the_same_two_hex() {
        let layout = Layout::new("/store");
        let hash = ObjectHash::of(b"");
        assert!(layout
            .object_path(&hash)
            .to_string_lossy()
            .contains("/objects/e3/"));
        assert!(layout
            .sidecar_path(&hash)
            .to_string_lossy()
            .ends_with(".json"));
    }
}
