//! Name-paths and namespaces, and the one spelling each has on disk.
//!
//! SPEC §5.3 gives no grammar for a name-path beyond "name-paths live in
//! namespaces" and §5.3.2's reserved `POLICY` leaf, so this module fixes the
//! narrowest grammar that makes the *store's* invariants hold, and says so
//! rather than leaving it implicit:
//!
//! * A name-path is one or more `/`-separated segments.
//! * A segment is non-empty, contains no `/` and no control character, and is
//!   neither `.` nor `..` — the three shapes that would let a name-path escape
//!   the directory it names or collide with a directory entry that is not one.
//! * The **namespace** is every segment but the last; the root namespace is the
//!   empty string. The **leaf** is the last segment.
//!
//! NFC normalization (§2.2) is *not* checked here. The oracle checks it, along
//! with everything else semantic, and a non-NFC path is therefore refused at
//! `bind` rather than at the CLI. That split is deliberate: normalizing text is
//! the validator's job, and duplicating it in Rust would create the second
//! opinion the whole seam exists to avoid.
//!
//! ## The one spelling on disk
//!
//! A namespace becomes one filename stem, not a directory tree, so that
//! enumerating namespaces is one `read_dir` and a namespace can never be
//! shadowed by a directory of the same name. The encoding is minimal and
//! injective — `%` becomes `%25`, `/` becomes `%2F` — with the root namespace
//! spelled `%`, which no non-empty namespace can encode to.

use crate::error::{Result, StoreError};

/// The reserved leaf name of §5.3.2. A binding whose leaf is this targets a
/// policy object (kind 6); every other binding targets a def object (kind 0).
pub const POLICY_LEAF: &str = "POLICY";

/// The filename stem of the root namespace. `%` is never the encoding of a
/// non-empty namespace, because encoding only ever emits `%` followed by two
/// hex digits.
const ROOT_STEM: &str = "%";

/// A validated name-path: at least one segment, and a leaf.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct NamePath {
    text: String,
    /// Byte offset of the leaf inside `text`.
    leaf_at: usize,
}

impl NamePath {
    pub fn parse(text: &str) -> Result<Self> {
        validate_segments(text, text)?;
        let leaf_at = match text.rfind('/') {
            Some(index) => index + 1,
            None => 0,
        };
        Ok(NamePath {
            text: text.to_string(),
            leaf_at,
        })
    }

    pub fn as_str(&self) -> &str {
        &self.text
    }

    /// Every segment but the last. The root namespace is `""`.
    pub fn namespace(&self) -> &str {
        if self.leaf_at == 0 {
            ""
        } else {
            &self.text[..self.leaf_at - 1]
        }
    }

    pub fn leaf(&self) -> &str {
        &self.text[self.leaf_at..]
    }

    pub fn is_policy(&self) -> bool {
        self.leaf() == POLICY_LEAF
    }
}

impl std::fmt::Display for NamePath {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.text)
    }
}

/// A namespace on its own — what `lease` and `names --ns` take. The root
/// namespace is the empty string, which is why this is a free function rather
/// than a `NamePath::parse` call with a special case.
pub fn validate_namespace(namespace: &str) -> Result<()> {
    if namespace.is_empty() {
        return Ok(());
    }
    validate_segments(namespace, namespace)
}

fn validate_segments(text: &str, whole: &str) -> Result<()> {
    if text.is_empty() {
        return Err(bad(whole, "a name-path needs at least one segment"));
    }
    for segment in text.split('/') {
        if segment.is_empty() {
            return Err(bad(whole, "empty segment"));
        }
        if segment == "." || segment == ".." {
            return Err(bad(whole, format!("segment {segment:?} is reserved")));
        }
        if let Some(character) = segment.chars().find(|c| c.is_control()) {
            return Err(bad(
                whole,
                format!("segment contains the control character {:?}", character),
            ));
        }
    }
    Ok(())
}

fn bad(text: &str, detail: impl Into<String>) -> StoreError {
    StoreError::BadName {
        text: text.to_string(),
        detail: detail.into(),
    }
}

/// The namespace and every namespace enclosing it, nearest first, ending at
/// root. This is the walk §5.3.2's resolution does.
pub fn ancestors(namespace: &str) -> Vec<String> {
    let mut found = vec![namespace.to_string()];
    let mut current = namespace;
    while let Some(index) = current.rfind('/') {
        current = &current[..index];
        found.push(current.to_string());
    }
    if !namespace.is_empty() {
        found.push(String::new());
    }
    found
}

/// Whether `candidate` encloses `namespace`, or is it.
pub fn encloses(candidate: &str, namespace: &str) -> bool {
    candidate.is_empty()
        || candidate == namespace
        || namespace.starts_with(candidate) && namespace[candidate.len()..].starts_with('/')
}

/// The filename stem a namespace's logs are filed under.
pub fn encode(namespace: &str) -> String {
    if namespace.is_empty() {
        return ROOT_STEM.to_string();
    }
    let mut out = String::with_capacity(namespace.len());
    for character in namespace.chars() {
        match character {
            '%' => out.push_str("%25"),
            '/' => out.push_str("%2F"),
            other => out.push(other),
        }
    }
    out
}

/// The inverse of [`encode`]. `None` for a stem no encoding produces, which is
/// how `fsck` tells a log file from a stray file someone dropped in the
/// directory.
pub fn decode(stem: &str) -> Option<String> {
    if stem == ROOT_STEM {
        return Some(String::new());
    }
    let mut out = String::with_capacity(stem.len());
    let mut characters = stem.chars();
    while let Some(character) = characters.next() {
        if character != '%' {
            out.push(character);
            continue;
        }
        let escape: String = characters.by_ref().take(2).collect();
        match escape.as_str() {
            "25" => out.push('%'),
            "2F" => out.push('/'),
            _ => return None,
        }
    }
    if out.is_empty() {
        return None;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_name_path_splits_into_a_namespace_and_a_leaf() {
        let path = NamePath::parse("stats/inner/median").unwrap();
        assert_eq!(path.namespace(), "stats/inner");
        assert_eq!(path.leaf(), "median");
        assert!(!path.is_policy());

        let root = NamePath::parse("median").unwrap();
        assert_eq!(root.namespace(), "");
        assert_eq!(root.leaf(), "median");
    }

    #[test]
    fn the_reserved_leaf_is_recognized_at_every_depth() {
        assert!(NamePath::parse("POLICY").unwrap().is_policy());
        assert!(NamePath::parse("stats/POLICY").unwrap().is_policy());
        // Reserved as a *leaf*; as an interior segment it is an ordinary name.
        assert!(!NamePath::parse("POLICY/x").unwrap().is_policy());
    }

    #[test]
    fn the_three_shapes_that_could_escape_a_directory_are_refused() {
        for text in ["", "a//b", "a/./b", "a/../b", "a/b/", "/a", "a/\u{7}/b"] {
            assert_eq!(
                NamePath::parse(text).unwrap_err().class(),
                "bad_name",
                "{text:?} should not parse"
            );
        }
    }

    #[test]
    fn encoding_is_injective_and_the_root_has_a_stem_nothing_else_can_take() {
        for namespace in ["", "stats", "stats/inner", "a%b", "a/b/c", "100%"] {
            assert_eq!(decode(&encode(namespace)).as_deref(), Some(namespace));
        }
        assert_eq!(encode(""), "%");
        assert_eq!(encode("stats/inner"), "stats%2Finner");
        // Nothing encodes to a stem with a bare or malformed escape.
        assert_eq!(decode("a%zz"), None);
        assert_eq!(decode("types.jsonl"), Some("types.jsonl".to_string()));
    }

    #[test]
    fn ancestors_walk_from_the_namespace_up_to_root() {
        assert_eq!(
            ancestors("a/b/c"),
            vec!["a/b/c".to_string(), "a/b".into(), "a".into(), "".into()]
        );
        assert_eq!(ancestors(""), vec![String::new()]);
    }

    #[test]
    fn enclosure_is_by_segment_not_by_prefix() {
        assert!(encloses("stats", "stats/inner"));
        assert!(encloses("", "anything/at/all"));
        assert!(encloses("stats", "stats"));
        // `stat` is a prefix of `stats` as text but encloses nothing in it.
        assert!(!encloses("stat", "stats/inner"));
    }
}
