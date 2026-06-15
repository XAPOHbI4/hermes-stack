#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_DB = Path("/root/hermes/runtime/memory-local/memory.sqlite")
DEFAULT_KB = Path("/root/hermes/knowledge/telegram_knowledge_base")
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def hermes_cmd() -> str:
    """Return a Hermes CLI path that works from launchd/cron's minimal PATH."""
    candidates = [
        os.environ.get("HERMES_BIN"),
        shutil.which("hermes"),
        "/root/.local/bin/hermes",
        "/root/.hermes/hermes-agent/venv/bin/hermes",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return "hermes"


def hermes_env() -> dict:
    env = os.environ.copy()
    # launchd/cron on macOS may inherit LC_ALL=C.UTF-8 from Linux-oriented
    # templates; Darwin does not provide that locale, and tar/bash then emit
    # noisy warnings or fail. Cron health checks must be quiet when healthy.
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["PATH"] = ":".join([
        "/root/.local/bin",
        "/root/.hermes/hermes-agent/venv/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
        env.get("PATH", ""),
    ])
    return env


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("pragma journal_mode=wal")
    con.execute(
        """
        create table if not exists chunks (
            id text primary key,
            source_path text not null,
            source_type text not null,
            chunk_index integer not null,
            text text not null,
            sha256 text not null,
            embedding blob,
            dim integer,
            model text,
            updated_at integer not null
        )
        """
    )
    con.execute("create index if not exists idx_chunks_path on chunks(source_path)")
    con.execute("create index if not exists idx_chunks_model on chunks(model)")
    return con


def iter_documents(root: Path):
    allowed = {".md", ".txt", ".csv", ".jsonl", ".json"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part.startswith("_") for part in rel_parts):
            continue
        if path.suffix.lower() == ".json" and path.stat().st_size > 500_000:
            continue
        if path.stat().st_size > 8_000_000:
            continue
        suffix = path.suffix.lower()
        if suffix == ".jsonl":
            for i, line in enumerate(read_text(path).splitlines()):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    text = obj.get("text") or obj.get("body") or obj.get("message") or json.dumps(obj, ensure_ascii=False)
                except Exception:
                    text = line
                yield f"{path}#L{i + 1}", "jsonl", text
        elif suffix == ".csv":
            text = read_text(path)
            try:
                rows = list(csv.DictReader(text.splitlines()))
                for i, row in enumerate(rows):
                    yield f"{path}#row{i + 1}", "csv", json.dumps(row, ensure_ascii=False)
            except Exception:
                yield str(path), "csv", text
        elif suffix == ".json":
            try:
                obj = json.loads(read_text(path))
                text = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                text = read_text(path)
            yield str(path), "json", text
        else:
            yield str(path), suffix.lstrip("."), read_text(path)


def chunks(text: str, size: int = 1400, overlap: int = 180):
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return
    start = 0
    idx = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        cut = cleaned[start:end]
        if end < len(cleaned):
            last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind(" "))
            if last_break > size * 0.55:
                end = start + last_break + 1
                cut = cleaned[start:end]
        yield idx, cut.strip()
        idx += 1
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)


def load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def embed_texts(model, texts):
    import numpy as np

    arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    arr = np.asarray(arr, dtype="float32")
    return arr


def vector_to_blob(vec) -> bytes:
    import numpy as np

    return np.asarray(vec, dtype="float32").tobytes()


def blob_to_vector(blob: bytes, dim: int):
    import numpy as np

    return np.frombuffer(blob, dtype="float32", count=dim)


def cmd_ingest(args):
    root = Path(args.source)
    con = connect(Path(args.db))
    if args.reset:
        con.execute("delete from chunks")
        con.commit()
    model = load_model(args.model)
    pending = []
    total_docs = 0
    total_chunks = 0
    for source_path, source_type, text in iter_documents(root):
        total_docs += 1
        sha = stable_id(source_path, text)
        existing = con.execute(
            "select count(*) from chunks where source_path=? and sha256=? and model=?",
            (source_path, sha, args.model),
        ).fetchone()[0]
        if existing:
            continue
        con.execute("delete from chunks where source_path=? and model=?", (source_path, args.model))
        for chunk_index, chunk_text in chunks(text, args.chunk_size, args.overlap):
            if len(chunk_text) < 20:
                continue
            pending.append((source_path, source_type, chunk_index, chunk_text, sha))
            if len(pending) >= args.batch:
                total_chunks += flush_embeddings(con, model, args.model, pending)
                pending = []
        if args.limit and total_docs >= args.limit:
            break
    if pending:
        total_chunks += flush_embeddings(con, model, args.model, pending)
    count = con.execute("select count(*) from chunks").fetchone()[0]
    print(json.dumps({"status": "ok", "docs_seen": total_docs, "chunks_added": total_chunks, "chunks_total": count, "db": str(args.db), "model": args.model}, ensure_ascii=False))


def flush_embeddings(con, model, model_name: str, rows):
    texts = [r[3] for r in rows]
    vectors = embed_texts(model, texts)
    now = int(time.time())
    for row, vec in zip(rows, vectors):
        source_path, source_type, chunk_index, text, sha = row
        con.execute(
            """
            insert or replace into chunks
            (id, source_path, source_type, chunk_index, text, sha256, embedding, dim, model, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stable_id(source_path, str(chunk_index), sha, model_name),
                source_path,
                source_type,
                chunk_index,
                text,
                sha,
                vector_to_blob(vec),
                len(vec),
                model_name,
                now,
            ),
        )
    con.commit()
    return len(rows)


def cmd_search(args):
    con = connect(Path(args.db))
    model = load_model(args.model)
    qvec = embed_texts(model, [args.query])[0]
    rows = con.execute(
        "select source_path, chunk_index, text, embedding, dim from chunks where model=? and embedding is not null",
        (args.model,),
    ).fetchall()
    scored = []
    for source_path, chunk_index, text, blob, dim in rows:
        vec = blob_to_vector(blob, dim)
        score = float((qvec * vec).sum())
        scored.append((score, source_path, chunk_index, text))
    scored.sort(reverse=True, key=lambda x: x[0])
    result = [
        {"score": round(score, 4), "source": source_path, "chunk": chunk_index, "text": text[: args.text_chars]}
        for score, source_path, chunk_index, text in scored[: args.top_k]
    ]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def read_cliproxy_key() -> str:
    text = Path("/root/.cli-proxy-api/config.yaml").read_text(errors="ignore")
    m = re.search(r"api-keys:\s*\n\s*-\s*[\"']?([^\"'\n#]+)", text)
    if not m:
        raise RuntimeError("No CLIProxy api key found")
    return m.group(1).strip()


def http_json(url: str, api_key: str, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            parsed = {"error": exc.reason}
        return exc.code, parsed


def cmd_provider_health(_args):
    provider = "openai-codex"
    model = "gpt-5.4-mini"
    hermes = hermes_cmd()
    env = hermes_env()
    auth = subprocess.run(
        [hermes, "auth", "status", provider],
        text=True,
        capture_output=True,
        timeout=60,
        env=env,
    )
    chat = subprocess.run(
        [
            hermes,
            "--ignore-rules",
            "--provider",
            provider,
            "--model",
            model,
            "-z",
            "Reply exactly: OK",
        ],
        text=True,
        capture_output=True,
        timeout=180,
        cwd="/root/hermes",
        env=env,
    )
    text = (chat.stdout or "").strip()
    result = {
        "provider": provider,
        "model": model,
        "hermes_bin": hermes,
        "auth_status_rc": auth.returncode,
        "auth_logged_in": "logged in" in ((auth.stdout or "") + (auth.stderr or "")).lower(),
        "chat_status_rc": chat.returncode,
        "chat_text": text[:200],
        "stderr_tail": (chat.stderr or "")[-500:],
    }
    print(json.dumps(result, ensure_ascii=False))
    if result["auth_status_rc"] != 0 or not result["auth_logged_in"] or chat.returncode != 0 or text != "OK":
        raise SystemExit(2)


def run_cmd(cmd):
    if cmd and cmd[0] == "hermes":
        cmd = [hermes_cmd(), *cmd[1:]]
    return subprocess.run(cmd, text=True, capture_output=True, timeout=120, env=hermes_env())


def cmd_kanban_monitor(args):
    boards = args.boards or ["system-changes", "projects-ideas", "smm-department", "sync-system", "company-runtime"]
    out = {}
    for board in boards:
        stats = run_cmd(["hermes", "kanban", "--board", board, "stats"])
        out[board] = {"rc": stats.returncode, "text": (stats.stdout + stats.stderr)[-3000:]}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_security_audit(_args):
    checks = []
    for path in [Path("/root/.hermes/.env"), Path("/root/.hermes/config.yaml")]:
        if path.exists():
            mode = path.stat().st_mode & 0o777
            checks.append({"path": str(path), "mode": oct(mode), "ok": mode & 0o077 == 0})
    cliproxy_cfg = Path("/root/.cli-proxy-api/config.yaml")
    if cliproxy_cfg.exists():
        mode = cliproxy_cfg.stat().st_mode & 0o777
        checks.append({"path": str(cliproxy_cfg), "mode": oct(mode), "ok": mode & 0o077 == 0})
    auth_dir = Path("/root/.cli-proxy-api/auths")
    active = 0
    total = 0
    if auth_dir.exists():
        for p in auth_dir.glob("*.json"):
            total += 1
            if not auth_disabled(p):
                active += 1
        checks.append({"path": str(auth_dir), "auth_files": total, "active_by_flag": active, "ok": active >= 1})
    else:
        checks.append({"path": str(auth_dir), "present": False, "ok": True, "note": "cli-proxy-api is not installed on this macOS host"})
    print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2))
    if not all(c.get("ok") for c in checks):
        raise SystemExit(2)


def auth_disabled(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except Exception:
        return True

    def walk(obj, needle):
        values = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                if needle in str(key).lower():
                    values.append(value)
                values.extend(walk(value, needle))
        elif isinstance(obj, list):
            for item in obj:
                values.extend(walk(item, needle))
        return values

    for key in ("disabled", "quarantine", "quarantined", "invalid", "revoked"):
        for value in walk(data, key):
            if value is True:
                return True
            if isinstance(value, str) and value.lower() in {"true", "1", "yes", "disabled", "quarantine"}:
                return True
    return False


def cmd_backup_config(_args):
    stamp = time.strftime("%Y%m%dT%H%M%S%z")
    dest = Path("/root/hermes/backups") / f"runtime-config-{stamp}.tar.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    requested_paths = [
        "/root/.hermes/config.yaml",
        "/root/.hermes/.env",
        "/root/.hermes/profiles",
        "/root/.hermes/kanban",
        "/root/.cli-proxy-api/config.yaml",
        "/root/.cli-proxy-api/auths",
    ]
    existing_paths = [p for p in requested_paths if Path(p).exists()]
    skipped_paths = [p for p in requested_paths if not Path(p).exists()]
    cmd = [
        "tar",
        "-czf",
        str(dest),
        *existing_paths,
    ]
    proc = run_cmd(cmd)
    print(json.dumps({"backup": str(dest), "rc": proc.returncode, "skipped_missing": skipped_paths, "stderr_tail": proc.stderr[-600:]}, ensure_ascii=False))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def cmd_status(args):
    con = connect(Path(args.db))
    chunks_count = con.execute("select count(*) from chunks").fetchone()[0]
    sources_count = con.execute("select count(distinct source_path) from chunks").fetchone()[0]
    print(json.dumps({"memory_db": str(args.db), "chunks": chunks_count, "sources": sources_count}, ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    ingest = sub.add_parser("memory-ingest")
    ingest.add_argument("--source", default=str(DEFAULT_KB))
    ingest.add_argument("--db", default=str(DEFAULT_DB))
    ingest.add_argument("--model", default=DEFAULT_MODEL)
    ingest.add_argument("--chunk-size", type=int, default=1400)
    ingest.add_argument("--overlap", type=int, default=180)
    ingest.add_argument("--batch", type=int, default=32)
    ingest.add_argument("--limit", type=int, default=0)
    ingest.add_argument("--reset", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    search = sub.add_parser("memory-search")
    search.add_argument("query")
    search.add_argument("--db", default=str(DEFAULT_DB))
    search.add_argument("--model", default=DEFAULT_MODEL)
    search.add_argument("--top-k", type=int, default=8)
    search.add_argument("--text-chars", type=int, default=700)
    search.set_defaults(func=cmd_search)

    status = sub.add_parser("memory-status")
    status.add_argument("--db", default=str(DEFAULT_DB))
    status.set_defaults(func=cmd_status)

    sub.add_parser("provider-health").set_defaults(func=cmd_provider_health)
    km = sub.add_parser("kanban-monitor")
    km.add_argument("--boards", nargs="*")
    km.set_defaults(func=cmd_kanban_monitor)
    sub.add_parser("security-audit").set_defaults(func=cmd_security_audit)
    sub.add_parser("backup-config").set_defaults(func=cmd_backup_config)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
