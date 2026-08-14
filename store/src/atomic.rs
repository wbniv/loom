//! Tmp-then-rename writes, so a crash leaves the old state or the new one.
//!
//! Two details that are easy to get wrong and expensive to get wrong here:
//!
//! 1. **The temporary file lives inside the store**, not in `/tmp`. `rename(2)`
//!    is only atomic within one filesystem, and `/tmp` is routinely a different
//!    one (tmpfs). A cross-device rename fails loudly, which is survivable — but
//!    a copy-then-delete fallback would not be atomic at all, so the temporary
//!    is simply never anywhere else.
//! 2. **The data is fsynced before the rename and the directory after it.**
//!    Renaming a file whose contents are still in page cache moves the name
//!    atomically and the bytes not at all, which is exactly the torn object the
//!    plan's R2 forbids.

use std::fs::{self, File};
use std::io::Write;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::error::{Result, StoreError};

static COUNTER: AtomicU64 = AtomicU64::new(0);

/// A unique name inside the store's own `tmp/` directory.
///
/// v0 is a single-writer store (R1), so this only has to survive concurrent
/// *processes* by accident rather than by design: pid plus a monotonic counter
/// plus the clock's nanoseconds is enough that two runs do not collide, and a
/// leftover file from a crash is inert because nothing ever reads `tmp/`.
fn temp_name(kind: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.subsec_nanos())
        .unwrap_or(0);
    let count = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{kind}.{}.{count}.{nanos}.tmp", std::process::id())
}

/// Write `bytes` to `target` atomically, creating the parent directory.
///
/// `tmp_dir` must be on the same filesystem as `target`; callers pass the
/// store's own `tmp/`.
pub fn write_atomic(tmp_dir: &Path, target: &Path, bytes: &[u8]) -> Result<()> {
    fs::create_dir_all(tmp_dir).map_err(|error| StoreError::io(tmp_dir, error))?;
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|error| StoreError::io(parent, error))?;
    }

    let temporary = tmp_dir.join(temp_name("write"));
    {
        let mut file =
            File::create(&temporary).map_err(|error| StoreError::io(&temporary, error))?;
        file.write_all(bytes)
            .map_err(|error| StoreError::io(&temporary, error))?;
        file.sync_all()
            .map_err(|error| StoreError::io(&temporary, error))?;
    }

    if let Err(error) = fs::rename(&temporary, target) {
        let _ = fs::remove_file(&temporary);
        return Err(StoreError::io(target, error));
    }

    if let Some(parent) = target.parent() {
        sync_directory(parent)?;
    }
    Ok(())
}

/// fsync a directory, which is what makes a rename durable rather than merely
/// visible to this boot.
pub fn sync_directory(directory: &Path) -> Result<()> {
    let handle = File::open(directory).map_err(|error| StoreError::io(directory, error))?;
    // A directory fsync is not portable to every platform; on the ones where it
    // is refused, the rename is still atomic, only less durable across a power
    // cut. That is a weaker guarantee, not a wrong one, so it is not fatal.
    match handle.sync_all() {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::InvalidInput => Ok(()),
        Err(error) => Err(StoreError::io(directory, error)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_through_a_temporary_and_leaves_none_behind() {
        let root = tempfile::tempdir().unwrap();
        let tmp = root.path().join("tmp");
        let target = root.path().join("objects/ab/cd");
        write_atomic(&tmp, &target, b"loom").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"loom");
        assert_eq!(fs::read_dir(&tmp).unwrap().count(), 0);
    }

    #[test]
    fn overwrites_in_place_without_a_window_of_absence() {
        let root = tempfile::tempdir().unwrap();
        let tmp = root.path().join("tmp");
        let target = root.path().join("index/types.jsonl");
        write_atomic(&tmp, &target, b"first").unwrap();
        write_atomic(&tmp, &target, b"second").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"second");
    }

    #[test]
    fn temporary_names_do_not_repeat() {
        let names: std::collections::HashSet<String> =
            (0..64).map(|_| temp_name("write")).collect();
        assert_eq!(names.len(), 64);
    }
}
