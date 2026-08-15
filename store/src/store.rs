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
use crate::names;
use crate::oracle::Oracle;
use crate::sidecar::Sidecar;
use crate::state;

/// How many times `acquire` will re-fold and re-claim before reporting
/// contention. Each attempt is a handful of filesystem calls and no sleep; the
/// loop only ever runs again because *another* acquisition won the fence and
/// has not appended yet, so a bound this small is generous.
const MAX_ACQUIRE_ATTEMPTS: usize = 16;

/// The same bound as `MAX_ACQUIRE_ATTEMPTS`, for `bind`'s seq claim, for the
/// same reason: a retry only happens because another `bind` under the same
/// fence won the race for that `seq` and has not appended yet.
const MAX_BIND_ATTEMPTS: usize = 16;

/// The store's own clock, which §5.3.3 makes the only clock that matters:
/// "expiry is judged by the store's clock at admission time", so writer-side
/// skew is harmless and this is the single arbiter.
pub fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |since| since.as_millis() as u64)
}

fn namespace_label(namespace: &str) -> String {
    if namespace.is_empty() {
        "the root namespace".to_string()
    } else {
        format!("namespace {namespace:?}")
    }
}

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

    /// Throw the derived data away and re-derive it: the index from the
    /// sidecars, and every namespace's current-lease cache from its log. The
    /// explicit repair for the divergences `fsck` reports, and the reason a
    /// crash between an append and a cache write is a nuisance rather than a
    /// corruption.
    pub fn reindex(&self) -> Result<(usize, usize)> {
        let mut rows = index::rebuild(&self.layout)?;
        let count = rows.len();
        let bytes = index::render(&mut rows)?;
        write_atomic(&self.layout.tmp_dir(), &self.layout.index_file(), &bytes)?;
        Ok((count, state::refresh_all(&self.layout)?))
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

        problems.extend(self.fsck_state()?);

        Ok(FsckReport {
            objects: seen.len(),
            rows,
            problems,
        })
    }

    /// The fourth invariant (§5.3.3, and the namespaces plan's R1).
    ///
    /// [`state::check`] owns everything decidable from the logs alone — they
    /// parse, fences increase strictly and were each issued once, the cache
    /// equals the fold, `seq` increases strictly and was each issued once.
    /// What it cannot do is look an object up, so the two checks that need
    /// the object store live here: every `def-hash` and every `policy-ref` a
    /// binding names is present, and is of the kind §5.3.2 requires for that
    /// leaf.
    fn fsck_state(&self) -> Result<Vec<Problem>> {
        let mut problems: Vec<Problem> = state::check(&self.layout)?
            .into_iter()
            .map(|found| Problem {
                kind: found.kind,
                hash: None,
                detail: format!("{}: {}", namespace_label(&found.namespace), found.detail),
            })
            .collect();

        for namespace in state::namespaces(&self.layout, state::BINDINGS_DIR)? {
            for record in state::bindings(&self.layout, &namespace)? {
                let policy_leaf = names::NamePath::parse(&record.name_path)
                    .map(|path| path.is_policy())
                    .unwrap_or(false);
                let expected = if policy_leaf {
                    crate::sidecar::KIND_POLICY
                } else {
                    crate::sidecar::KIND_DEFINITION
                };
                self.check_bound_object(
                    &mut problems,
                    &record.name_path,
                    &record.def_hash,
                    expected,
                    "def-hash",
                );
                self.check_bound_object(
                    &mut problems,
                    &record.name_path,
                    &record.policy_ref,
                    crate::sidecar::KIND_POLICY,
                    "policy-ref",
                );
            }
        }
        Ok(problems)
    }

    fn check_bound_object(
        &self,
        problems: &mut Vec<Problem>,
        name_path: &str,
        hash: &str,
        expected: &str,
        slot: &str,
    ) {
        let parsed = match ObjectHash::parse(hash) {
            Ok(parsed) => parsed,
            Err(error) => {
                problems.push(Problem {
                    kind: "binding_hash_malformed",
                    hash: Some(hash.to_string()),
                    detail: format!("{name_path}'s {slot}: {error}"),
                });
                return;
            }
        };
        match self.sidecar(&parsed) {
            Ok((sidecar, _)) if sidecar.kind == expected => {}
            Ok((sidecar, _)) => problems.push(Problem {
                kind: "binding_kind_wrong",
                hash: Some(hash.to_string()),
                detail: format!(
                    "{name_path}'s {slot} names a {} object where §5.3.2 requires a {expected}",
                    sidecar.kind
                ),
            }),
            Err(StoreError::NotFound { .. }) => problems.push(Problem {
                kind: "binding_object_missing",
                hash: Some(hash.to_string()),
                detail: format!("{name_path}'s {slot} names an object this store does not hold"),
            }),
            Err(error) => problems.push(Problem {
                kind: "binding_object_unreadable",
                hash: Some(hash.to_string()),
                detail: format!("{name_path}'s {slot}: {error}"),
            }),
        }
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

    // -- namespaces: leases (§5.3.3) -----------------------------------------

    /// A scratch file inside the store's own `tmp/`, for handing the oracle a
    /// request document. Same filesystem as everything else, and removed by the
    /// caller — never `/tmp`, which may be a different mount.
    /// Absolute, because the oracle runs with its own working directory
    /// (`prototype/`) and a relative path would resolve against that instead.
    fn scratch(&self, stem: &str) -> Result<std::path::PathBuf> {
        let directory = self.layout.tmp_dir();
        fs::create_dir_all(&directory).map_err(|error| StoreError::io(&directory, error))?;
        let directory =
            fs::canonicalize(&directory).map_err(|error| StoreError::io(&directory, error))?;
        Ok(directory.join(format!("{stem}.{}.json", std::process::id())))
    }

    fn write_request(&self, stem: &str, body: &Value) -> Result<std::path::PathBuf> {
        let path = self.scratch(stem)?;
        let mut bytes = serde_json::to_vec(body).map_err(|error| StoreError::Layout {
            detail: error.to_string(),
        })?;
        bytes.push(b'\n');
        fs::write(&path, &bytes).map_err(|error| StoreError::io(&path, error))?;
        Ok(path)
    }

    /// Every enclosing namespace's current `POLICY` binding, nearest first,
    /// each carrying the oracle's JSON mirror of the policy object.
    ///
    /// This is the *fold*, not the resolution: which of these governs, and
    /// whether the chain dominates, is §5.3.2 semantics and belongs to the
    /// oracle. Walking binding logs is the store's job, so the store does
    /// exactly that and hands over what it found.
    pub fn policy_chain(&self, namespace: &str) -> Result<Vec<Value>> {
        let mut chain = Vec::new();
        for ancestor in names::ancestors(namespace) {
            let heads = state::heads(&state::bindings(&self.layout, &ancestor)?);
            let leaf = if ancestor.is_empty() {
                names::POLICY_LEAF.to_string()
            } else {
                format!("{ancestor}/{}", names::POLICY_LEAF)
            };
            let Some(record) = heads.get(&leaf) else {
                continue;
            };
            let hash = ObjectHash::parse(&record.def_hash)?;
            let (sidecar, _) = self.sidecar(&hash)?;
            if sidecar.kind != crate::sidecar::KIND_POLICY {
                return Err(StoreError::Integrity {
                    hash: record.def_hash.clone(),
                    detail: format!("{leaf} is bound to a {} object, not a policy", sidecar.kind),
                });
            }
            chain.push(json!({
                "namespace": ancestor,
                "hash": record.def_hash,
                "object": sidecar.object,
            }));
        }
        Ok(chain)
    }

    pub fn lease_status(&self, namespace: &str) -> Result<Option<state::LeaseState>> {
        names::validate_namespace(namespace)?;
        Ok(state::fold(
            namespace,
            &state::lease_events(&self.layout, namespace)?,
        ))
    }

    /// `acquire(namespace, principal, ttl-millis)` (§5.3.3).
    ///
    /// The order is deliberate: the policy check runs *before* the fence is
    /// claimed, so a principal who may not hold this lease never burns a fence
    /// number. Expiry is judged by this process's clock at this moment, which
    /// is what "the single arbiter the store already is" means.
    pub fn lease_acquire(
        &self,
        oracle: &Oracle,
        namespace: &str,
        principal: &str,
        ttl_millis: u64,
    ) -> Result<state::LeaseState> {
        names::validate_namespace(namespace)?;
        ObjectHash::parse(principal).map_err(|_| StoreError::BadHash {
            text: principal.to_string(),
            detail: "a principal-id is 32 bytes, spelled as 64 lowercase hex digits".to_string(),
        })?;
        if ttl_millis == 0 {
            return Err(StoreError::Lease {
                reason: "bound".to_string(),
                detail: "a lease needs a positive ttl-millis".to_string(),
                context: json!({ "ttl_millis": 0 }),
            });
        }
        let policy_ref = self.clear_lease(oracle, namespace, principal, ttl_millis)?;

        for _ in 0..MAX_ACQUIRE_ATTEMPTS {
            let events = state::lease_events(&self.layout, namespace)?;
            let held = state::fold(namespace, &events);
            let now = now_millis();
            if let Some(current) = held.as_ref().filter(|lease| lease.held_at(now)) {
                return Err(StoreError::Lease {
                    reason: "held".to_string(),
                    detail: format!(
                        "{} holds {} until {} (now {now})",
                        current.principal,
                        namespace_label(namespace),
                        current.expires_millis
                    ),
                    context: json!({
                        "namespace": namespace,
                        "holder": current.principal,
                        "fence": current.fence,
                        "expires_millis": current.expires_millis,
                        "now_millis": now,
                    }),
                });
            }
            let fence = held.as_ref().map_or(0, |lease| lease.fence) + 1;
            // The claim, not the fold, is what makes a fence unique: exactly one
            // process can create this file, so exactly one can append this
            // acquisition. See `state.rs`.
            if !state::claim_fence(&self.layout, namespace, fence)? {
                continue;
            }
            let event = state::LeaseEvent::Acquire {
                fence,
                principal: principal.to_string(),
                policy_ref: policy_ref.clone(),
                at_millis: now,
                expires_millis: now + ttl_millis,
                ttl_millis,
            };
            state::append_lease_event(&self.layout, namespace, &event)?;
            state::refresh_current(&self.layout, namespace)?;
            return self.expect_lease(namespace);
        }
        Err(StoreError::Lease {
            reason: "held".to_string(),
            detail: format!(
                "another acquisition of {} is in flight; contention is poll-based, so retry",
                namespace_label(namespace)
            ),
            context: json!({ "namespace": namespace, "attempts": MAX_ACQUIRE_ATTEMPTS }),
        })
    }

    /// `renew(namespace, fence, ttl-millis)` — same fence, re-checked against
    /// the policy **now** in force (§5.3.3). That re-check is the whole reason a
    /// mid-lease policy rebind needs no eviction: the new policy binds here.
    pub fn lease_renew(
        &self,
        oracle: &Oracle,
        namespace: &str,
        fence: u64,
        ttl_millis: u64,
    ) -> Result<state::LeaseState> {
        names::validate_namespace(namespace)?;
        let current = self.expect_lease(namespace)?;
        let now = now_millis();
        self.require_fence(namespace, &current, fence, now)?;
        let policy_ref = self.clear_lease(oracle, namespace, &current.principal, ttl_millis)?;
        state::append_lease_event(
            &self.layout,
            namespace,
            &state::LeaseEvent::Renew {
                fence,
                policy_ref,
                at_millis: now,
                expires_millis: now + ttl_millis,
                ttl_millis,
            },
        )?;
        state::refresh_current(&self.layout, namespace)?;
        self.expect_lease(namespace)
    }

    /// `release(namespace, fence)` — ends the lease immediately. The fence
    /// stays in the log, so a late proposal from the released holder still
    /// fails the fence check rather than resolving against nothing.
    pub fn lease_release(&self, namespace: &str, fence: u64) -> Result<state::LeaseState> {
        names::validate_namespace(namespace)?;
        let current = self.expect_lease(namespace)?;
        if current.released {
            return Err(StoreError::Lease {
                reason: "fence".to_string(),
                detail: format!("fence {fence} was already released"),
                context: json!({ "namespace": namespace, "fence": current.fence }),
            });
        }
        if current.fence != fence {
            return Err(self.stale_fence(namespace, &current, fence, "released"));
        }
        state::append_lease_event(
            &self.layout,
            namespace,
            &state::LeaseEvent::Release {
                fence,
                at_millis: now_millis(),
            },
        )?;
        state::refresh_current(&self.layout, namespace)?;
        self.expect_lease(namespace)
    }

    fn clear_lease(
        &self,
        oracle: &Oracle,
        namespace: &str,
        principal: &str,
        ttl_millis: u64,
    ) -> Result<String> {
        let request = self.write_request(
            "lease-request",
            &json!({
                "schema": 1,
                "namespace": namespace,
                "principal": principal,
                "ttl_millis": ttl_millis,
                "policy_bindings": self.policy_chain(namespace)?,
            }),
        )?;
        let answer = oracle.lease_check(&request);
        let _ = fs::remove_file(&request);
        let answer = answer?;
        answer
            .get("policy_ref")
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| StoreError::Oracle {
                detail: format!("lease check returned no policy_ref: {answer}"),
            })
    }

    fn expect_lease(&self, namespace: &str) -> Result<state::LeaseState> {
        self.lease_status(namespace)?
            .ok_or_else(|| StoreError::Lease {
                reason: "fence".to_string(),
                detail: format!("{} has never been leased", namespace_label(namespace)),
                context: json!({ "namespace": namespace }),
            })
    }

    /// The check §5.3.3 makes the guarantee: current, and unexpired.
    fn require_fence(
        &self,
        namespace: &str,
        current: &state::LeaseState,
        presented: u64,
        now: u64,
    ) -> Result<()> {
        if current.fence != presented {
            return Err(self.stale_fence(namespace, current, presented, "superseded"));
        }
        if !current.held_at(now) {
            return Err(StoreError::Lease {
                reason: "fence".to_string(),
                detail: format!(
                    "fence {presented} is no longer held: the lease {}",
                    if current.released {
                        "was released".to_string()
                    } else {
                        format!("expired at {} (now {now})", current.expires_millis)
                    }
                ),
                context: json!({
                    "namespace": namespace,
                    "fence": current.fence,
                    "expires_millis": current.expires_millis,
                    "now_millis": now,
                }),
            });
        }
        Ok(())
    }

    fn stale_fence(
        &self,
        namespace: &str,
        current: &state::LeaseState,
        presented: u64,
        verb: &str,
    ) -> StoreError {
        StoreError::Lease {
            reason: "fence".to_string(),
            detail: format!(
                "fence {presented} was {verb}; {} is now at fence {}",
                namespace_label(namespace),
                current.fence
            ),
            context: json!({
                "namespace": namespace,
                "presented_fence": presented,
                "fence": current.fence,
            }),
        }
    }

    // -- namespaces: bindings (§5.3, §5.3.2) ---------------------------------

    /// Append a binding record, if the fence holds and the oracle admits it.
    ///
    /// The split is the plan's R2 and store v0's R3 applied to names: this
    /// method checks the four things that are *store* invariants — the fence is
    /// current and unexpired, `seq` continues the namespace's sequence, the
    /// objects named are here, and their kinds are the ones §5.3.2 requires —
    /// and hands everything semantic to the oracle. It never reads a policy.
    ///
    /// `seq` is proposed from the log's current length, same as it always
    /// was, but it is now *claimed* before anything durable happens — see
    /// [`state::claim_binding_seq`] and the module docstring on
    /// `state.rs` — because two `bind` calls racing under one held fence (the
    /// same holder, two threads or processes) would otherwise both read the
    /// same length and both propose the same `seq`. A lost claim means
    /// someone else's record landed first; this method re-reads the log and
    /// tries again rather than risk two records sharing a `seq`.
    pub fn bind(
        &self,
        oracle: &Oracle,
        name_path: &str,
        def_hash: &str,
        evidence: Vec<Value>,
        policy_ref: &str,
        fence: u64,
    ) -> Result<(state::BindingRecord, Value)> {
        let path = names::NamePath::parse(name_path)?;
        let namespace = path.namespace().to_string();

        let current = self.expect_lease(&namespace)?;
        self.require_fence(&namespace, &current, fence, now_millis())?;

        let definition = ObjectHash::parse(def_hash)?;
        let (def_sidecar, _) = self.sidecar(&definition)?;
        let wanted = if path.is_policy() {
            crate::sidecar::KIND_POLICY
        } else {
            crate::sidecar::KIND_DEFINITION
        };
        if def_sidecar.kind != wanted {
            return Err(StoreError::NotApplicable {
                hash: def_hash.to_string(),
                kind: def_sidecar.kind.clone(),
                detail: format!(
                    "a binding whose leaf is {} targets a {wanted} object (§5.3.2)",
                    if path.is_policy() {
                        names::POLICY_LEAF
                    } else {
                        "not POLICY"
                    }
                ),
            });
        }
        // The policy the proposal names must be an object this store holds and
        // must be a policy. Whether it is the *governing* one is rule 1, and
        // rule 1 is the oracle's.
        let policy = ObjectHash::parse(policy_ref)?;
        let (policy_sidecar, _) = self.sidecar(&policy)?;
        if policy_sidecar.kind != crate::sidecar::KIND_POLICY {
            return Err(StoreError::NotApplicable {
                hash: policy_ref.to_string(),
                kind: policy_sidecar.kind.clone(),
                detail: "a policy-ref names a policy object (§5.3)".to_string(),
            });
        }

        for _ in 0..MAX_BIND_ATTEMPTS {
            let records = state::bindings(&self.layout, &namespace)?;
            let seq = records.len() as u64 + 1;
            let previous = state::heads(&records).get(name_path).cloned();
            let previous_body = match previous.as_ref() {
                None => Value::Null,
                Some(record) => {
                    let object = if path.is_policy() {
                        self.sidecar(&ObjectHash::parse(&record.def_hash)?)?
                            .0
                            .object
                    } else {
                        None
                    };
                    json!({
                        "def_hash": record.def_hash,
                        "evidence": record.evidence,
                        "policy_ref": record.policy_ref,
                        "seq": record.seq,
                        "object": object,
                    })
                }
            };

            let request = self.write_request(
                "bind-request",
                &json!({
                    "schema": 1,
                    "binding": {
                        "name_path": name_path,
                        "def_hash": def_hash,
                        "evidence": evidence,
                        "policy_ref": policy_ref,
                        "seq": seq,
                        "object": if path.is_policy() { def_sidecar.object.clone() } else { None },
                    },
                    "policy_bindings": self.policy_chain(&namespace)?,
                    "previous": previous_body,
                }),
            )?;
            let admission = oracle.bind(&request);
            let _ = fs::remove_file(&request);
            let admission = admission?;

            // Expiry is judged at admission time, and the oracle call sits inside
            // that window. Re-checking here is what stops a lease that expired
            // *during* validation from landing a binding after a second writer has
            // already taken the namespace.
            let current = self.expect_lease(&namespace)?;
            self.require_fence(&namespace, &current, fence, now_millis())?;

            // Claim `seq` now, right before it becomes durable. If another
            // `bind` claimed it first — it raced us between our read of the
            // log above and this point — retry from a fresh read instead of
            // appending a duplicate.
            if !state::claim_binding_seq(&self.layout, &namespace, seq)? {
                continue;
            }

            let record = state::BindingRecord {
                seq,
                name_path: name_path.to_string(),
                def_hash: def_hash.to_string(),
                evidence,
                policy_ref: policy_ref.to_string(),
                fence,
            };
            state::append_binding(&self.layout, &namespace, &record)?;
            return Ok((record, admission));
        }
        Err(StoreError::Lease {
            reason: "contention".to_string(),
            detail: format!(
                "another bind in {} is in flight; contention is poll-based, so retry",
                namespace_label(&namespace)
            ),
            context: json!({ "namespace": namespace, "attempts": MAX_BIND_ATTEMPTS }),
        })
    }

    /// The current binding of a name, or the one in force at `at_seq`.
    pub fn resolve(&self, name_path: &str, at_seq: Option<u64>) -> Result<state::BindingRecord> {
        let path = names::NamePath::parse(name_path)?;
        let records = state::bindings(&self.layout, path.namespace())?;
        records
            .into_iter()
            .filter(|record| record.name_path == name_path)
            .rfind(|record| at_seq.is_none_or(|seq| record.seq <= seq))
            .ok_or_else(|| StoreError::NameNotFound {
                name: name_path.to_string(),
                detail: match at_seq {
                    Some(seq) => format!("no binding of that name at or before seq {seq}"),
                    None => "no binding of that name".to_string(),
                },
            })
    }

    /// Every binding of a name, oldest first. §5.3's "every previous state of
    /// every namespace remains addressable", as a list.
    pub fn history(&self, name_path: &str) -> Result<Vec<state::BindingRecord>> {
        let path = names::NamePath::parse(name_path)?;
        let found: Vec<_> = state::bindings(&self.layout, path.namespace())?
            .into_iter()
            .filter(|record| record.name_path == name_path)
            .collect();
        if found.is_empty() {
            return Err(StoreError::NameNotFound {
                name: name_path.to_string(),
                detail: "no binding of that name".to_string(),
            });
        }
        Ok(found)
    }

    /// The current binding of every name, in one namespace or in all of them.
    /// An empty answer is data, not a miss — a namespace with no bindings is a
    /// perfectly ordinary namespace.
    pub fn names(&self, namespace: Option<&str>) -> Result<Vec<state::BindingRecord>> {
        let wanted = match namespace {
            Some(namespace) => {
                names::validate_namespace(namespace)?;
                vec![namespace.to_string()]
            }
            None => state::namespaces(&self.layout, state::BINDINGS_DIR)?,
        };
        let mut found = Vec::new();
        for namespace in wanted {
            found.extend(state::heads(&state::bindings(&self.layout, &namespace)?).into_values());
        }
        found.sort_by(|left, right| left.name_path.cmp(&right.name_path));
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
            // A policy object is not resolvable as a term or as a type, so it
            // has no place in a *resolver* document. This is the one kind
            // filter here, and it is not a projection of the sidecar shape —
            // each object that appears still appears whole.
            if sidecar.kind == crate::sidecar::KIND_POLICY {
                continue;
            }
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
