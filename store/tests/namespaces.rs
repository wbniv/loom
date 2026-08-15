//! End-to-end tests for namespaces: the lease protocol (§5.3.3), binding
//! records (§5.3), and policy-gated admission (§5.3.2).
//!
//! These are the plan's verification steps 3–6 as executable tests. Every one
//! of them shells out to the Python oracle at `../prototype`, because that is
//! where §5.3.2 lives — a namespaces test that stubbed the oracle would prove
//! the store can append lines, which is not the property in question.
//!
//! **On sleeping.** Two tests sleep, for 260 ms each. §5.3.3 makes the store's
//! own clock the arbiter of expiry, so the only honest way to test expiry is to
//! let a short lease actually expire; a `--now-millis` override would be a back
//! door into the one component the design says is the arbiter, and a test that
//! used it would no longer be testing it. Both tests reach the short window by
//! *renewing* down to 150 ms rather than acquiring at 150 ms, so nothing
//! depends on how long a Python subprocess takes to start.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use loom_store::error::exit;
use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const ALICE: &str = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const BOB: &str = "b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0";
const DEFAULT_POLICY: &str = "901f33bdd7bcb96a53f560673a2cd437d00328d1065b7f60ef0b05340735299c";

fn binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_loom-store"))
}

fn prototype() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("prototype")
}

fn cli(root: &Path, arguments: &[&str]) -> (i32, Value) {
    let output = Command::new(binary())
        .arg("--store")
        .arg(root)
        .arg("--prototype")
        .arg(prototype())
        .args(arguments)
        .output()
        .expect("failed to run loom-store");
    let text = String::from_utf8_lossy(&output.stdout);
    let line = text.lines().last().unwrap_or("");
    let value: Value = serde_json::from_str(line)
        .unwrap_or_else(|error| panic!("stdout was not one JSON line ({error}): {text:?}"));
    (output.status.code().unwrap_or(-1), value)
}

/// An initialized store with the default policy preloaded and one real
/// definition in it, whose hash is returned.
fn store_with_a_definition() -> (tempfile::TempDir, String) {
    let root = tempfile::tempdir().unwrap();
    let (code, body) = cli(root.path(), &["init", "--from-oracle"]);
    assert_eq!(code, exit::OK, "init failed: {body}");
    assert_eq!(body["default_policy"], DEFAULT_POLICY);

    let source = root.path().join("id.loom.sexpr");
    fs::write(&source, "(def (fn I64 () I64) (lam I64 (var 0)))\n").unwrap();
    let (code, body) = cli(
        root.path(),
        &["admit", "--name", "id", source.to_str().unwrap()],
    );
    assert_eq!(code, exit::OK, "admit failed: {body}");
    let hash = body["objects"][0]["hash"].as_str().unwrap().to_string();
    (root, hash)
}

/// Land a policy object built from §5.3.1 keys, and return its hash.
fn admit_policy(root: &Path, keys: Value) -> String {
    let entries: Vec<Value> = keys
        .as_object()
        .unwrap()
        .iter()
        .map(|(key, value)| json!([key.parse::<u64>().unwrap(), value]))
        .collect();
    let path = root.join(format!("policy.{}.json", entries.len() * 7 + rand_ish()));
    fs::write(
        &path,
        serde_json::to_vec(&json!([6, {"m": entries}])).unwrap(),
    )
    .unwrap();
    let (code, body) = cli(root, &["admit-policy", path.to_str().unwrap()]);
    assert_eq!(code, exit::OK, "admit-policy failed: {body}");
    body["objects"][0]["hash"].as_str().unwrap().to_string()
}

/// Enough variation to keep two policy files in one test from colliding. Not a
/// random number generator, and does not need to be one.
fn rand_ish() -> usize {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    NEXT.fetch_add(1, Ordering::Relaxed)
}

fn acquire(root: &Path, namespace: &str, principal: &str, ttl: u64) -> (i32, Value) {
    cli(
        root,
        &[
            "lease",
            "acquire",
            namespace,
            "--principal",
            principal,
            "--ttl-millis",
            &ttl.to_string(),
        ],
    )
}

fn bind(root: &Path, name: &str, def: &str, policy_ref: &str, fence: u64) -> (i32, Value) {
    cli(
        root,
        &[
            "bind",
            name,
            "--def",
            def,
            "--policy-ref",
            policy_ref,
            "--fence",
            &fence.to_string(),
        ],
    )
}

// ---------------------------------------------------------------------------
// step 3 — the two-writer race
// ---------------------------------------------------------------------------

#[test]
fn two_writers_are_serialized_by_the_fence_and_never_by_the_clock() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();

    // A takes the lease and binds under it. The TTL is generous because each
    // step below is a subprocess that shells to the oracle; the *expiry* half
    // of this test is set up by a short renewal further down, so nothing here
    // depends on how fast Python starts.
    let (code, granted) = acquire(root, "stats", ALICE, 30_000);
    assert_eq!(code, exit::OK, "A's acquire failed: {granted}");
    assert_eq!(granted["fence"], 1);
    let (code, bound) = bind(root, "stats/median", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::OK, "A's bind failed: {bound}");
    assert_eq!(bound["seq"], 1);

    // B is refused while A holds it, and told exactly who holds it and until
    // when — a poll-based caller (§5.3.3 has no queue) needs both.
    let (code, refused) = acquire(root, "stats", BOB, 30_000);
    assert_eq!(code, exit::LEASE, "B should have been refused: {refused}");
    assert_eq!(refused["error"], "lease_refused");
    assert_eq!(refused["reason"], "held");
    assert_eq!(refused["holder"], ALICE);
    assert_eq!(refused["fence"], 1);
    assert!(refused["expires_millis"].as_u64().unwrap() > 0);

    // A shortens its own lease, then lets it lapse. Lazy expiry: no reaper
    // runs, the lease simply becomes acquirable once the store's clock passes
    // the expiry it recorded.
    let (code, renewed) = cli(
        root,
        &[
            "lease",
            "renew",
            "stats",
            "--fence",
            "1",
            "--ttl-millis",
            "150",
        ],
    );
    assert_eq!(code, exit::OK, "{renewed}");
    std::thread::sleep(Duration::from_millis(260));
    let (code, granted) = acquire(root, "stats", BOB, 60_000);
    assert_eq!(code, exit::OK, "B's acquire after expiry failed: {granted}");
    assert_eq!(granted["fence"], 2, "the next grant increments the fence");
    assert_eq!(granted["principal"], BOB);

    // A's late bind fails the fence check regardless of what A believes about
    // time. This is L2: correctness comes from fencing, not from clocks.
    let (code, refused) = bind(root, "stats/other", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::LEASE, "A's late bind should fail: {refused}");
    assert_eq!(refused["reason"], "fence");
    assert_eq!(refused["fence"], 2);
    assert_eq!(refused["presented_fence"], 1);

    // And nothing landed: the namespace still has A's one binding.
    let (_, names) = cli(root, &["names", "--ns", "stats"]);
    assert_eq!(names["count"], 1);
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn simultaneous_acquisitions_of_a_free_namespace_produce_exactly_one_holder() {
    // The property §5.3.3 states outright — a store "can never admit two
    // writers" — under the interleaving that actually threatens it: several
    // processes folding the same empty log at the same time and all computing
    // fence 1. Folding cannot decide this; the `O_EXCL` fence claim can, and
    // this is the test that says so.
    let (root, _definition) = store_with_a_definition();
    let root = root.path().to_path_buf();

    let winners: Vec<(i32, Value)> = std::thread::scope(|scope| {
        let handles: Vec<_> = [ALICE, BOB, ALICE, BOB]
            .into_iter()
            .map(|principal| {
                let root = root.clone();
                scope.spawn(move || acquire(&root, "contended", principal, 60_000))
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect()
    });

    let granted: Vec<_> = winners
        .iter()
        .filter(|(code, _)| *code == exit::OK)
        .collect();
    assert_eq!(
        granted.len(),
        1,
        "exactly one acquisition may be granted, got {winners:?}"
    );
    assert_eq!(granted[0].1["fence"], 1);
    for (code, body) in winners.iter().filter(|(code, _)| *code != exit::OK) {
        assert_eq!(
            *code,
            exit::LEASE,
            "a loser must be a lease refusal: {body}"
        );
    }

    // One acquire event in the log, and the fold agrees with it.
    let text = fs::read_to_string(lease_log(&root, "contended")).unwrap();
    assert_eq!(text.lines().count(), 1, "the log carries one acquisition");
    assert_eq!(cli(&root, &["fsck"]).0, exit::OK);
}

#[test]
fn concurrent_binds_under_one_fence_never_share_a_seq() {
    // The fence answers "who may write"; it says nothing about "one at a
    // time". A single holder is free to run several `bind` calls in
    // parallel — different threads of the same agent, say — and each one
    // reads the log's current length before any of them has appended. Left
    // alone, all four would read length 0 and all four would propose seq 1:
    // the duplicate `binding_seq_gap` fsck used to merely *detect*. `bind`
    // now claims its `seq` via `O_CREAT|O_EXCL` before appending (mirroring
    // `state::claim_fence`), so this is the test that the race is actually
    // *prevented*, not just diagnosable after the fact.
    let (root, definition) = store_with_a_definition();
    let root = root.path().to_path_buf();

    assert_eq!(acquire(&root, "stats", ALICE, 60_000).0, exit::OK);

    // Four different names under the one held fence, so nothing here also
    // exercises rule 5 (monotone assurance against a previous binding) —
    // this test is isolated to the seq claim.
    let names = ["stats/w", "stats/x", "stats/y", "stats/z"];
    let results: Vec<(i32, Value)> = std::thread::scope(|scope| {
        let handles: Vec<_> = names
            .into_iter()
            .map(|name| {
                let root = root.clone();
                let definition = definition.clone();
                scope.spawn(move || bind(&root, name, &definition, DEFAULT_POLICY, 1))
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect()
    });

    for (code, body) in &results {
        assert_eq!(
            *code,
            exit::OK,
            "every bind under a valid, unexpired fence \
            held by its own caller should be admitted: {body}"
        );
    }

    let mut seqs: Vec<u64> = results
        .iter()
        .map(|(_, body)| body["seq"].as_u64().unwrap())
        .collect();
    seqs.sort_unstable();
    assert_eq!(
        seqs,
        vec![1, 2, 3, 4],
        "four successful binds must claim exactly the four seqs 1..4, once each, got {seqs:?}"
    );

    // The log itself agrees: four lines, four distinct seqs, and fsck's
    // seq-regression and seq-unissued checks both pass over it.
    let text = fs::read_to_string(binding_log(&root, "stats")).unwrap();
    assert_eq!(text.lines().count(), 4, "one line per bind, no duplicates");
    assert_eq!(cli(&root, &["fsck"]).0, exit::OK);
}

#[test]
fn a_released_or_expired_holder_cannot_renew_or_bind_but_the_log_still_shows_it() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();

    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);
    assert_eq!(
        bind(root, "stats/a", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );

    let (code, released) = cli(root, &["lease", "release", "stats", "--fence", "1"]);
    assert_eq!(code, exit::OK, "release failed: {released}");
    assert_eq!(released["held"], false);
    assert_eq!(released["released"], true);
    // The fence stays in place, so a late proposal fails the check rather than
    // resolving against nothing.
    assert_eq!(released["fence"], 1);

    let (code, refused) = bind(root, "stats/b", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::LEASE, "{refused}");
    assert_eq!(refused["reason"], "fence");

    let (code, refused) = cli(
        root,
        &[
            "lease",
            "renew",
            "stats",
            "--fence",
            "1",
            "--ttl-millis",
            "1000",
        ],
    );
    assert_eq!(code, exit::LEASE, "{refused}");

    // A fresh acquire gets fence 2, not fence 1 reissued.
    let (_, granted) = acquire(root, "stats", BOB, 60_000);
    assert_eq!(granted["fence"], 2);
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn a_renewal_keeps_the_fence_because_holder_continuity_is_its_point() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();

    assert_eq!(acquire(root, "stats", ALICE, 150).0, exit::OK);
    let (code, renewed) = cli(
        root,
        &[
            "lease",
            "renew",
            "stats",
            "--fence",
            "1",
            "--ttl-millis",
            "60000",
        ],
    );
    assert_eq!(code, exit::OK, "renew failed: {renewed}");
    assert_eq!(renewed["fence"], 1, "a renewal must not issue a new fence");

    // Past the original expiry, the renewed lease still binds under fence 1.
    std::thread::sleep(Duration::from_millis(260));
    let (code, bound) = bind(root, "stats/a", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::OK, "bind after renewal failed: {bound}");
}

// ---------------------------------------------------------------------------
// step 4 — the policy gate on keys 5 and 6
// ---------------------------------------------------------------------------

#[test]
fn a_policy_stating_keys_5_and_6_is_enforced_and_one_stating_neither_leases_freely() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();

    // Root lease, so the root `POLICY` can be bound at all.
    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    let gated = admit_policy(root, json!({"5": [{"b16": ALICE}], "6": 5000}));
    let (code, bound) = bind(root, "POLICY", &gated, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::OK, "binding the root policy failed: {bound}");

    // Key 5: a principal outside `writers` is refused, naming the reason.
    let (code, refused) = acquire(root, "stats", BOB, 1000);
    assert_eq!(code, exit::LEASE, "{refused}");
    assert_eq!(refused["reason"], "writer");

    // Key 6: an over-bound TTL is refused, never silently clamped.
    let (code, refused) = acquire(root, "stats", ALICE, 5001);
    assert_eq!(code, exit::LEASE, "{refused}");
    assert_eq!(refused["reason"], "bound");
    assert!(
        refused["message"].as_str().unwrap().contains("clamped"),
        "the refusal should say it did not clamp: {refused}"
    );

    // Exactly at the bound is fine, and lands under the gating policy.
    let (code, granted) = acquire(root, "stats", ALICE, 5000);
    assert_eq!(code, exit::OK, "{granted}");
    assert_eq!(granted["policy_ref"], gated);

    // A namespace governed by a policy stating neither key leases freely — the
    // store no longer has to refuse for want of a lease implementation.
    let free = tempfile::tempdir().unwrap();
    assert_eq!(cli(free.path(), &["init", "--from-oracle"]).0, exit::OK);
    let (code, granted) = acquire(free.path(), "stats", BOB, 9_999_999);
    assert_eq!(code, exit::OK, "{granted}");
    assert_eq!(granted["policy_ref"], DEFAULT_POLICY);

    let _ = definition;
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn tightening_a_policy_mid_lease_does_not_evict_the_holder_but_binds_at_the_next_renew() {
    let (root, _definition) = store_with_a_definition();
    let root = root.path();

    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    // Bob holds `stats` under the default policy.
    let (_, granted) = acquire(root, "stats", BOB, 60_000);
    assert_eq!(granted["fence"], 1);

    // Root tightens `writers` to exclude Bob, mid-lease.
    let tightened = admit_policy(root, json!({"5": [{"b16": ALICE}]}));
    assert_eq!(
        bind(root, "POLICY", &tightened, DEFAULT_POLICY, 1).0,
        exit::OK
    );

    // D2: no eviction. Bob still holds it, at the same fence.
    let (code, status) = cli(root, &["lease", "status", "stats"]);
    assert_eq!(code, exit::OK);
    assert_eq!(status["held"], true);
    assert_eq!(status["principal"], BOB);
    assert_eq!(status["fence"], 1);

    // But the new policy binds at the next renew, which re-checks.
    let (code, refused) = cli(
        root,
        &[
            "lease",
            "renew",
            "stats",
            "--fence",
            "1",
            "--ttl-millis",
            "1000",
        ],
    );
    assert_eq!(code, exit::LEASE, "the renewal should re-check: {refused}");
    assert_eq!(refused["reason"], "writer");
}

// ---------------------------------------------------------------------------
// step 5 — the rebind ladder
// ---------------------------------------------------------------------------

#[test]
fn the_rebind_ladder_refuses_a_stale_policy_ref_and_a_non_dominating_amendment() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    // 1. Bind under the default policy.
    let (code, bound) = bind(root, "stats/median", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::OK, "{bound}");
    assert_eq!(bound["seq"], 1);
    assert_eq!(bound["admission"]["governing_policy"], DEFAULT_POLICY);

    // 2. Rebind `stats/POLICY` to a dominating policy. It must dominate the
    //    policy governing it, which for a POLICY leaf resolves strictly above.
    let strict = admit_policy(root, json!({"6": 5000, "9": "no long leases"}));
    let (code, bound) = bind(root, "stats/POLICY", &strict, DEFAULT_POLICY, 1);
    assert_eq!(
        code,
        exit::OK,
        "the dominating policy rebind failed: {bound}"
    );

    // 3. The next bind must carry the *new* policy-ref. The stale one refuses
    //    under rule 1 — this is the raced-a-policy-rebind case, by name.
    let (code, refused) = bind(root, "stats/median", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::REFUSED, "{refused}");
    assert_eq!(refused["layer"], "bindings");
    assert!(
        refused["message"].as_str().unwrap().starts_with("rule 1:"),
        "expected a rule 1 refusal: {refused}"
    );
    let (code, bound) = bind(root, "stats/median", &definition, &strict, 1);
    assert_eq!(code, exit::OK, "retry under the new policy failed: {bound}");
    assert_eq!(bound["seq"], 3, "seq is per namespace, and POLICY took 2");

    // 4. A non-dominating POLICY rebind is refused under rule 6's amendment
    //    rule: a namespace ratchets toward strictness only. Its `policy-ref` is
    //    the *root* policy, because a POLICY leaf resolves strictly above its
    //    own namespace — `stats/POLICY` is not governed by itself.
    let looser = admit_policy(root, json!({"6": 90000}));
    let (code, refused) = bind(root, "stats/POLICY", &looser, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::REFUSED, "{refused}");
    assert!(
        refused["message"].as_str().unwrap().starts_with("rule 6:"),
        "expected a rule 6 refusal: {refused}"
    );

    // 5. History is addressable: every previous binding of the name is there.
    let (code, history) = cli(root, &["history", "stats/median"]);
    assert_eq!(code, exit::OK);
    assert_eq!(history["count"], 2);
    assert_eq!(history["bindings"][0]["policy_ref"], DEFAULT_POLICY);
    assert_eq!(history["bindings"][1]["policy_ref"], strict.as_str());

    let (_, at_one) = cli(root, &["resolve", "stats/median", "--at-seq", "1"]);
    assert_eq!(at_one["policy_ref"], DEFAULT_POLICY);
    let (_, current) = cli(root, &["resolve", "stats/median"]);
    assert_eq!(current["policy_ref"], strict.as_str());

    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn descent_refuses_a_child_policy_that_does_not_dominate_its_ancestor() {
    let (root, _definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    let strict_root = admit_policy(root, json!({"6": 1000}));
    assert_eq!(
        bind(root, "POLICY", &strict_root, DEFAULT_POLICY, 1).0,
        exit::OK
    );

    // A child stating a *larger* maximum does not dominate its ancestor.
    let loose_child = admit_policy(root, json!({"6": 9000}));
    let (code, refused) = bind(root, "stats/POLICY", &loose_child, &strict_root, 1);
    assert_eq!(code, exit::REFUSED, "{refused}");
    assert!(refused["message"].as_str().unwrap().contains("descent"));

    // Restating the ancestor's constraint always satisfies the test.
    let ok_child = admit_policy(root, json!({"6": 500}));
    assert_eq!(
        bind(root, "stats/POLICY", &ok_child, &strict_root, 1).0,
        exit::OK
    );
}

#[test]
fn the_kinds_5_3_2_requires_are_checked_by_the_store_before_the_oracle_is_asked() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    // A `POLICY` leaf bound to a definition.
    let (code, refused) = bind(root, "stats/POLICY", &definition, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::NOT_APPLICABLE, "{refused}");
    assert_eq!(refused["error"], "not_applicable");
    assert_eq!(refused["kind"], "definition");

    // An ordinary leaf bound to a policy.
    let (code, refused) = bind(root, "stats/median", DEFAULT_POLICY, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::NOT_APPLICABLE, "{refused}");
    assert_eq!(refused["kind"], "policy");

    // A def-hash the store does not hold is a typed miss, not a fault.
    let absent = "ab".repeat(32);
    let (code, missed) = bind(root, "stats/median", &absent, DEFAULT_POLICY, 1);
    assert_eq!(code, exit::NOT_FOUND, "{missed}");
    assert_eq!(missed["error"], "not_found");

    // And so is resolving a name nothing was ever bound to — carrying the name
    // rather than a hash, so a caller can tell which lookup missed.
    let (code, missed) = cli(root, &["resolve", "stats/nothing"]);
    assert_eq!(code, exit::NOT_FOUND, "{missed}");
    assert_eq!(missed["error"], "not_found");
    assert_eq!(missed["name"], "stats/nothing");

    // A malformed name-path never reaches the store at all.
    let (code, bad) = cli(root, &["resolve", "stats//median"]);
    assert_eq!(code, exit::USAGE, "{bad}");
    assert_eq!(bad["error"], "bad_name");
}

#[test]
fn monotone_assurance_refuses_a_rebind_that_would_lower_it() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    let strong = root.join("strong.json");
    fs::write(
        &strong,
        serde_json::to_vec(&json!([["ensures.sorted", [3]]])).unwrap(),
    )
    .unwrap();
    let weak = root.join("weak.json");
    fs::write(
        &weak,
        serde_json::to_vec(&json!([["ensures.sorted", [0]]])).unwrap(),
    )
    .unwrap();

    let (code, bound) = cli(
        root,
        &[
            "bind",
            "stats/median",
            "--def",
            &definition,
            "--policy-ref",
            DEFAULT_POLICY,
            "--fence",
            "1",
            "--evidence",
            strong.to_str().unwrap(),
        ],
    );
    assert_eq!(code, exit::OK, "{bound}");

    let (code, refused) = cli(
        root,
        &[
            "bind",
            "stats/median",
            "--def",
            &definition,
            "--policy-ref",
            DEFAULT_POLICY,
            "--fence",
            "1",
            "--evidence",
            weak.to_str().unwrap(),
        ],
    );
    assert_eq!(code, exit::REFUSED, "{refused}");
    assert!(
        refused["message"].as_str().unwrap().starts_with("rule 5:"),
        "expected a rule 5 refusal: {refused}"
    );

    // The refused rebind left nothing behind.
    let (_, history) = cli(root, &["history", "stats/median"]);
    assert_eq!(history["count"], 1);
}

// ---------------------------------------------------------------------------
// step 6 — what `fsck` catches in the state stratum
// ---------------------------------------------------------------------------

/// The state stratum's on-disk paths, spelled out here rather than imported, so
/// that a change to the layout has to be made deliberately in two places.
fn lease_log(root: &Path, namespace: &str) -> PathBuf {
    let stem = if namespace.is_empty() {
        "%".to_string()
    } else {
        namespace.replace('%', "%25").replace('/', "%2F")
    };
    root.join("state/leases").join(format!("{stem}.jsonl"))
}

fn binding_log(root: &Path, namespace: &str) -> PathBuf {
    let stem = if namespace.is_empty() {
        "%".to_string()
    } else {
        namespace.replace('%', "%25").replace('/', "%2F")
    };
    root.join("state/bindings").join(format!("{stem}.jsonl"))
}

fn fsck_problem_kinds(root: &Path) -> (i32, Vec<String>) {
    let (code, body) = cli(root, &["fsck"]);
    let kinds = body["problems"]
        .as_array()
        .map(|problems| {
            problems
                .iter()
                .map(|problem| problem["kind"].as_str().unwrap_or("").to_string())
                .collect()
        })
        .unwrap_or_default();
    (code, kinds)
}

#[test]
fn fsck_catches_a_tampered_lease_log() {
    let (root, _definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);
    cli(root, &["lease", "release", "stats", "--fence", "1"]);
    assert_eq!(acquire(root, "stats", BOB, 60_000).0, exit::OK);
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);

    // Rewrite the second acquisition's fence downward: the log now claims two
    // acquisitions at fence 1, which is exactly what fencing forbids.
    let path = lease_log(root, "stats");
    let text = fs::read_to_string(&path).unwrap();
    let tampered = text.replace("\"fence\":2", "\"fence\":1");
    assert_ne!(text, tampered, "the fixture did not contain fence 2");
    fs::write(&path, tampered).unwrap();

    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"lease_fence_regression".to_string()),
        "expected a fence regression, got {kinds:?}"
    );
    // And the cache no longer equals the fold, which is §5.3.3's own wording.
    assert!(
        kinds.contains(&"lease_cache_diverged".to_string()),
        "{kinds:?}"
    );
}

#[test]
fn fsck_catches_a_binding_whose_def_hash_is_absent_an_unissued_seq_and_a_seq_regression() {
    // Binding `seq` is strictly increasing per namespace (§5.3, R2), not
    // contiguous — the same shape as a fence (§5.3.3) and for the same
    // reason: a `seq` is claimed via `O_CREAT|O_EXCL` before it is appended,
    // so a crash between claiming and appending burns a number rather than
    // blocking the log. `fsck` therefore no longer flags a numbering gap by
    // itself; what it still catches is a `seq` that repeats or goes backward,
    // and a `seq` that was never actually claimed — both are signs of a
    // hand-edited log, not of an ordinary burned claim.
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);
    assert_eq!(
        bind(root, "stats/a", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );
    assert_eq!(
        bind(root, "stats/b", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);

    let path = binding_log(root, "stats");
    let original = fs::read_to_string(&path).unwrap();

    // (a) a def-hash the store does not hold.
    fs::write(&path, original.replace(&definition, &"ab".repeat(32))).unwrap();
    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"binding_object_missing".to_string()),
        "expected a missing object, got {kinds:?}"
    );

    // (b) an unissued seq — the log's second record renumbered to 3, which
    //     this namespace never claimed (only 1 and 2 were ever claimed).
    fs::write(&path, original.replace("\"seq\":2", "\"seq\":3")).unwrap();
    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"binding_seq_unissued".to_string()),
        "expected an unissued seq, got {kinds:?}"
    );

    // (c) a seq regression — the log's second record renumbered to repeat
    //     the first's seq. 1 *was* claimed, so this is not (b); it fails
    //     because it does not exceed the running highest.
    fs::write(&path, original.replace("\"seq\":2", "\"seq\":1")).unwrap();
    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"binding_seq_regression".to_string()),
        "expected a seq regression, got {kinds:?}"
    );
    assert!(
        !kinds.contains(&"binding_seq_unissued".to_string()),
        "seq 1 was legitimately claimed, so this must not also read as unissued: {kinds:?}"
    );

    // (d) restored, everything is clean again — so the checks above are not
    //     firing on something the fixture always had wrong.
    fs::write(&path, &original).unwrap();
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn a_stale_lease_cache_is_a_nuisance_that_reindex_repairs() {
    let (root, _definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    // What a crash between the log append and the cache write leaves behind.
    fs::remove_file(root.join("state/current/stats.json")).unwrap();
    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"lease_cache_diverged".to_string()),
        "{kinds:?}"
    );

    let (code, body) = cli(root, &["reindex"]);
    assert_eq!(code, exit::OK, "{body}");
    assert_eq!(body["namespaces"], 1);
    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn a_fence_the_namespace_never_issued_cannot_be_forged_into_the_log() {
    let (root, _definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    // The claim markers are what *issue* a fence, so a log edited to claim a
    // higher one is detectable even though it is internally consistent.
    let path = lease_log(root, "stats");
    let text = fs::read_to_string(&path)
        .unwrap()
        .replace("\"fence\":1", "\"fence\":9");
    fs::write(&path, text).unwrap();
    cli(root, &["reindex"]); // make the cache agree, so only the fence is wrong

    let (code, kinds) = fsck_problem_kinds(root);
    assert_eq!(code, exit::INTEGRITY);
    assert!(
        kinds.contains(&"lease_fence_unissued".to_string()),
        "expected an unissued fence, got {kinds:?}"
    );
}

// ---------------------------------------------------------------------------
// the read API (R3) and the namespace shape
// ---------------------------------------------------------------------------

#[test]
fn the_read_api_answers_by_namespace_and_an_empty_namespace_is_data() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);
    assert_eq!(acquire(root, "stats/inner", ALICE, 60_000).0, exit::OK);

    assert_eq!(
        bind(root, "top", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );
    assert_eq!(
        bind(root, "stats/median", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );
    assert_eq!(
        bind(root, "stats/inner/deep", &definition, DEFAULT_POLICY, 1).0,
        exit::OK
    );

    // Each namespace has its own lease and its own seq space (L5).
    let (_, all) = cli(root, &["names"]);
    assert_eq!(all["count"], 3);
    let (_, stats) = cli(root, &["names", "--ns", "stats"]);
    assert_eq!(stats["count"], 1);
    assert_eq!(stats["names"][0]["name_path"], "stats/median");
    assert_eq!(
        stats["names"][0]["seq"], 1,
        "seq is per namespace, not global"
    );

    // A namespace with no bindings is a perfectly ordinary namespace.
    let (code, empty) = cli(root, &["names", "--ns", "nothing/here"]);
    assert_eq!(code, exit::OK, "{empty}");
    assert_eq!(empty["count"], 0);

    // A lease on `stats` says nothing about `stats/inner`.
    let (_, inner) = cli(root, &["lease", "status", "stats/inner"]);
    assert_eq!(inner["fence"], 1);
    let (_, outer) = cli(root, &["lease", "status", "stats"]);
    assert_eq!(outer["fence"], 1);
    assert_ne!(
        lease_log(root, "stats"),
        lease_log(root, "stats/inner"),
        "one lease per namespace, one log per namespace"
    );

    // Never leased is data, not a miss.
    let (code, never) = cli(root, &["lease", "status", "untouched"]);
    assert_eq!(code, exit::OK, "{never}");
    assert_eq!(never["held"], false);
    assert_eq!(never["lease"], Value::Null);

    assert_eq!(cli(root, &["fsck"]).0, exit::OK);
}

#[test]
fn a_policy_the_store_cannot_enforce_refuses_the_binding_rather_than_admitting_it() {
    let (root, definition) = store_with_a_definition();
    let root = root.path();
    assert_eq!(acquire(root, "", ALICE, 60_000).0, exit::OK);
    assert_eq!(acquire(root, "stats", ALICE, 60_000).0, exit::OK);

    // Key 2 `max-assumptions` needs an evidence ledger over the transitive
    // closure, which this increment does not have. §5.3.1's own discipline for
    // an unimplemented key is to refuse, not to admit unenforced.
    let budgeted = admit_policy(root, json!({"2": 0}));
    assert_eq!(
        bind(root, "stats/POLICY", &budgeted, DEFAULT_POLICY, 1).0,
        exit::OK,
        "binding the policy itself is governed by root, which states nothing"
    );
    let (code, refused) = bind(root, "stats/median", &definition, &budgeted, 1);
    assert_eq!(code, exit::REFUSED, "{refused}");
    let message = refused["message"].as_str().unwrap();
    assert!(message.starts_with("rule 4:"), "{message}");
    assert!(message.contains("key 2"), "{message}");
    assert!(message.contains("unenforced"), "{message}");
}
