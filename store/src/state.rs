//! The state stratum: append-only lease logs, append-only binding logs, and
//! the derived current-lease cache.
//!
//! Everything in `objects/` is immutable and content-addressed. A lease is
//! neither — it expires — and a binding is a *mapping* that changes, so SPEC
//! §5.3.3 puts leases in "their own stratum … outside object identity" and the
//! namespaces plan puts binding sequences beside them. This module is that
//! stratum:
//!
//! ```text
//! state/
//!   leases/<ns>.jsonl     append-only lease events, one JSON object per line
//!   fences/<ns>/<fence>   an empty marker per issued fence — see below
//!   current/<ns>.json     derived: the fold of the lease log
//!   bindings/<ns>.jsonl   append-only binding records, `seq` strictly increasing
//!   seqs/<ns>/<seq>       an empty marker per claimed binding seq — see below
//! ```
//!
//! `<ns>` is [`crate::names::encode`]'s stem, so one namespace is one file and
//! enumerating namespaces is one `read_dir`.
//!
//! ## Why the fence markers exist
//!
//! §5.3.3 promises that a store-side clock jump "can never admit two writers".
//! Folding the log and appending an acquire is a read-then-write, and two
//! processes that both observe the same expired lease would both compute fence
//! `n+1` and both append it. The marker closes that: a fence is *issued* by
//! `open(…, O_CREAT|O_EXCL)` on `fences/<ns>/<n+1>`, which POSIX gives to
//! exactly one caller, and only the winner appends. A crash between claiming
//! and appending burns a fence number, which is harmless — §5.3.3 requires
//! fences to increase strictly, not contiguously — and `fsck` therefore treats
//! a marker with no acquire as normal and an acquire with no marker as a
//! tampered log.
//!
//! ## Why the same discipline applies to binding seq
//!
//! §5.3 says a rebind is "a new binding record with a higher seq" and the
//! namespaces plan's R2 says binding `seq` is "strictly increasing" — neither
//! says contiguous, which is what makes this the same shape as a fence rather
//! than a new problem. `bind` reads the log's length to propose the next
//! `seq`, and two `bind` calls racing under one held fence (the same holder,
//! two threads or processes) can both read the same length and both propose
//! the same `seq`. The marker closes that exactly as the fence marker does: a
//! `seq` is *issued* by `open(…, O_CREAT|O_EXCL)` on `seqs/<ns>/<n>`, only the
//! winner appends, and a loser re-reads the log and proposes again. A crash
//! between claiming and appending burns a `seq`, which is harmless for the
//! same reason a burned fence is — nothing in §5.3 or §5.3.3 promises
//! contiguity, only strict increase — so `fsck` treats a marker with no
//! binding behind it as normal and a binding whose `seq` no marker backs as a
//! tampered log.
//!
//! ## Why the cache is derived rather than authoritative
//!
//! §5.3.3's integrity check is "any cached current-lease state equals the
//! fold", so the fold is the truth and the cache is a convenience. It is
//! written after the log, so a crash between the two leaves a stale cache that
//! `fsck` reports and `reindex` repairs — exactly the shape `index/types.jsonl`
//! already has, and for the same reason.
//!
//! ## Why a burned marker does not block forever
//!
//! Naively, `acquire`/`bind` would propose exactly `committed + 1` — the
//! fold's fence, or the binding log's length, plus one. A crash burns that
//! *specific* number's marker forever, and `committed` never advances without
//! an append, so every future proposal recomputes the identical burned number
//! and fails identically: not a bounded retry but a permanent block. See
//! [`next_after_claims`], which instead looks at what has actually been
//! *claimed* (via [`claimed_fences`]/[`claimed_binding_seqs`]) so a burn is
//! skipped rather than retried.
//!
//! This has to be used carefully, because the claim-marker directory can be
//! *ahead* of the log (a marker exists the moment `claim_fence`/
//! `claim_binding_seq` returns, before the corresponding event is appended),
//! so a proposal built from it is a guess about state that has not landed
//! yet. `bind` uses it on every attempt: nothing about a binding requires
//! exactly one caller to win, so several proposals racing ahead of each
//! other's not-yet-durable claims is fine — every successful claim still
//! yields a distinct `seq`, and [`heads`]/[`Store::resolve`]/[`Store::history`]
//! answer by `seq` value rather than by log position, so it does not matter
//! if two records land out of `seq` order. `lease_acquire` cannot be this
//! free with it: §5.3.3's whole point is that *at most one* acquisition may
//! land, which the fold-based `held` check enforces only against what is
//! already durable. Escalating on every attempt would let a caller who has
//! failed several rounds against a live (not burned) claimant leapfrog to a
//! *different*, unclaimed fence while that claimant is still mid-flight,
//! producing two holders — exactly what the fence claim exists to prevent.
//! `lease_acquire` therefore only escalates on its *last* attempt, after the
//! ordinary fold-based candidate has had every other attempt to resolve
//! normally (which a live claimant, appending within a couple of local
//! filesystem calls, essentially always does well within that budget), and
//! re-verifies nothing durable changed underneath it immediately before
//! appending. `fold` also treats a higher fence as more authoritative than a
//! lower one regardless of which line the log puts first, as a second layer
//! against the same narrow window — see `fold`'s own docs.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::atomic::write_atomic;
use crate::error::{Result, StoreError};
use crate::layout::Layout;
use crate::names;

/// The schema of every file in this stratum. Bumped when the Rust store and
/// the oracle must change together.
pub const STATE_SCHEMA: u32 = 1;

// ---------------------------------------------------------------------------
// records
// ---------------------------------------------------------------------------

/// One line of `state/leases/<ns>.jsonl`.
///
/// `renew` deliberately carries the *same* fence: §5.3.3 makes holder
/// continuity the point of renewal, so a renewal that issued a new fence would
/// invalidate the holder's own in-flight proposals.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum LeaseEvent {
    Acquire {
        fence: u64,
        principal: String,
        policy_ref: String,
        at_millis: u64,
        expires_millis: u64,
        ttl_millis: u64,
    },
    Renew {
        fence: u64,
        policy_ref: String,
        at_millis: u64,
        expires_millis: u64,
        ttl_millis: u64,
    },
    Release {
        fence: u64,
        at_millis: u64,
    },
}

impl LeaseEvent {
    pub fn fence(&self) -> u64 {
        match self {
            LeaseEvent::Acquire { fence, .. }
            | LeaseEvent::Renew { fence, .. }
            | LeaseEvent::Release { fence, .. } => *fence,
        }
    }

    pub fn is_acquire(&self) -> bool {
        matches!(self, LeaseEvent::Acquire { .. })
    }
}

/// The fold of a lease log: what the namespace's lease *is*.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeaseState {
    pub schema: u32,
    pub namespace: String,
    pub fence: u64,
    pub principal: String,
    pub policy_ref: String,
    pub acquired_millis: u64,
    pub expires_millis: u64,
    pub released: bool,
}

impl LeaseState {
    /// Whether this lease is held at `now`. Lazy expiry (§5.3.3) means there is
    /// no reaper: an expired lease is simply one this returns `false` for.
    pub fn held_at(&self, now_millis: u64) -> bool {
        !self.released && now_millis < self.expires_millis
    }
}

/// One line of `state/bindings/<ns>.jsonl` — the named mirror of SPEC §5.3's
/// `[2, name-path, def-hash, evidence-set, policy-ref, seq]`, plus the fence it
/// was admitted under.
///
/// The fence is not part of §5.3's record and is not part of a binding's
/// meaning; it is the audit trail for *which writer* appended it, which is
/// what makes the log an accountability record rather than a bare mapping.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BindingRecord {
    pub seq: u64,
    pub name_path: String,
    pub def_hash: String,
    /// `[[obligation-id, lattice-point]…]`, sorted by id. v1 carries the
    /// points inline rather than hashes of stored §6.1 evidence objects,
    /// because evidence-object storage is out of scope by the plan's R4 and
    /// §5.3 does not fix the element type.
    pub evidence: Vec<Value>,
    pub policy_ref: String,
    pub fence: u64,
}

impl BindingRecord {
    /// The §5.3 array this line mirrors. Nothing reads it yet; it exists so
    /// that the mirror can be checked against the spelling the SPEC gives,
    /// rather than the two drifting silently apart.
    pub fn spec_form(&self) -> Value {
        json!([
            2,
            self.name_path,
            self.def_hash,
            self.evidence,
            self.policy_ref,
            self.seq
        ])
    }
}

// ---------------------------------------------------------------------------
// paths
// ---------------------------------------------------------------------------

pub const STATE_DIR: &str = "state";
pub const LEASES_DIR: &str = "state/leases";
pub const FENCES_DIR: &str = "state/fences";
pub const CURRENT_DIR: &str = "state/current";
pub const BINDINGS_DIR: &str = "state/bindings";
pub const SEQS_DIR: &str = "state/seqs";

pub fn lease_log(layout: &Layout, namespace: &str) -> PathBuf {
    layout
        .root()
        .join(LEASES_DIR)
        .join(format!("{}.jsonl", names::encode(namespace)))
}

pub fn fence_dir(layout: &Layout, namespace: &str) -> PathBuf {
    layout
        .root()
        .join(FENCES_DIR)
        .join(names::encode(namespace))
}

pub fn current_file(layout: &Layout, namespace: &str) -> PathBuf {
    layout
        .root()
        .join(CURRENT_DIR)
        .join(format!("{}.json", names::encode(namespace)))
}

pub fn binding_log(layout: &Layout, namespace: &str) -> PathBuf {
    layout
        .root()
        .join(BINDINGS_DIR)
        .join(format!("{}.jsonl", names::encode(namespace)))
}

pub fn seq_dir(layout: &Layout, namespace: &str) -> PathBuf {
    layout.root().join(SEQS_DIR).join(names::encode(namespace))
}

/// Every namespace with a log of the given kind, sorted, decoded back from the
/// filename stem. A stem no encoding produces is skipped — `fsck` reports it
/// separately rather than guessing at a namespace name.
pub fn namespaces(layout: &Layout, directory: &str) -> Result<Vec<String>> {
    let path = layout.root().join(directory);
    let mut found = Vec::new();
    let entries = match fs::read_dir(&path) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(found),
        Err(error) => return Err(StoreError::io(&path, error)),
    };
    for entry in entries {
        let entry = entry.map_err(|error| StoreError::io(&path, error))?;
        let name = entry.file_name().to_string_lossy().to_string();
        let stem = match name
            .strip_suffix(".jsonl")
            .or_else(|| name.strip_suffix(".json"))
        {
            Some(stem) => stem,
            None => continue,
        };
        if let Some(namespace) = names::decode(stem) {
            found.push(namespace);
        }
    }
    found.sort();
    Ok(found)
}

// ---------------------------------------------------------------------------
// reading
// ---------------------------------------------------------------------------

fn read_lines<T: for<'a> Deserialize<'a>>(path: &Path) -> Result<Vec<T>> {
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(StoreError::io(path, error)),
    };
    let text = std::str::from_utf8(&bytes)
        .map_err(|error| StoreError::malformed(path, error.to_string()))?;
    let mut out = Vec::new();
    for (number, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        out.push(serde_json::from_str(line).map_err(|error| {
            StoreError::malformed(path, format!("line {}: {error}", number + 1))
        })?);
    }
    Ok(out)
}

pub fn lease_events(layout: &Layout, namespace: &str) -> Result<Vec<LeaseEvent>> {
    read_lines(&lease_log(layout, namespace))
}

pub fn bindings(layout: &Layout, namespace: &str) -> Result<Vec<BindingRecord>> {
    read_lines(&binding_log(layout, namespace))
}

/// The fold §5.3.3 calls the current lease: last event wins, and a `release`
/// leaves the fence in place so a released holder's late proposal still fails
/// the fence check rather than resolving against nothing.
///
/// "Last event wins" is "last by *fence*", not "last by file position", for
/// `Acquire`: an `Acquire` never overwrites a higher fence already folded,
/// even if it appears later in the log. In ordinary operation these always
/// coincide (an `Acquire` for fence `n+1` cannot be appended before fence
/// `n`'s own — see `lease_acquire`), so this only matters in the narrow
/// window `lease_acquire`'s last-attempt escalation leaves open (module
/// docstring, "why a burned marker does not block forever"): a second layer
/// that keeps the fold answering with whichever fence is actually
/// authoritative even if two `Acquire`s ever did land out of order. `Renew`
/// and `Release` only apply if their own fence matches the fence currently
/// folded — a mismatch means they belong to a fence some other `Acquire` has
/// since superseded, so applying them would silently misattribute a renewal
/// or release to the wrong holder.
pub fn fold(namespace: &str, events: &[LeaseEvent]) -> Option<LeaseState> {
    let mut state: Option<LeaseState> = None;
    for event in events {
        match event {
            LeaseEvent::Acquire {
                fence,
                principal,
                policy_ref,
                at_millis,
                expires_millis,
                ..
            } => {
                if state.as_ref().is_none_or(|current| *fence > current.fence) {
                    state = Some(LeaseState {
                        schema: STATE_SCHEMA,
                        namespace: namespace.to_string(),
                        fence: *fence,
                        principal: principal.clone(),
                        policy_ref: policy_ref.clone(),
                        acquired_millis: *at_millis,
                        expires_millis: *expires_millis,
                        released: false,
                    });
                }
            }
            LeaseEvent::Renew {
                fence,
                policy_ref,
                expires_millis,
                ..
            } => {
                if let Some(current) = state.as_mut() {
                    if *fence == current.fence {
                        current.policy_ref = policy_ref.clone();
                        current.expires_millis = *expires_millis;
                    }
                }
            }
            LeaseEvent::Release { fence, .. } => {
                if let Some(current) = state.as_mut() {
                    if *fence == current.fence {
                        current.released = true;
                    }
                }
            }
        }
    }
    state
}

pub fn current(layout: &Layout, namespace: &str) -> Result<Option<LeaseState>> {
    let path = current_file(layout, namespace);
    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(StoreError::io(&path, error)),
    };
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|error| StoreError::malformed(&path, error.to_string()))
}

/// The current binding of every name in a namespace: the highest `seq` per
/// name-path, not the last record in file order. `bind`'s seq claim (see the
/// module docstring) lets two records land out of `seq` order under
/// contention — every claimed `seq` is still unique, but file position no
/// longer implies recency — so "current" is answered by comparing `seq`
/// values directly rather than by assuming the log agrees with them.
/// `BTreeMap` so enumeration is sorted and never depends on log order either.
pub fn heads(records: &[BindingRecord]) -> BTreeMap<String, BindingRecord> {
    let mut found: BTreeMap<String, BindingRecord> = BTreeMap::new();
    for record in records {
        found
            .entry(record.name_path.clone())
            .and_modify(|current| {
                if record.seq > current.seq {
                    *current = record.clone();
                }
            })
            .or_insert_with(|| record.clone());
    }
    found
}

// ---------------------------------------------------------------------------
// writing
// ---------------------------------------------------------------------------

fn append_line(path: &Path, value: &impl Serialize) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| StoreError::io(parent, error))?;
    }
    let mut line = serde_json::to_vec(value).map_err(|error| StoreError::Layout {
        detail: error.to_string(),
    })?;
    line.push(b'\n');
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| StoreError::io(path, error))?;
    // One `write_all` of one line under `O_APPEND`: the kernel places it at the
    // end atomically, so a concurrent appender can never interleave inside it.
    file.write_all(&line)
        .map_err(|error| StoreError::io(path, error))?;
    file.sync_all().map_err(|error| StoreError::io(path, error))
}

/// Issue a fence by creating its marker, or report that someone else has it.
/// `O_EXCL` is the whole mechanism; see the module docstring.
pub fn claim_fence(layout: &Layout, namespace: &str, fence: u64) -> Result<bool> {
    let directory = fence_dir(layout, namespace);
    fs::create_dir_all(&directory).map_err(|error| StoreError::io(&directory, error))?;
    let path = directory.join(fence.to_string());
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(false),
        Err(error) => Err(StoreError::io(&path, error)),
    }
}

pub fn claimed_fences(layout: &Layout, namespace: &str) -> Result<Vec<u64>> {
    let directory = fence_dir(layout, namespace);
    let entries = match fs::read_dir(&directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(StoreError::io(&directory, error)),
    };
    let mut found = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| StoreError::io(&directory, error))?;
        if let Ok(fence) = entry.file_name().to_string_lossy().parse::<u64>() {
            found.push(fence);
        }
    }
    found.sort_unstable();
    Ok(found)
}

/// Issue a binding `seq` by creating its marker, or report that someone else
/// has it. The same mechanism as [`claim_fence`], for the same reason: see
/// the module docstring.
pub fn claim_binding_seq(layout: &Layout, namespace: &str, seq: u64) -> Result<bool> {
    let directory = seq_dir(layout, namespace);
    fs::create_dir_all(&directory).map_err(|error| StoreError::io(&directory, error))?;
    let path = directory.join(seq.to_string());
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(false),
        Err(error) => Err(StoreError::io(&path, error)),
    }
}

pub fn claimed_binding_seqs(layout: &Layout, namespace: &str) -> Result<Vec<u64>> {
    let directory = seq_dir(layout, namespace);
    let entries = match fs::read_dir(&directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(StoreError::io(&directory, error)),
    };
    let mut found = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| StoreError::io(&directory, error))?;
        if let Ok(seq) = entry.file_name().to_string_lossy().parse::<u64>() {
            found.push(seq);
        }
    }
    found.sort_unstable();
    Ok(found)
}

/// The next number to propose after `committed` (what the log itself has
/// already durably recorded), skipping past anything already `claimed` —
/// see the module docstring's "why a burned marker does not block forever".
/// Never proposes at or below `committed`: the log is always the floor, even
/// if the claim directory happens to be behind it (nothing has claimed
/// `committed`'s own successor yet) or ahead of it (something has, but has
/// not appended). An empty `claimed` falls back to `committed + 1` exactly
/// as the naive computation always did.
pub fn next_after_claims(claimed: &[u64], committed: u64) -> u64 {
    claimed
        .iter()
        .copied()
        .max()
        .unwrap_or(committed)
        .max(committed)
        + 1
}

pub fn append_lease_event(layout: &Layout, namespace: &str, event: &LeaseEvent) -> Result<()> {
    append_line(&lease_log(layout, namespace), event)
}

pub fn append_binding(layout: &Layout, namespace: &str, record: &BindingRecord) -> Result<()> {
    append_line(&binding_log(layout, namespace), record)
}

/// Rewrite the derived cache for one namespace from its log.
pub fn refresh_current(layout: &Layout, namespace: &str) -> Result<()> {
    let events = lease_events(layout, namespace)?;
    let path = current_file(layout, namespace);
    match fold(namespace, &events) {
        Some(state) => {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).map_err(|error| StoreError::io(parent, error))?;
            }
            let mut bytes = serde_json::to_vec(&state).map_err(|error| StoreError::Layout {
                detail: error.to_string(),
            })?;
            bytes.push(b'\n');
            write_atomic(&layout.tmp_dir(), &path, &bytes)
        }
        None => Ok(()),
    }
}

/// Rebuild every namespace's cache. The explicit repair for the divergence
/// `fsck` reports, and the reason a stale cache is a nuisance rather than a
/// corruption.
pub fn refresh_all(layout: &Layout) -> Result<usize> {
    let namespaces = namespaces(layout, LEASES_DIR)?;
    for namespace in &namespaces {
        refresh_current(layout, namespace)?;
    }
    Ok(namespaces.len())
}

// ---------------------------------------------------------------------------
// checking — `fsck` invariant 4
// ---------------------------------------------------------------------------

/// One thing wrong in the state stratum, in the shape `fsck` reports.
pub struct StateProblem {
    pub kind: &'static str,
    pub namespace: String,
    pub detail: String,
}

fn problem(kind: &'static str, namespace: &str, detail: impl Into<String>) -> StateProblem {
    StateProblem {
        kind,
        namespace: namespace.to_string(),
        detail: detail.into(),
    }
}

/// §5.3.3's integrity check: every log parses, fences increase strictly, and
/// any cached current-lease state equals the fold. Plus what the namespaces
/// plan adds for bindings: `seq` increases strictly and every claimed `seq`
/// a record uses was actually issued (the same two checks the fence gets, for
/// the same reason — see the module docstring), every record in the log its
/// own namespace names, and every record's fence one this namespace actually
/// issued.
///
/// Object presence and object kind are *not* checked here — they need the
/// object store, so [`crate::store::Store::fsck`] does them where it has it.
pub fn check(layout: &Layout) -> Result<Vec<StateProblem>> {
    let mut problems = Vec::new();

    for namespace in namespaces(layout, LEASES_DIR)? {
        let events = match lease_events(layout, &namespace) {
            Ok(events) => events,
            Err(error) => {
                problems.push(problem(
                    "lease_log_malformed",
                    &namespace,
                    error.to_string(),
                ));
                continue;
            }
        };
        let claims = claimed_fences(layout, &namespace)?;
        let mut highest = 0u64;
        for (index, event) in events.iter().enumerate() {
            let fence = event.fence();
            if event.is_acquire() {
                if fence <= highest {
                    problems.push(problem(
                        "lease_fence_regression",
                        &namespace,
                        format!(
                            "event {index} acquires fence {fence}, which does not exceed {highest}"
                        ),
                    ));
                }
                if !claims.contains(&fence) {
                    problems.push(problem(
                        "lease_fence_unissued",
                        &namespace,
                        format!("event {index} acquires fence {fence}, which was never issued"),
                    ));
                }
                highest = highest.max(fence);
            } else if fence != highest {
                problems.push(problem(
                    "lease_fence_regression",
                    &namespace,
                    format!(
                        "event {index} names fence {fence}, but the lease then held was {highest}"
                    ),
                ));
            }
        }

        let folded = fold(&namespace, &events);
        let cached = match current(layout, &namespace) {
            Ok(cached) => cached,
            Err(error) => {
                problems.push(problem(
                    "lease_cache_malformed",
                    &namespace,
                    error.to_string(),
                ));
                continue;
            }
        };
        if cached != folded {
            problems.push(problem(
                "lease_cache_diverged",
                &namespace,
                "the cached current lease is not the fold of the log; run `reindex`",
            ));
        }
    }

    for namespace in namespaces(layout, CURRENT_DIR)? {
        if !lease_log(layout, &namespace).exists() {
            problems.push(problem(
                "lease_cache_orphan",
                &namespace,
                "a cached current lease with no log behind it",
            ));
        }
    }

    for namespace in namespaces(layout, BINDINGS_DIR)? {
        let records = match bindings(layout, &namespace) {
            Ok(records) => records,
            Err(error) => {
                problems.push(problem(
                    "binding_log_malformed",
                    &namespace,
                    error.to_string(),
                ));
                continue;
            }
        };
        let issued_fences = claimed_fences(layout, &namespace)?;
        let issued_seqs = claimed_binding_seqs(layout, &namespace)?;
        // `bind` only ever proposes the log's current length + 1 (see
        // `claim_binding_seq`'s call site), so a legitimate log can never
        // present two records out of increasing order — a later `seq` cannot
        // be claimed until the record before it is durably appended. A
        // regression here is therefore tampering, exactly like a fence
        // regression.
        let mut highest = 0u64;
        for (index, record) in records.iter().enumerate() {
            let seq = record.seq;
            if seq <= highest {
                problems.push(problem(
                    "binding_seq_regression",
                    &namespace,
                    format!("record {index} has seq {seq}, which does not exceed {highest}"),
                ));
            }
            highest = highest.max(seq);
            if !issued_seqs.contains(&seq) {
                problems.push(problem(
                    "binding_seq_unissued",
                    &namespace,
                    format!(
                        "{} was bound at seq {seq}, which this namespace never claimed",
                        record.name_path
                    ),
                ));
            }
            match crate::names::NamePath::parse(&record.name_path) {
                Ok(path) if path.namespace() == namespace => {}
                Ok(path) => problems.push(problem(
                    "binding_namespace_mismatch",
                    &namespace,
                    format!(
                        "{} is in namespace {:?}, not in this log's",
                        record.name_path,
                        path.namespace()
                    ),
                )),
                Err(error) => problems.push(problem(
                    "binding_name_malformed",
                    &namespace,
                    error.to_string(),
                )),
            }
            if !issued_fences.contains(&record.fence) {
                problems.push(problem(
                    "binding_fence_unissued",
                    &namespace,
                    format!(
                        "{} was bound under fence {}, which this namespace never issued",
                        record.name_path, record.fence
                    ),
                ));
            }
        }
    }

    Ok(problems)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn acquire(fence: u64, expires: u64) -> LeaseEvent {
        LeaseEvent::Acquire {
            fence,
            principal: "aa".repeat(32),
            policy_ref: "bb".repeat(32),
            at_millis: 0,
            expires_millis: expires,
            ttl_millis: expires,
        }
    }

    #[test]
    fn the_fold_is_the_last_event_and_a_release_keeps_the_fence() {
        let events = vec![
            acquire(1, 100),
            LeaseEvent::Renew {
                fence: 1,
                policy_ref: "bb".repeat(32),
                at_millis: 50,
                expires_millis: 500,
                ttl_millis: 450,
            },
            LeaseEvent::Release {
                fence: 1,
                at_millis: 60,
            },
        ];
        let state = fold("stats", &events).unwrap();
        assert_eq!(state.fence, 1);
        assert_eq!(state.expires_millis, 500);
        assert!(state.released);
        // A released lease is not held even before its expiry.
        assert!(!state.held_at(0));
    }

    #[test]
    fn lazy_expiry_is_a_comparison_and_nothing_else() {
        let state = fold("stats", &[acquire(3, 100)]).unwrap();
        assert!(state.held_at(99));
        assert!(!state.held_at(100));
        assert!(!state.held_at(101));
    }

    #[test]
    fn an_empty_log_folds_to_no_lease_rather_than_to_a_default_one() {
        assert!(fold("stats", &[]).is_none());
    }

    #[test]
    fn a_higher_fence_wins_the_fold_even_if_it_is_not_last_in_the_log() {
        // The escalation window (module docstring, "why a burned marker does
        // not block forever") can — rarely — let a higher fence's `Acquire`
        // land before a lower, still-in-flight one's. The fold must not let
        // the lower one, merely by arriving later in the file, look current.
        let events = vec![acquire(2, 500), acquire(1, 100)];
        let state = fold("stats", &events).unwrap();
        assert_eq!(
            state.fence, 2,
            "the higher fence must win regardless of file order"
        );

        // A renew or release for a fence the fold no longer holds — because
        // a higher `Acquire` has since superseded it — must not silently
        // misattribute itself to the wrong holder.
        let events = vec![
            acquire(2, 500),
            LeaseEvent::Renew {
                fence: 1,
                policy_ref: "bb".repeat(32),
                at_millis: 10,
                expires_millis: 999,
                ttl_millis: 989,
            },
        ];
        let state = fold("stats", &events).unwrap();
        assert_eq!(state.fence, 2);
        assert_eq!(
            state.expires_millis, 500,
            "a renew naming a superseded fence must not touch the current lease"
        );
    }

    #[test]
    fn next_after_claims_skips_a_burn_but_never_proposes_below_the_log() {
        // Nothing claimed yet: falls back to the log's own next number.
        assert_eq!(next_after_claims(&[], 0), 1);
        assert_eq!(next_after_claims(&[], 5), 6);
        // A burn ahead of the log (claimed, never appended) is skipped.
        assert_eq!(next_after_claims(&[1, 2, 3], 0), 4);
        // The claim directory can also be *behind* the log's own fold in
        // principle (nothing has claimed the log's own successor yet); the
        // log is always the floor.
        assert_eq!(next_after_claims(&[1], 5), 6);
    }

    #[test]
    fn a_binding_line_mirrors_the_spec_array_it_stands_for() {
        let record = BindingRecord {
            seq: 7,
            name_path: "stats/median".into(),
            def_hash: "cc".repeat(32),
            evidence: vec![json!(["ensures.sorted", [3]])],
            policy_ref: "dd".repeat(32),
            fence: 2,
        };
        assert_eq!(
            record.spec_form(),
            json!([
                2,
                "stats/median",
                "cc".repeat(32),
                [["ensures.sorted", [3]]],
                "dd".repeat(32),
                7
            ])
        );
    }

    #[test]
    fn a_fence_is_issued_to_exactly_one_claimant() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        layout.init(serde_json::Map::new()).unwrap();
        assert!(claim_fence(&layout, "stats", 1).unwrap());
        assert!(!claim_fence(&layout, "stats", 1).unwrap());
        assert!(claim_fence(&layout, "stats", 2).unwrap());
        assert_eq!(claimed_fences(&layout, "stats").unwrap(), vec![1, 2]);
        // A different namespace has its own fence space.
        assert!(claim_fence(&layout, "other", 1).unwrap());
    }

    #[test]
    fn heads_answers_by_seq_value_not_by_file_position() {
        // The same escalation window, on the binding side: two records for
        // one name can land with the higher `seq` first in the file. `heads`
        // must still report the higher-`seq` record as current.
        let earlier = BindingRecord {
            seq: 3,
            name_path: "stats/median".into(),
            def_hash: "aa".repeat(32),
            evidence: vec![],
            policy_ref: "bb".repeat(32),
            fence: 1,
        };
        let later = BindingRecord {
            seq: 2,
            ..earlier.clone()
        };
        // `later` (seq 2) appears second in the file despite being the
        // *older* binding by seq — exactly the divergence next_after_claims
        // makes possible.
        let found = heads(&[earlier.clone(), later]);
        assert_eq!(found["stats/median"].seq, 3, "the higher seq must win");
        assert_eq!(found["stats/median"], earlier);
    }

    #[test]
    fn a_binding_seq_is_issued_to_exactly_one_claimant() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        layout.init(serde_json::Map::new()).unwrap();
        assert!(claim_binding_seq(&layout, "stats", 1).unwrap());
        assert!(!claim_binding_seq(&layout, "stats", 1).unwrap());
        assert!(claim_binding_seq(&layout, "stats", 2).unwrap());
        assert_eq!(claimed_binding_seqs(&layout, "stats").unwrap(), vec![1, 2]);
        // A different namespace has its own seq space.
        assert!(claim_binding_seq(&layout, "other", 1).unwrap());
    }

    #[test]
    fn a_hand_edited_fence_regression_is_caught_with_its_namespace_named() {
        let root = tempfile::tempdir().unwrap();
        let layout = Layout::new(root.path());
        layout.init(serde_json::Map::new()).unwrap();
        for fence in [1, 2] {
            claim_fence(&layout, "stats", fence).unwrap();
            append_lease_event(&layout, "stats", &acquire(fence, 100)).unwrap();
        }
        refresh_current(&layout, "stats").unwrap();
        assert!(check(&layout).unwrap().is_empty());

        let path = lease_log(&layout, "stats");
        let text = fs::read_to_string(&path)
            .unwrap()
            .replace("\"fence\":2", "\"fence\":1");
        fs::write(&path, text).unwrap();
        let problems = check(&layout).unwrap();
        assert!(problems.iter().any(|p| p.kind == "lease_fence_regression"));
        assert!(problems.iter().all(|p| p.namespace == "stats"));
    }
}
