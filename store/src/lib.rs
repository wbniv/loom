//! Loom's persistent content-addressed object store (SPEC §5), version 0.
//!
//! Designed by [`docs/plans/2026-08-14-store-v0.md`]. The short version of what
//! this crate is and is not:
//!
//! * **It is** immutable objects on disk named by the SHA-256 of their bytes,
//!   with crash-safe writes, an index that makes type lookup cheap enough for
//!   the decode hot path, and an `fsck` that re-proves all of it.
//! * **It is not** a validator. Object bytes are opaque here. Everything
//!   semantic arrives in a sidecar produced by the Python oracle
//!   (`prototype/store_admit.py`), which remains the specification of record
//!   until Track P's differential harness exists.
//! * **It is not** namespaced, leased, policy-gated, garbage-collected, or
//!   networked. Each of those is out by rule, with the reason recorded in the
//!   plan rather than left as an omission.
//!
//! Module map:
//!
//! | module | owns |
//! |---|---|
//! | [`hash`] | the 32-byte content address and its one hex spelling |
//! | [`error`] | the error / exit-code / output-shape taxonomy |
//! | [`atomic`] | tmp-then-rename writes with the fsyncs that make them mean something |
//! | [`layout`] | where files live, and `store.json` |
//! | [`sidecar`] | the oracle's statement about an object, as the store reads it |
//! | [`index`] | the derived, sorted, re-derivable `types.jsonl` |
//! | [`store`] | put, the read API, `fsck`, `export-resolver` |
//! | [`oracle`] | running the Python admission oracle |

pub mod atomic;
pub mod error;
pub mod hash;
pub mod index;
pub mod layout;
pub mod oracle;
pub mod sidecar;
pub mod store;

pub use error::{Result, StoreError};
pub use hash::ObjectHash;
pub use store::{FsckReport, PutOutcome, Store};
