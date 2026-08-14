//! `loom-store` — the CLI over the store.
//!
//! Output discipline, which is the whole visible surface of this increment:
//!
//! * **stdout is always exactly one line of JSON**, on success and on failure
//!   alike. A caller pipes it into a JSON reader and branches on the presence
//!   of an `error` key; it never parses prose and never has to special-case the
//!   failure channel. The one exception is `get --raw`, which is asking for
//!   bytes and gets bytes.
//! * **stderr is for humans and only under `--verbose`.** A quiet run says
//!   nothing there, so `2>/dev/null` is never needed and never hides anything.
//! * **the exit code is the error class**, per `error::exit`. A miss is 3, and
//!   a miss is not a fault.

use std::io::Write;
use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use serde_json::{json, Value};

use loom_store::error::{exit, Result, StoreError};
use loom_store::hash::ObjectHash;
use loom_store::index::IndexRow;
use loom_store::oracle::Oracle;
use loom_store::store::PutOutcome;
use loom_store::Store;

#[derive(Parser)]
#[command(
    name = "loom-store",
    version,
    about = "Loom's persistent content-addressed object store (SPEC §5), v0",
    long_about = None
)]
struct Cli {
    /// The store directory.
    #[arg(long, global = true, env = "LOOM_STORE", default_value = ".loom-store")]
    store: PathBuf,

    /// Python interpreter used to run the admission oracle.
    #[arg(long, global = true, env = "LOOM_PYTHON", default_value = "python3")]
    python: String,

    /// The `prototype/` tree the admission oracle lives in.
    #[arg(
        long,
        global = true,
        env = "LOOM_PROTOTYPE",
        default_value = "prototype"
    )]
    prototype: PathBuf,

    /// Human-oriented commentary on stderr. stdout stays JSON either way.
    #[arg(long, short, global = true)]
    verbose: bool,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Create the store directory skeleton. Idempotent.
    Init {
        /// Record contract versions read from this JSON file.
        #[arg(long, conflicts_with = "from_oracle")]
        contracts: Option<PathBuf>,
        /// Record contract versions by asking the Python oracle.
        #[arg(long)]
        from_oracle: bool,
        /// Skip preloading §5.3.2's default policy. Only for a store that will
        /// never bind a name: without it, resolution has no base case and every
        /// `bind` refuses.
        #[arg(long)]
        bare: bool,
    },
    /// Land an object whose sidecar has already been produced by the oracle.
    Put {
        #[arg(long)]
        sidecar: PathBuf,
        object: PathBuf,
    },
    /// Validate through the Python oracle, then put. `--corpus` seeds the
    /// pinned bootstrap corpus.
    Admit {
        /// Admit the full pinned corpus in dependency order.
        #[arg(long, conflicts_with = "source")]
        corpus: bool,
        /// A canonical `(def …)` surface file.
        source: Option<PathBuf>,
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        spec: Option<String>,
        #[arg(long, default_value_t = 0)]
        sequence: u64,
    },
    /// Validate a §5.3.1 policy object through the oracle, then put it.
    AdmitPolicy {
        /// A JSON-mirrored policy object, `[6, {"m": [[key, value]…]}]`.
        source: PathBuf,
        #[arg(long)]
        name: Option<String>,
        #[arg(long, default_value_t = 0)]
        sequence: u64,
    },
    /// The namespace write lease (§5.3.3).
    #[command(subcommand)]
    Lease(LeaseCommand),
    /// Append a binding, if the fence holds and §5.3.2 admits it.
    Bind {
        name_path: String,
        /// The definition (or, for a `POLICY` leaf, the policy) being bound.
        #[arg(long = "def")]
        def_hash: String,
        /// The governing policy this proposal was cleared against.
        #[arg(long = "policy-ref")]
        policy_ref: String,
        /// The fence issued by `lease acquire`.
        #[arg(long)]
        fence: u64,
        /// A JSON file holding `[[obligation-id, lattice-point]…]`, sorted by
        /// id. Absent means the empty evidence set.
        #[arg(long)]
        evidence: Option<PathBuf>,
    },
    /// The current binding of a name, or the one in force at `--at-seq`.
    Resolve {
        name_path: String,
        #[arg(long = "at-seq")]
        at_seq: Option<u64>,
    },
    /// Every binding of a name, oldest first.
    History { name_path: String },
    /// The current binding of every name.
    Names {
        /// Restrict to one namespace. The root namespace is `""`.
        #[arg(long)]
        ns: Option<String>,
    },
    /// The object's canonical bytes, identity re-verified on the way out.
    Get {
        hash: String,
        /// Write the raw bytes to stdout instead of a JSON line.
        #[arg(long)]
        raw: bool,
    },
    /// The type surface a `ref` to this hash has, from the index.
    Type { hash: String },
    /// Declared dependency edges out of this object.
    Deps { hash: String },
    /// Declared dependency edges into this object.
    Rdeps { hash: String },
    /// Enumerate objects.
    List {
        #[arg(long)]
        kind: Option<String>,
    },
    /// Every hash extending a hex prefix.
    Prefix { prefix: String },
    /// Re-prove every invariant. Exit 4 if any fails.
    Fsck,
    /// Re-derive the index from the sidecars.
    Reindex,
    /// One document with everything the Python harness needs to build a
    /// resolver.
    #[command(name = "export-resolver")]
    ExportResolver {
        #[arg(long)]
        out: Option<PathBuf>,
    },
}

/// §5.3.3's verbs, minus the one deliberately not built: `revoke` is named as
/// future work by the approved lease design, not omitted by oversight.
#[derive(Subcommand)]
enum LeaseCommand {
    /// Take the namespace's write lease, or be told who has it.
    Acquire {
        namespace: String,
        /// The claimed 32-byte principal-id. Claimed, not proved — possession
        /// proof is the A0 payload's open question (§5.3.3, §13).
        #[arg(long)]
        principal: String,
        #[arg(long = "ttl-millis")]
        ttl_millis: u64,
    },
    /// Extend the expiry under the same fence, re-checked against the policy
    /// now in force.
    Renew {
        namespace: String,
        #[arg(long)]
        fence: u64,
        #[arg(long = "ttl-millis")]
        ttl_millis: u64,
    },
    /// End the lease immediately.
    Release {
        namespace: String,
        #[arg(long)]
        fence: u64,
    },
    /// The fold of the lease log, and whether it is held right now.
    Status { namespace: String },
}

/// What a subcommand produced: a JSON line, and the code to exit with.
struct Outcome {
    value: Value,
    code: i32,
}

impl Outcome {
    fn ok(value: Value) -> Self {
        Outcome {
            value,
            code: exit::OK,
        }
    }
}

fn main() {
    let cli = Cli::parse();
    let verbose = cli.verbose;
    match run(&cli) {
        Ok(None) => {}
        Ok(Some(outcome)) => {
            print_line(&outcome.value);
            if outcome.code != exit::OK {
                std::process::exit(outcome.code);
            }
        }
        Err(error) => {
            print_line(&error.to_json());
            if verbose {
                eprintln!("loom-store: {error}");
            }
            std::process::exit(error.exit_code());
        }
    }
}

fn print_line(value: &Value) {
    let mut stdout = std::io::stdout().lock();
    let _ = writeln!(stdout, "{value}");
    let _ = stdout.flush();
}

fn note(verbose: bool, message: impl AsRef<str>) {
    if verbose {
        eprintln!("loom-store: {}", message.as_ref());
    }
}

/// `Ok(None)` means the command wrote raw bytes and has nothing to say.
fn run(cli: &Cli) -> Result<Option<Outcome>> {
    match &cli.command {
        Command::Init {
            contracts,
            from_oracle,
            bare,
        } => {
            let map = if let Some(path) = contracts {
                let bytes = std::fs::read(path).map_err(|error| StoreError::io(path, error))?;
                serde_json::from_slice(&bytes)
                    .map_err(|error| StoreError::malformed(path, error.to_string()))?
            } else if *from_oracle {
                oracle(cli).contracts()?
            } else {
                serde_json::Map::new()
            };
            let (store, created) = Store::init(&cli.store, map)?;
            note(
                cli.verbose,
                if created {
                    "created"
                } else {
                    "already a store"
                },
            );
            // §5.3.2's resolution terminates at the default policy, so a store
            // without it cannot bind anything at all. It is preloaded "like the
            // §2.4 prelude" — but through the oracle, because a sidecar minted
            // in Rust would be the store inventing contract versions for an
            // object it did not validate.
            let default_policy = if *bare {
                None
            } else {
                let workspace = Workspace::new(&store)?;
                let emitted = oracle(cli).default_policy(workspace.path())?;
                let mut landed = None;
                for item in &emitted {
                    let outcome = put_files(
                        &store,
                        &workspace.path().join(&item.object),
                        &workspace.path().join(&item.sidecar),
                    )?;
                    landed = Some(outcome.0.to_string());
                }
                landed
            };
            Ok(Some(Outcome::ok(json!({
                "status": if created { "created" } else { "exists" },
                "store": cli.store.display().to_string(),
                "layout_version": store.meta()?.layout_version,
                "default_policy": default_policy,
            }))))
        }

        Command::AdmitPolicy {
            source,
            name,
            sequence,
        } => {
            let store = Store::open(&cli.store)?;
            let workspace = Workspace::new(&store)?;
            let source = absolute(source)?;
            let emitted =
                oracle(cli).policy(&source, workspace.path(), name.as_deref(), *sequence)?;
            let mut landed = Vec::new();
            for item in &emitted {
                let outcome = put_files(
                    &store,
                    &workspace.path().join(&item.object),
                    &workspace.path().join(&item.sidecar),
                )?;
                landed.push(json!({ "hash": outcome.0.to_string(), "status": outcome.1.as_str() }));
            }
            Ok(Some(Outcome::ok(
                json!({ "status": "admitted", "objects": landed }),
            )))
        }

        Command::Lease(verb) => {
            let store = Store::open(&cli.store)?;
            let lease = match verb {
                LeaseCommand::Acquire {
                    namespace,
                    principal,
                    ttl_millis,
                } => store.lease_acquire(&oracle(cli), namespace, principal, *ttl_millis)?,
                LeaseCommand::Renew {
                    namespace,
                    fence,
                    ttl_millis,
                } => store.lease_renew(&oracle(cli), namespace, *fence, *ttl_millis)?,
                LeaseCommand::Release { namespace, fence } => {
                    store.lease_release(namespace, *fence)?
                }
                LeaseCommand::Status { namespace } => match store.lease_status(namespace)? {
                    Some(lease) => lease,
                    // Never leased is data, not a miss: it is the state every
                    // namespace starts in.
                    None => {
                        return Ok(Some(Outcome::ok(json!({
                            "namespace": namespace,
                            "held": false,
                            "lease": Value::Null,
                        }))))
                    }
                },
            };
            let now = loom_store::store::now_millis();
            Ok(Some(Outcome::ok(json!({
                "namespace": lease.namespace,
                "held": lease.held_at(now),
                "fence": lease.fence,
                "principal": lease.principal,
                "policy_ref": lease.policy_ref,
                "expires_millis": lease.expires_millis,
                "now_millis": now,
                "released": lease.released,
            }))))
        }

        Command::Bind {
            name_path,
            def_hash,
            policy_ref,
            fence,
            evidence,
        } => {
            let store = Store::open(&cli.store)?;
            let entries = match evidence {
                None => Vec::new(),
                Some(path) => {
                    let bytes = std::fs::read(path).map_err(|error| StoreError::io(path, error))?;
                    let value: Value = serde_json::from_slice(&bytes)
                        .map_err(|error| StoreError::malformed(path, error.to_string()))?;
                    value.as_array().cloned().ok_or_else(|| {
                        StoreError::malformed(path, "expected an array of [obligation-id, point]")
                    })?
                }
            };
            let (record, admission) = store.bind(
                &oracle(cli),
                name_path,
                def_hash,
                entries,
                policy_ref,
                *fence,
            )?;
            note(
                cli.verbose,
                format!("bound {name_path} at seq {}", record.seq),
            );
            Ok(Some(Outcome::ok(json!({
                "status": "bound",
                "name_path": record.name_path,
                "seq": record.seq,
                "def_hash": record.def_hash,
                "policy_ref": record.policy_ref,
                "fence": record.fence,
                "admission": admission,
            }))))
        }

        Command::Resolve { name_path, at_seq } => {
            let store = Store::open(&cli.store)?;
            let record = store.resolve(name_path, *at_seq)?;
            Ok(Some(Outcome::ok(binding_json(&record))))
        }

        Command::History { name_path } => {
            let store = Store::open(&cli.store)?;
            let records = store.history(name_path)?;
            Ok(Some(Outcome::ok(json!({
                "name_path": name_path,
                "count": records.len(),
                "bindings": records.iter().map(binding_json).collect::<Vec<_>>(),
            }))))
        }

        Command::Names { ns } => {
            let store = Store::open(&cli.store)?;
            let records = store.names(ns.as_deref())?;
            Ok(Some(Outcome::ok(json!({
                "count": records.len(),
                "names": records.iter().map(binding_json).collect::<Vec<_>>(),
            }))))
        }

        Command::Put { sidecar, object } => {
            let store = Store::open(&cli.store)?;
            let outcome = put_files(&store, object, sidecar)?;
            note(cli.verbose, format!("{} {}", outcome.0, outcome.1.as_str()));
            Ok(Some(Outcome::ok(json!({
                "status": outcome.1.as_str(),
                "hash": outcome.0.to_string(),
            }))))
        }

        Command::Admit {
            corpus,
            source,
            name,
            spec,
            sequence,
        } => {
            let store = Store::open(&cli.store)?;
            let workspace = Workspace::new(&store)?;
            let oracle = oracle(cli);

            let emitted = if *corpus {
                note(cli.verbose, "asking the oracle for the pinned corpus");
                oracle.corpus(workspace.path())?
            } else {
                let source = source.as_ref().ok_or_else(|| StoreError::Layout {
                    detail: "admit needs a source file or --corpus".to_string(),
                })?;
                // The store feeds its own contents back to the oracle, so a
                // definition may reference anything already admitted. An empty
                // store therefore refuses a definition that names a
                // declaration — which is correct, not a bootstrap bug.
                let export = workspace.path().join("resolver.json");
                write_json(&export, &store.export_resolver()?)?;
                let source = absolute(source)?;
                oracle.emit(
                    &source,
                    workspace.path(),
                    Some(&export),
                    name.as_deref(),
                    spec.as_deref(),
                    *sequence,
                )?
            };

            let mut written = 0usize;
            let mut existing = 0usize;
            for item in &emitted {
                let outcome = put_files(
                    &store,
                    &workspace.path().join(&item.object),
                    &workspace.path().join(&item.sidecar),
                )?;
                match outcome.1 {
                    PutOutcome::Written => written += 1,
                    PutOutcome::Exists => existing += 1,
                }
                note(
                    cli.verbose,
                    format!("{} {} {}", outcome.1.as_str(), item.kind, outcome.0),
                );
            }
            Ok(Some(Outcome::ok(json!({
                "status": "admitted",
                "written": written,
                "exists": existing,
                "objects": emitted.iter().map(|item| json!({
                    "hash": item.hash,
                    "kind": item.kind,
                    "name": item.name,
                    "sequence": item.sequence,
                })).collect::<Vec<_>>(),
            }))))
        }

        Command::Get { hash, raw } => {
            let store = Store::open(&cli.store)?;
            let hash = ObjectHash::parse(hash)?;
            let bytes = store.get(&hash)?;
            if *raw {
                let mut stdout = std::io::stdout().lock();
                stdout
                    .write_all(&bytes)
                    .map_err(|error| StoreError::io("<stdout>", error))?;
                stdout
                    .flush()
                    .map_err(|error| StoreError::io("<stdout>", error))?;
                return Ok(None);
            }
            // The sidecar is what carries the canonical surface, and the
            // surface is what a prompt shows — conclusion 1's read path. The
            // bytes come too, hex-encoded, because they are the identity.
            let (sidecar, _) = store.sidecar(&hash)?;
            Ok(Some(Outcome::ok(json!({
                "hash": hash.to_string(),
                "kind": sidecar.kind,
                "name": sidecar.name,
                "length": bytes.len(),
                "bytes": hex(&bytes),
                "surface": sidecar.surface,
                "spec": sidecar.spec,
            }))))
        }

        Command::Type { hash } => {
            let store = Store::open(&cli.store)?;
            let hash = ObjectHash::parse(hash)?;
            let (kind, surface) = store.type_of(&hash)?;
            Ok(Some(Outcome::ok(json!({
                "hash": hash.to_string(),
                "kind": kind,
                "type": surface,
            }))))
        }

        Command::Deps { hash } => {
            let store = Store::open(&cli.store)?;
            let hash = ObjectHash::parse(hash)?;
            Ok(Some(Outcome::ok(json!({
                "hash": hash.to_string(),
                "deps": store.deps(&hash)?,
            }))))
        }

        Command::Rdeps { hash } => {
            let store = Store::open(&cli.store)?;
            let hash = ObjectHash::parse(hash)?;
            Ok(Some(Outcome::ok(json!({
                "hash": hash.to_string(),
                "rdeps": store.rdeps(&hash)?,
            }))))
        }

        Command::List { kind } => {
            let store = Store::open(&cli.store)?;
            let rows = store.list(kind.as_deref())?;
            Ok(Some(Outcome::ok(json!({
                "count": rows.len(),
                "objects": rows.iter().map(summary).collect::<Vec<_>>(),
            }))))
        }

        Command::Prefix { prefix } => {
            let store = Store::open(&cli.store)?;
            let hashes = store.prefix(prefix)?;
            Ok(Some(Outcome::ok(json!({
                "prefix": prefix,
                "count": hashes.len(),
                "hashes": hashes,
            }))))
        }

        Command::Fsck => {
            let store = Store::open(&cli.store)?;
            let report = store.fsck()?;
            note(
                cli.verbose,
                format!(
                    "{} objects, {} index rows, {} problems",
                    report.objects,
                    report.rows,
                    report.problems.len()
                ),
            );
            if report.healthy() {
                return Ok(Some(Outcome::ok(json!({
                    "ok": true,
                    "objects": report.objects,
                    "rows": report.rows,
                }))));
            }
            Ok(Some(Outcome {
                value: json!({
                    "error": "integrity",
                    "message": format!("{} problem(s)", report.problems.len()),
                    "objects": report.objects,
                    "rows": report.rows,
                    "problems": report.problems,
                }),
                code: exit::INTEGRITY,
            }))
        }

        Command::Reindex => {
            let store = Store::open(&cli.store)?;
            let (rows, namespaces) = store.reindex()?;
            Ok(Some(Outcome::ok(json!({
                "status": "reindexed",
                "rows": rows,
                "namespaces": namespaces,
            }))))
        }

        Command::ExportResolver { out } => {
            let store = Store::open(&cli.store)?;
            let document = store.export_resolver()?;
            match out {
                Some(path) => {
                    write_json(path, &document)?;
                    Ok(Some(Outcome::ok(json!({
                        "status": "exported",
                        "path": path.display().to_string(),
                        "objects": document["objects"].as_array().map_or(0, Vec::len),
                    }))))
                }
                None => Ok(Some(Outcome::ok(document))),
            }
        }
    }
}

/// One binding record on the wire. The named form of SPEC §5.3's
/// `[2, name-path, def-hash, evidence-set, policy-ref, seq]`, plus the fence
/// that appended it.
fn binding_json(record: &loom_store::state::BindingRecord) -> Value {
    json!({
        "name_path": record.name_path,
        "seq": record.seq,
        "def_hash": record.def_hash,
        "evidence": record.evidence,
        "policy_ref": record.policy_ref,
        "fence": record.fence,
    })
}

fn summary(row: &IndexRow) -> Value {
    json!({
        "hash": row.hash,
        "kind": row.kind,
        "name": row.name,
        "type": row.type_surface,
        "sequence": row.sequence,
    })
}

fn put_files(store: &Store, object: &Path, sidecar: &Path) -> Result<(ObjectHash, PutOutcome)> {
    let object_bytes = std::fs::read(object).map_err(|error| StoreError::io(object, error))?;
    let sidecar_bytes = std::fs::read(sidecar).map_err(|error| StoreError::io(sidecar, error))?;
    store.put(&object_bytes, &sidecar_bytes)
}

fn oracle(cli: &Cli) -> Oracle {
    Oracle::new(cli.python.clone(), &cli.prototype)
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let mut bytes = serde_json::to_vec(value).map_err(|error| StoreError::Layout {
        detail: error.to_string(),
    })?;
    bytes.push(b'\n');
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| StoreError::io(parent, error))?;
    }
    std::fs::write(path, &bytes).map_err(|error| StoreError::io(path, error))
}

fn absolute(path: &Path) -> Result<PathBuf> {
    std::fs::canonicalize(path).map_err(|error| StoreError::io(path, error))
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// A scratch directory inside the store, removed when the command finishes.
///
/// It lives under the store's own `tmp/` rather than in `/tmp` for the same
/// reason atomic writes do: same filesystem, and nothing the store depends on
/// ever sits on a mount it does not control.
struct Workspace {
    path: PathBuf,
}

impl Workspace {
    fn new(store: &Store) -> Result<Self> {
        let root = std::fs::canonicalize(store.layout().root())
            .map_err(|error| StoreError::io(store.layout().root(), error))?;
        let path = root
            .join(loom_store::layout::TMP_DIR)
            .join(format!("admit.{}", std::process::id()));
        std::fs::create_dir_all(&path).map_err(|error| StoreError::io(&path, error))?;
        Ok(Workspace { path })
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}
