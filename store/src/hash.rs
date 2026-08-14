//! The store's one native invariant: a 32-byte SHA-256 name for opaque bytes.
//!
//! Everything semantic about an object arrives from the Python oracle in a
//! sidecar. This module is the part the store owns outright, so it is the part
//! that is enforced here rather than trusted: `Hash::of(bytes)` on write and on
//! read, compared against the name the caller claimed.

use std::fmt;

use sha2::{Digest, Sha256};

use crate::error::StoreError;

/// A 32-byte content address. Displayed as 64 lowercase hex digits, which is
/// also the on-disk spelling and the wire spelling — there is deliberately only
/// one rendering of a hash anywhere in the store.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ObjectHash([u8; 32]);

impl ObjectHash {
    /// The hash of these bytes. The only way an `ObjectHash` is ever derived
    /// from content.
    pub fn of(bytes: &[u8]) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let digest = hasher.finalize();
        let mut out = [0u8; 32];
        out.copy_from_slice(&digest);
        ObjectHash(out)
    }

    /// Parse 64 lowercase hex digits. Uppercase is refused rather than
    /// normalized: two spellings of one name is how a content-addressed store
    /// grows duplicate rows.
    pub fn parse(text: &str) -> Result<Self, StoreError> {
        if text.len() != 64 {
            return Err(StoreError::BadHash {
                text: text.to_string(),
                detail: format!("expected 64 hex digits, got {}", text.len()),
            });
        }
        let mut out = [0u8; 32];
        for (index, chunk) in text.as_bytes().chunks_exact(2).enumerate() {
            let high = hex_nibble(chunk[0], text)?;
            let low = hex_nibble(chunk[1], text)?;
            out[index] = (high << 4) | low;
        }
        Ok(ObjectHash(out))
    }

    /// The two-hex fan-out directory and the 62-hex leaf, in that order.
    pub fn fanout(&self) -> (String, String) {
        let hex = self.to_string();
        (hex[..2].to_string(), hex[2..].to_string())
    }
}

fn hex_nibble(byte: u8, text: &str) -> Result<u8, StoreError> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(StoreError::BadHash {
            text: text.to_string(),
            detail: "expected lowercase hex digits only".to_string(),
        }),
    }
}

impl fmt::Display for ObjectHash {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

impl fmt::Debug for ObjectHash {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "ObjectHash({self})")
    }
}

/// A hex prefix a caller may query with — the masker's reference-hash trie is
/// seeded from `prefix` queries, so a prefix is a first-class input rather than
/// a substring match applied after the fact.
pub fn is_hex_prefix(text: &str) -> bool {
    !text.is_empty()
        && text.len() <= 64
        && text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashes_the_empty_string_to_the_published_vector() {
        assert_eq!(
            ObjectHash::of(b"").to_string(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn round_trips_through_hex() {
        let hash = ObjectHash::of(b"loom");
        assert_eq!(ObjectHash::parse(&hash.to_string()).unwrap(), hash);
    }

    #[test]
    fn refuses_uppercase_and_wrong_lengths() {
        let upper = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855";
        assert!(ObjectHash::parse(upper).is_err());
        assert!(ObjectHash::parse("abc").is_err());
    }

    #[test]
    fn splits_into_git_style_fanout() {
        let (directory, leaf) = ObjectHash::of(b"").fanout();
        assert_eq!(directory, "e3");
        assert_eq!(leaf.len(), 62);
    }

    #[test]
    fn accepts_only_lowercase_hex_prefixes() {
        assert!(is_hex_prefix("00ff"));
        assert!(!is_hex_prefix(""));
        assert!(!is_hex_prefix("00FF"));
        assert!(!is_hex_prefix(&"0".repeat(65)));
    }
}
