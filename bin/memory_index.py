#!/usr/bin/env python3
"""memory_index.py — локальный retrieval-слой для оркестратора (по local-embedding-brief v2026-04-30).

Локальный, offline, приватный: fastembed + paraphrase-multilingual-MiniLM-L12-v2 (384d),
SQLite + FTS5, гибрид vector+BM25. НЕ источник истины — слой навигации по references/wiki.

Команды:
  rebuild-atomic   собрать индекс в temp, проверить (secret-scan+benchmark), атомарно заменить live
  verify           показать что в индексе (кол-во, источники)
  secret-scan      пересканировать сохранённые чанки на секреты (defense-in-depth)
  benchmark        прогнать контрольные запросы (expected path substring в top-k)
  search "<q>"     поиск, JSON {success, results:[{path,heading,score,snippet}]}
"""
from __future__ import annotations
import sys, os, re, json, sqlite3, hashlib, argparse, tempfile
sys.stdout.reconfigure(encoding="utf-8")

MI = os.environ.get("MI_HOME", "/root/hermes/runtime/memory-index")
DB = os.path.join(MI, "index.db")
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384
CHUNK = 1100  # ~chars

# источники знаний (НЕ память, НЕ секреты, НЕ live state)
ROOTS = os.environ.get("MI_ROOTS",
    "/root/.hermes/profiles/orchestrator/references:"
    "/root/.hermes/profiles/orchestrator/wiki:"
    "/root/.hermes/profiles/orchestrator/skills:"
    "/root/hermes/runtime/reports").split(":")

# §12 security gate: что НИКОГДА не индексируем
FORBID_PATH = re.compile(r"(USER\.md$|\.env|\.bak|\.sqlite$|\.db$|/logs/|/kanban/|"
                         r"/closures/|/reviews/|/sessions/|credential|auth\.json|secret)", re.I)
ALLOW_EXT = {".md", ".txt"}

# hard-secret detectors (значения НЕ печатаем)
HARD = [re.compile(p) for p in [
    r"sk-[A-Za-z0-9]{20,}", r"\d{6,}:[A-Za-z0-9_-]{30,}", r"AIza[0-9A-Za-z_-]{30,}",
    r"ya29\.[0-9A-Za-z_-]+", r"xoxb-[0-9A-Za-z-]+", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", r"AKIA[0-9A-Z]{16}",
]]

BENCH = [
    ("приоритет источников правды", "source-map"),
    ("уровни риска изменений L0 L5", "change-safety"),
    ("что хранить в памяти что никогда", "memory-policy"),
    ("как закрывается задача с доказательством proof", "kanban"),
    ("архитектура системы провайдеры", "architecture"),
    ("ключевые решения почему", "decisions"),
]

def _emb():
    from fastembed import TextEmbedding
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return TextEmbedding(model_name=MODEL)

def _scan_secret(text):
    for rx in HARD:
        m = rx.search(text)
        if m:
            s = m.group(0)
            return s[:4] + "…(len %d)" % len(s)
    return None

def _iter_files():
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _, fns in os.walk(root):
            for fn in fns:
                p = os.path.join(dp, fn)
                if os.path.splitext(fn)[1].lower() not in ALLOW_EXT:
                    continue
                if FORBID_PATH.search(p):
                    continue
                if "/skills/" in p and fn != "SKILL.md":
                    continue
                if "/reports/" in p and not (fn.startswith("lessons-") and fn.endswith(".md") and fn not in ("lessons-latest.md", "lessons-msg.md")):
                    continue
                yield p

def _chunks(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    title = os.path.basename(path)
    heading = title
    buf, idx = [], 0
    cur = 0
    lines = txt.splitlines()
    out = []
    def flush():
        nonlocal buf, idx
        body = "\n".join(buf).strip()
        if body:
            out.append((idx, heading, body)); idx += 1
        buf = []
    for ln in lines:
        h = re.match(r"^#{1,4}\s+(.*)", ln)
        if h:
            if buf: flush()
            heading = h.group(1).strip()[:120]
        buf.append(ln); cur += len(ln)
        if sum(len(x) for x in buf) >= CHUNK:
            flush()
    flush()
    return title, out

def rebuild_atomic():
    import numpy as np
    emb = _emb()
    rows = []
    skipped_secret = []
    for p in _iter_files():
        title, chunks = _chunks(p)
        st = ("skill" if "/skills/" in p else "lesson" if "/reports/" in p else "wiki" if "/wiki/" in p else "reference")
        file_rows = []
        sec_hit = None
        for idx, heading, body in chunks:
            blob = f"{title}\n{heading}\n{body}"
            sec = _scan_secret(blob)
            if sec:
                sec_hit = sec
                break
            file_rows.append((st, p, title, heading, idx, body, blob))
        if sec_hit:
            if "/skills/" in p:
                skipped_secret.append(p)
                continue
            print(f"ABORT: hard-secret в {p} :: {sec_hit} — индекс НЕ собран", file=sys.stderr)
            return 2
        rows.extend(file_rows)
    if skipped_secret:
        print(f"SKIPPED {len(skipped_secret)} skill-файлов с secret-паттернами (НЕ проиндексированы)")
    if not rows:
        print("ABORT: 0 документов (проверь ROOTS)", file=sys.stderr); return 2
    print(f"embedding {len(rows)} chunks…")
    vecs = list(emb.embed([r[6] for r in rows]))
    tmp = DB + ".tmp"
    if os.path.exists(tmp): os.remove(tmp)
    c = sqlite3.connect(tmp)
    c.executescript("""
      CREATE TABLE documents(id INTEGER PRIMARY KEY, source_type TEXT, source_path TEXT,
        title TEXT, heading TEXT, chunk_idx INT, content TEXT, content_hash TEXT,
        embedded_at TEXT DEFAULT (datetime('now')), embedding_dim INT, embedding BLOB);
      CREATE VIRTUAL TABLE doc_fts USING fts5(content, content='documents', content_rowid='id');
    """)
    for (st,p,title,heading,idx,body,blob), v in zip(rows, vecs):
        v = np.asarray(v, dtype="float32")
        v = v / (np.linalg.norm(v) + 1e-9)
        ch = hashlib.sha256(blob.encode()).hexdigest()[:16]
        cur = c.execute("INSERT INTO documents(source_type,source_path,title,heading,chunk_idx,"
                        "content,content_hash,embedding_dim,embedding) VALUES(?,?,?,?,?,?,?,?,?)",
                        (st,p,title,heading,idx,body,ch,DIM,v.tobytes()))
        c.execute("INSERT INTO doc_fts(rowid,content) VALUES(?,?)", (cur.lastrowid, body))
    c.commit(); c.close()
    os.replace(tmp, DB)
    print(f"REBUILD_OK: {len(rows)} chunks из {len(set(r[1] for r in rows))} файлов -> {DB}")
    return run_benchmark(quiet=False)

def _load_all():
    import numpy as np
    c = sqlite3.connect(DB)
    ids, paths, heads, conts, mats = [], [], [], [], []
    for rid,p,h,cont,emb in c.execute("SELECT id,source_path,heading,content,embedding FROM documents"):
        ids.append(rid); paths.append(p); heads.append(h); conts.append(cont)
        mats.append(np.frombuffer(emb, dtype="float32"))
    c.close()
    return ids, paths, heads, conts, (np.vstack(mats) if mats else np.zeros((0,DIM),"float32"))

def search(query, top_k=5, as_json=True):
    import numpy as np
    if not os.path.exists(DB):
        out = {"success": False, "error": "index not built"}; print(json.dumps(out,ensure_ascii=False)); return 1
    emb = _emb()
    qv = np.asarray(list(emb.embed([query]))[0], dtype="float32")
    qv = qv / (np.linalg.norm(qv)+1e-9)
    ids, paths, heads, conts, M = _load_all()
    cos = M @ qv if len(M) else np.zeros(0)
    # FTS5 boost: чанки с лексическим совпадением получают +0.1
    boost = {}
    try:
        c = sqlite3.connect(DB)
        q = " OR ".join(re.findall(r"\w{3,}", query))[:200]
        if q:
            for (rid,) in c.execute("SELECT rowid FROM doc_fts WHERE doc_fts MATCH ? LIMIT 50", (q,)):
                boost[rid] = 0.1
        c.close()
    except Exception:
        pass
    scored = sorted(
        [(float(cos[i]) + boost.get(ids[i],0.0) + (0.0 if "/skills/" in paths[i] else 0.08), i) for i in range(len(ids))],
        reverse=True)[:top_k]
    res = [{"path": paths[i], "heading": heads[i], "score": round(s,3),
            "snippet": conts[i][:280].replace("\n"," ")} for s,i in scored]
    out = {"success": True, "query": query, "results": res}
    if as_json: print(json.dumps(out, ensure_ascii=False, indent=2))
    return out

def embed_cmd():
    """stdin JSON {"texts":[...]} -> stdout JSON {"dim":N,"vectors":[[...]]} (L2-normalized).
    Used by hermes_runtime.py as a torch-free embedding backend (isolated venv)."""
    import numpy as np
    data = json.load(sys.stdin)
    texts = list(data.get("texts", []))
    emb = _emb()
    vecs = []
    for v in emb.embed(texts):
        v = np.asarray(v, dtype="float32")
        v = v / (np.linalg.norm(v) + 1e-9)
        vecs.append([round(float(x), 7) for x in v])
    json.dump({"dim": DIM, "vectors": vecs}, sys.stdout, ensure_ascii=False)
    return 0


def run_benchmark(quiet=False):
    ok = 0
    for q, expect in BENCH:
        r = search(q, top_k=3, as_json=False)
        paths = " ".join(x["path"] for x in r.get("results",[]))
        hit = expect in paths
        ok += hit
        if not quiet:
            print(f"  [{'ok' if hit else 'MISS'}] '{q}' -> expect '{expect}' :: {'найдено' if hit else paths[:80]}")
    print(f"BENCHMARK: {ok}/{len(BENCH)} passed")
    return 0 if ok >= len(BENCH)*0.7 else 3

def verify():
    if not os.path.exists(DB): print("no index"); return 1
    c = sqlite3.connect(DB)
    n = c.execute("SELECT count(*) FROM documents").fetchone()[0]
    print(f"chunks: {n}")
    for p,cnt in c.execute("SELECT source_path,count(*) FROM documents GROUP BY source_path ORDER BY 1"):
        print(f"  {cnt:3d}  {p}")
    c.close(); return 0

def secret_scan():
    if not os.path.exists(DB): print("no index"); return 1
    c = sqlite3.connect(DB); bad = 0
    for rid,p,cont in c.execute("SELECT id,source_path,content FROM documents"):
        s = _scan_secret(cont)
        if s: print(f"  SECRET in {p} :: {s}"); bad += 1
    c.close()
    print(f"SECRET_SCAN: {'CLEAN' if not bad else str(bad)+' HITS'}")
    return 0 if not bad else 1

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rebuild-atomic"); sub.add_parser("verify")
    sub.add_parser("secret-scan"); sub.add_parser("benchmark"); sub.add_parser("embed")
    sp = sub.add_parser("search"); sp.add_argument("query"); sp.add_argument("--top-k", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "rebuild-atomic": sys.exit(rebuild_atomic())
    if a.cmd == "verify": sys.exit(verify())
    if a.cmd == "secret-scan": sys.exit(secret_scan())
    if a.cmd == "benchmark": sys.exit(run_benchmark())
    if a.cmd == "embed": sys.exit(embed_cmd())
    if a.cmd == "search": sys.exit(0 if search(a.query, a.top_k) else 1)
