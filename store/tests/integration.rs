//! End-to-end tests: the library over a real directory, and the binary over a
//! real process boundary.
//!
//! The unit tests in `src/` check pieces. These check the properties the plan
//! actually promises — that a crash cannot leave a torn object, that `fsck`
//! catches a corrupted object *and* an edited sidecar, that a miss is exit 3
//! with a hash in it, and that a store deleted and re-seeded from the pinned
//! corpus comes back byte-identical.
//!
//! The corpus-seeding tests shell out to the Python oracle at `../prototype`,
//! which is a dependency `task setup` verifies. They are the only tests here
//! that leave the crate, and they are the ones worth the cost: a store that
//! passes every synthetic test and cannot admit the 47 real objects has proven
//! nothing.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use loom_store::error::exit;
use loom_store::hash::ObjectHash;
use loom_store::store::PutOutcome;
use loom_store::Store;
use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

fn new_store() -> (tempfile::TempDir, Store) {
    let root = tempfile::tempdir().unwrap();
    let (store, created) = Store::init(root.path(), serde_json::Map::new()).unwrap();
    assert!(created);
    (root, store)
}

/// A well-formed sidecar for arbitrary bytes. The store does not interpret
/// object bytes, so a synthetic object is a completely faithful test subject
/// for everything except admission.
fn sidecar_for(object: &[u8], kind: &str, name: &str, sequence: u64, deps: &[String]) -> Vec<u8> {
    let hash = ObjectHash::of(object).to_string();
    let type_surface = match kind {
        "definition" | "extern" => json!("(fn Bool () Bool)"),
        _ => Value::Null,
    };
    let surface = match kind {
        "definition" => json!("(def (fn Bool () Bool) (lam Bool (var 0)))"),
        _ => Value::Null,
    };
    let body = json!({
        "schema": 1,
        "hash": hash,
        "kind": kind,
        "name": name,
        "type_surface": type_surface,
        "deps": deps,
        "surface": surface,
        "object": Value::Null,
        "spec": "a synthetic fixture",
        "sequence": sequence,
        "provenance": {"origin": "generated", "source": "tests", "admitter": "tests"},
        "validation": {"layers": ["parser"], "contracts": {"parser": "1.0"}, "obligations": 0},
    });
    let mut bytes = serde_json::to_vec_pretty(&body).unwrap();
    bytes.push(b'\n');
    bytes
}

fn put(store: &Store, object: &[u8], kind: &str, name: &str, sequence: u64) -> ObjectHash {
    let sidecar = sidecar_for(object, kind, name, sequence, &[]);
    store.put(object, &sidecar).unwrap().0
}

fn binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_loom-store"))
}

fn prototype() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("prototype")
}

/// Run the CLI and return (exit code, parsed stdout JSON).
fn cli(root: &Path, arguments: &[&str]) -> (i32, Value) {
    let output = raw_cli(root, arguments);
    let text = String::from_utf8_lossy(&output.stdout);
    let line = text.lines().last().unwrap_or("");
    let value: Value = serde_json::from_str(line)
        .unwrap_or_else(|error| panic!("stdout was not one JSON line ({error}): {text:?}"));
    (output.status.code().unwrap_or(-1), value)
}

fn raw_cli(root: &Path, arguments: &[&str]) -> Output {
    Command::new(binary())
        .arg("--store")
        .arg(root)
        .arg("--prototype")
        .arg(prototype())
        .args(arguments)
        .output()
        .expect("failed to run loom-store")
}

/// Every file under `root`, relative path to contents. The comparison the
/// plan's "deleted and re-seeded is byte-identical" criterion needs.
fn snapshot(root: &Path, skip: &[&str]) -> std::collections::BTreeMap<String, Vec<u8>> {
    let mut found = std::collections::BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        for entry in fs::read_dir(&directory).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let relative = path
                .strip_prefix(root)
                .unwrap()
                .to_string_lossy()
                .to_string();
            if skip.iter().any(|prefix| relative.starts_with(prefix)) {
                continue;
            }
            if path.is_dir() {
                stack.push(path);
            } else {
                found.insert(relative, fs::read(&path).unwrap());
            }
        }
    }
    found
}

// ---------------------------------------------------------------------------
// the library over a real directory
// ---------------------------------------------------------------------------

#[test]
fn put_then_get_returns_the_same_bytes() {
    let (_root, store) = new_store();
    let object = b"canonical object bytes".to_vec();
    let hash = put(&store, &object, "definition", "corpus/x", 0);
    assert_eq!(store.get(&hash).unwrap(), object);
}

#[test]
fn putting_the_same_object_twice_reports_exists() {
    let (_root, store) = new_store();
    let object = b"identical".to_vec();
    let sidecar = sidecar_for(&object, "definition", "corpus/x", 0, &[]);
    assert_eq!(store.put(&object, &sidecar).unwrap().1, PutOutcome::Written);
    assert_eq!(store.put(&object, &sidecar).unwrap().1, PutOutcome::Exists);
    assert_eq!(store.rows().unwrap().len(), 1);
}

#[test]
fn a_missing_hash_is_a_typed_miss_not_a_fault() {
    let (_root, store) = new_store();
    let absent = ObjectHash::parse(&"ab".repeat(32)).unwrap();
    let error = store.get(&absent).unwrap_err();
    assert_eq!(error.class(), "not_found");
    assert_eq!(error.exit_code(), exit::NOT_FOUND);
    assert_eq!(error.to_json()["hash"], "ab".repeat(32));
}

#[test]
fn a_sidecar_that_claims_a_different_hash_is_refused_at_put() {
    let (_root, store) = new_store();
    let sidecar = sidecar_for(b"one", "definition", "corpus/x", 0, &[]);
    let error = store.put(b"two", &sidecar).unwrap_err();
    assert_eq!(error.class(), "integrity");
}

#[test]
fn a_corrupted_object_byte_is_caught_on_read_and_by_fsck() {
    let (root, store) = new_store();
    let hash = put(
        &store,
        b"canonical object bytes",
        "definition",
        "corpus/x",
        0,
    );
    assert!(store.fsck().unwrap().healthy());

    let path = store.layout().object_path(&hash);
    let mut bytes = fs::read(&path).unwrap();
    bytes[0] ^= 0xff;
    fs::write(&path, &bytes).unwrap();

    let error = store.get(&hash).unwrap_err();
    assert_eq!(error.class(), "integrity");
    assert_eq!(error.exit_code(), exit::INTEGRITY);

    let report = store.fsck().unwrap();
    assert!(!report.healthy());
    assert!(report
        .problems
        .iter()
        .any(|problem| problem.kind == "object_corrupt"
            && problem.hash.as_deref() == Some(hash.to_string().as_str())));
    drop(root);
}

#[test]
fn an_edited_sidecar_field_the_store_does_not_interpret_is_still_caught() {
    // `spec` is never read by any query the store answers. Without the
    // sidecar digest in the index, an edit to it would be invisible — which is
    // why that column exists.
    let (_root, store) = new_store();
    let hash = put(&store, b"object", "definition", "corpus/x", 0);
    let path = store.layout().sidecar_path(&hash);
    let text = fs::read_to_string(&path)
        .unwrap()
        .replace("a synthetic fixture", "tampered");
    fs::write(&path, text).unwrap();

    let report = store.fsck().unwrap();
    assert!(!report.healthy());
    assert!(report
        .problems
        .iter()
        .any(|problem| problem.kind == "index_diverged"));
}

#[test]
fn a_deleted_index_is_rebuilt_losslessly() {
    let (_root, store) = new_store();
    for (index, name) in ["a", "b", "c"].iter().enumerate() {
        put(&store, name.as_bytes(), "definition", name, index as u64);
    }
    let before = fs::read(store.layout().index_file()).unwrap();
    fs::remove_file(store.layout().index_file()).unwrap();
    assert!(!store.fsck().unwrap().healthy());

    assert_eq!(store.reindex().unwrap(), 3);
    assert_eq!(fs::read(store.layout().index_file()).unwrap(), before);
    assert!(store.fsck().unwrap().healthy());
}

#[test]
fn an_object_without_a_sidecar_is_reported_as_an_orphan() {
    // The visible shape of a crash between put's first and second write.
    let (_root, store) = new_store();
    let hash = put(&store, b"object", "definition", "corpus/x", 0);
    fs::remove_file(store.layout().sidecar_path(&hash)).unwrap();
    let report = store.fsck().unwrap();
    assert!(report
        .problems
        .iter()
        .any(|problem| problem.kind == "object_orphan"));
}

#[test]
fn no_index_row_can_reference_an_absent_object() {
    // The invariant R2 states, checked from the other direction: remove the
    // object and the index row is now a lie, and fsck says so.
    let (_root, store) = new_store();
    let hash = put(&store, b"object", "definition", "corpus/x", 0);
    fs::remove_file(store.layout().object_path(&hash)).unwrap();
    let report = store.fsck().unwrap();
    assert!(report
        .problems
        .iter()
        .any(|problem| problem.kind == "object_missing"));
}

#[test]
fn queries_read_the_index_and_refuse_kinds_they_do_not_apply_to() {
    let (_root, store) = new_store();
    let definition = put(&store, b"definition", "definition", "corpus/x", 0);
    let data = put(&store, b"data", "data", "List", 1);
    let dependent = {
        let object = b"dependent".to_vec();
        let sidecar = sidecar_for(
            &object,
            "definition",
            "corpus/y",
            2,
            &[definition.to_string()],
        );
        store.put(&object, &sidecar).unwrap().0
    };

    assert_eq!(store.type_of(&definition).unwrap().1, "(fn Bool () Bool)");
    assert_eq!(store.type_of(&data).unwrap_err().class(), "not_applicable");
    assert_eq!(
        store.type_of(&data).unwrap_err().exit_code(),
        exit::NOT_APPLICABLE
    );

    assert_eq!(
        store.deps(&dependent).unwrap(),
        vec![definition.to_string()]
    );
    assert_eq!(
        store.rdeps(&definition).unwrap(),
        vec![dependent.to_string()]
    );
    assert!(store.rdeps(&data).unwrap().is_empty());

    assert_eq!(store.list(None).unwrap().len(), 3);
    assert_eq!(store.list(Some("data")).unwrap().len(), 1);
    assert_eq!(store.list(Some("wombat")).unwrap_err().class(), "layout");

    let prefix = &definition.to_string()[..4];
    assert!(store
        .prefix(prefix)
        .unwrap()
        .contains(&definition.to_string()));
    assert!(store.prefix(&"f".repeat(64)).unwrap().is_empty());
    assert_eq!(store.prefix("NOPE").unwrap_err().class(), "bad_hash");
}

#[test]
fn the_index_file_does_not_depend_on_insertion_order() {
    let (_first_root, first) = new_store();
    let (_second_root, second) = new_store();
    let objects: Vec<Vec<u8>> = (0..8).map(|n| format!("object {n}").into_bytes()).collect();
    for (index, object) in objects.iter().enumerate() {
        put(&first, object, "definition", "x", index as u64);
    }
    for (index, object) in objects.iter().enumerate().rev() {
        put(&second, object, "definition", "x", index as u64);
    }
    assert_eq!(
        fs::read(first.layout().index_file()).unwrap(),
        fs::read(second.layout().index_file()).unwrap()
    );
}

// ---------------------------------------------------------------------------
// the binary over a real process boundary
// ---------------------------------------------------------------------------

#[test]
fn the_cli_reports_a_miss_on_stdout_as_json_and_exits_three() {
    let root = tempfile::tempdir().unwrap();
    assert_eq!(cli(root.path(), &["init"]).0, exit::OK);
    let absent = "ab".repeat(32);
    let (code, body) = cli(root.path(), &["get", &absent]);
    assert_eq!(code, exit::NOT_FOUND);
    assert_eq!(body["error"], "not_found");
    assert_eq!(body["hash"], absent);
}

#[test]
fn the_cli_refuses_a_malformed_hash_without_touching_the_store() {
    let root = tempfile::tempdir().unwrap();
    cli(root.path(), &["init"]);
    let (code, body) = cli(root.path(), &["get", "not-a-hash"]);
    assert_eq!(code, exit::USAGE);
    assert_eq!(body["error"], "bad_hash");
}

#[test]
fn the_cli_refuses_a_directory_that_is_not_a_store() {
    let root = tempfile::tempdir().unwrap();
    let (code, body) = cli(root.path(), &["fsck"]);
    assert_eq!(code, exit::STORE);
    assert_eq!(body["error"], "layout");
}

#[test]
fn init_is_idempotent_through_the_cli() {
    let root = tempfile::tempdir().unwrap();
    assert_eq!(cli(root.path(), &["init"]).1["status"], "created");
    assert_eq!(cli(root.path(), &["init"]).1["status"], "exists");
}

#[test]
fn get_raw_writes_bytes_and_nothing_else() {
    let root = tempfile::tempdir().unwrap();
    cli(root.path(), &["init"]);
    let store = Store::open(root.path()).unwrap();
    let object = b"\x00\x01\x02 raw bytes \xff".to_vec();
    let hash = put(&store, &object, "definition", "corpus/x", 0);

    let output = raw_cli(root.path(), &["get", "--raw", &hash.to_string()]);
    assert_eq!(output.status.code(), Some(exit::OK));
    assert_eq!(output.stdout, object);
}

#[test]
fn the_seeded_corpus_admits_completely_and_fscks_clean() {
    let root = tempfile::tempdir().unwrap();
    assert_eq!(cli(root.path(), &["init", "--from-oracle"]).0, exit::OK);

    let (code, body) = cli(root.path(), &["admit", "--corpus"]);
    assert_eq!(code, exit::OK, "admit --corpus failed: {body}");
    assert_eq!(body["written"], 47);
    assert_eq!(body["exists"], 0);

    let (code, body) = cli(root.path(), &["fsck"]);
    assert_eq!(code, exit::OK, "fsck failed: {body}");
    assert_eq!(body["objects"], 47);
    assert_eq!(body["rows"], 47);

    for (kind, count) in [
        ("definition", 26),
        ("ability", 8),
        ("data", 4),
        ("extern", 9),
    ] {
        let (_, body) = cli(root.path(), &["list", "--kind", kind]);
        assert_eq!(body["count"], count, "wrong count for {kind}");
    }

    // Re-admitting is a no-op that reports it, which is conclusion 4.
    let (_, body) = cli(root.path(), &["admit", "--corpus"]);
    assert_eq!(body["written"], 0);
    assert_eq!(body["exists"], 47);

    // The store records the contract versions it was initialized under.
    let meta: Value =
        serde_json::from_slice(&fs::read(root.path().join("store.json")).unwrap()).unwrap();
    assert_eq!(meta["contracts"]["parser"], "1.0");
    assert_eq!(meta["contracts"]["typecheck"], "1.1");
}

#[test]
fn a_deleted_and_reseeded_store_is_byte_identical() {
    let first = tempfile::tempdir().unwrap();
    let second = tempfile::tempdir().unwrap();
    for root in [first.path(), second.path()] {
        assert_eq!(cli(root, &["init", "--from-oracle"]).0, exit::OK);
        assert_eq!(cli(root, &["admit", "--corpus"]).0, exit::OK);
    }
    // `tmp/` is scratch and holds nothing after a command finishes; everything
    // else — objects, sidecars, the index, store.json — must match exactly.
    assert_eq!(
        snapshot(first.path(), &["tmp"]),
        snapshot(second.path(), &["tmp"])
    );
}

#[test]
fn a_seeded_store_answers_the_read_api_the_experiment_needs() {
    let root = tempfile::tempdir().unwrap();
    cli(root.path(), &["init", "--from-oracle"]);
    cli(root.path(), &["admit", "--corpus"]);

    // corpus/bool/not, pinned in corpus_registry.MANIFEST.
    let not = "162f818f22a2d041cb823d9a4e98c98d6102eee7de83519211452c348bb1be45";

    let (code, body) = cli(root.path(), &["type", not]);
    assert_eq!(code, exit::OK);
    assert_eq!(body["type"], "(fn Bool () Bool)");

    let (code, body) = cli(root.path(), &["get", not]);
    assert_eq!(code, exit::OK);
    assert_eq!(
        body["surface"],
        "(def (fn Bool () Bool) (lam Bool (if (var 0) (lit bool false) (lit bool true))))"
    );
    assert_eq!(
        ObjectHash::parse(body["hash"].as_str().unwrap())
            .unwrap()
            .to_string(),
        not
    );

    let (_, body) = cli(root.path(), &["prefix", &not[..3]]);
    assert!(body["hashes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|hash| hash == not));

    // Bool.not is an extern; corpus/bool/not does not reference it, but
    // corpus/math/abs references I64.sub — a real edge, checked both ways.
    let sub = "d3914e25a045031ef17d33eb038ca837c40c55642ceeef902b2d046a322f00b5";
    let (_, body) = cli(root.path(), &["rdeps", sub]);
    let referrers = body["rdeps"].as_array().unwrap();
    assert!(!referrers.is_empty());
    for referrer in referrers {
        let (_, deps) = cli(root.path(), &["deps", referrer.as_str().unwrap()]);
        assert!(deps["deps"]
            .as_array()
            .unwrap()
            .iter()
            .any(|edge| edge == sub));
    }

    let (code, body) = cli(root.path(), &["export-resolver"]);
    assert_eq!(code, exit::OK);
    assert_eq!(body["objects"].as_array().unwrap().len(), 47);
    assert_eq!(body["schema"], 1);
}

#[test]
fn the_oracle_refusal_reaches_the_cli_with_its_own_error_class() {
    let root = tempfile::tempdir().unwrap();
    cli(root.path(), &["init", "--from-oracle"]);
    cli(root.path(), &["admit", "--corpus"]);

    let source = root.path().join("bad.loom.sexpr");
    // Well-formed surface, but `(var 3)` escapes every binder: a scope error.
    fs::write(&source, "(def (fn Bool () Bool) (lam Bool (var 3)))\n").unwrap();
    let (code, body) = cli(root.path(), &["admit", source.to_str().unwrap()]);
    assert_eq!(code, exit::REFUSED, "expected a refusal, got {body}");
    assert_eq!(body["error"], "refused");
    assert_eq!(body["layer"], "scope");
    assert_eq!(body["error_class"], "ScopeError");
}

#[test]
fn a_generated_definition_admits_against_the_stores_own_contents() {
    let root = tempfile::tempdir().unwrap();
    cli(root.path(), &["init", "--from-oracle"]);
    cli(root.path(), &["admit", "--corpus"]);

    // Not in the corpus, and it references nothing — so it admits on the
    // store's own resolver export rather than on the pinned registry.
    let source = root.path().join("new.loom.sexpr");
    fs::write(&source, "(def (fn I64 () I64) (lam I64 (var 0)))\n").unwrap();
    let (code, body) = cli(
        root.path(),
        &["admit", "--name", "generated/id", source.to_str().unwrap()],
    );
    assert_eq!(code, exit::OK, "admit failed: {body}");
    assert_eq!(body["written"], 1);

    let (_, body) = cli(root.path(), &["list"]);
    assert_eq!(body["count"], 48);
    assert_eq!(cli(root.path(), &["fsck"]).0, exit::OK);

    // The corpus loop's guardrail, from the read API alone: `list --kind
    // definition` separates the one generated definition from the 26 curated
    // ones on the oracle's `provenance.origin`, with no naming convention and
    // no second lookup involved.
    let (_, body) = cli(root.path(), &["list", "--kind", "definition"]);
    let rows = body["objects"].as_array().unwrap();
    let generated: Vec<&Value> = rows
        .iter()
        .filter(|row| row["origin"] == "generated")
        .collect();
    assert_eq!(rows.len(), 27);
    assert_eq!(generated.len(), 1);
    assert_eq!(generated[0]["name"], "generated/id");
    assert_eq!(
        rows.iter()
            .filter(|row| row["origin"] == "transpiled")
            .count(),
        26
    );
}
