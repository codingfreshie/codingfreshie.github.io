"""Decides which repository paths may be listed or read. Defaults to excluding anything risky."""
from __future__ import annotations

import fnmatch
import posixpath
import re

EXCLUDED_DIRS = {
    ".git", "node_modules", "vendor", "venv", ".venv", "__pycache__", "site-packages", "__pypackages__",
    "dist", "build", "target", ".next", ".nuxt", ".cache", ".idea", ".vscode", "coverage",
    "bower_components", "pods", ".terraform", ".gradle", "third_party", "thirdparty", ".tox",
    ".mypy_cache", ".pytest_cache",
}
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker"}
SECRET_NAME_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.tfstate", "*.tfstate.*", "*.tfvars",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd", ".git-credentials", ".dockercfg",
    "credentials", "credentials.*", "secrets.*", "secret.*", "service-account*.json",
    "*serviceaccount*.json", "*.kdbx", "*.ovpn",
]
ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock", "gemfile.lock",
    "composer.lock", "go.sum", "uv.lock", "pipfile.lock", "bun.lockb", "flake.lock",
}
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".psd", ".svg", ".pdf",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
    ".a", ".o", ".obj", ".class", ".jar", ".war", ".pyc", ".pyo", ".woff", ".woff2", ".ttf", ".otf",
    ".eot", ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac", ".ogg", ".webm", ".bin", ".dat", ".iso",
    ".dmg", ".apk", ".ipa", ".wasm", ".db", ".sqlite", ".sqlite3",
}
DATA_EXTS = {
    ".csv", ".tsv", ".parquet", ".feather", ".h5", ".hdf5", ".pkl", ".pickle", ".npy", ".npz",
    ".pt", ".pth", ".ckpt", ".onnx", ".safetensors", ".pb", ".tflite", ".joblib", ".mat", ".jsonl",
}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".cpp",
    ".cc", ".c", ".h", ".hpp", ".swift", ".scala", ".sh", ".lua", ".dart", ".vue", ".svelte",
}


def is_safe_path(path: str) -> bool:
    """Rejects anything that could escape a directory or confuse downstream file handling."""
    if not path or "\x00" in path or "\\" in path or path.startswith("/"):
        return False
    return all(seg not in ("", ".", "..") for seg in path.split("/"))


def classify_path(path: str) -> str | None:
    """Return None if the path may be used, otherwise the reason it is excluded."""
    if not is_safe_path(path):
        return "unsafe"
    parts = [p.lower() for p in path.split("/")]
    name, dirs = parts[-1], parts[:-1]

    if any(d in SECRET_DIRS for d in dirs):
        return "secret"
    if name not in ENV_TEMPLATES and any(fnmatch.fnmatchcase(name, g) for g in SECRET_NAME_GLOBS):
        return "secret"
    if any(d in EXCLUDED_DIRS for d in dirs):
        return "vendored"
    if name in LOCKFILES:
        return "lockfile"
    if name.endswith((".min.js", ".min.css", ".map")):
        return "minified"
    ext = posixpath.splitext(name)[1]
    if ext in BINARY_EXTS:
        return "binary"
    if ext in DATA_EXTS:
        return "data"
    if "_pb2" in name or name.endswith((".pb.go", ".g.dart", ".generated.ts")):
        return "generated"
    return None


_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}


def summarize_tree(entries: list[dict], max_listed: int) -> tuple[dict, list[dict]]:
    """Filter a git tree. Returns (summary for the bundle, list of kept {path,size})."""
    kept: list[dict] = []
    skipped: dict[str, int] = {}
    for e in entries:
        reason = classify_path(e["path"])
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            kept.append({"path": e["path"], "size": e.get("size") or 0})

    lowered = [k["path"].lower() for k in kept]
    names = [p.rsplit("/", 1)[-1] for p in lowered]
    summary = {
        "total_entries": len(entries),
        "kept_count": len(kept),
        "skipped": dict(sorted(skipped.items())),
        "top_level_dirs": sorted({k["path"].split("/")[0] for k in kept if "/" in k["path"]}),
        "has_tests": any(
            (set(p.split("/")[:-1]) & _TEST_DIRS) or re.match(r"(test_.*\.py|.*_test\.(py|go)|.*\.(test|spec)\.[jt]sx?)$", n)
            for p, n in zip(lowered, names)
        ),
        "has_ci": any(p.startswith(".github/workflows/") or n in ("jenkinsfile", ".gitlab-ci.yml") for p, n in zip(lowered, names)),
        "has_docker": any(n == "dockerfile" or n.startswith("docker-compose") for n in names),
        "has_docs_dir": any(p.startswith("docs/") for p in lowered),
    }
    listed = sorted(kept, key=lambda k: (k["path"].count("/"), k["path"]))[:max_listed]
    summary["listed_paths"] = [k["path"] for k in listed]
    summary["listed_truncated"] = len(kept) > max_listed
    return summary, kept


_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py", "pipfile", "cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", "gemfile", "composer.json", "environment.yml",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile", "cmakelists.txt", ".env.example",
}
_ENTRY_NAMES = {
    "main.py", "app.py", "run.py", "manage.py", "__main__.py", "server.py", "wsgi.py", "asgi.py",
    "index.js", "main.js", "server.js", "app.js", "index.ts", "main.ts", "server.ts", "app.ts",
    "main.go", "main.rs", "lib.rs", "main.java", "program.cs", "main.cpp", "main.c", "index.html",
}


# Tooling configuration says little about what a project does.
_TOOLING_CONFIG = re.compile(r"(\.(config|conf)\.[cm]?[jt]s$)|(^conftest\.py$)")
_DOC_KEYWORDS = re.compile(r"grammar|design|architecture|spec|notes|overview|usage|api|guide|protocol")

MAX_NOTEBOOK_BYTES = 1_500_000  # notebooks are large mostly because of outputs, which are dropped


def select_files(kept: list[dict], max_file_bytes: int, max_files: int) -> list[dict]:
    """Pick the few files most likely to explain what the project is, in priority order."""
    candidates: list[tuple[int, int, str, int]] = []
    for k in kept:
        path, size = k["path"], k["size"]
        low = path.lower()
        name = low.rsplit("/", 1)[-1]
        depth = low.count("/")
        ext = posixpath.splitext(name)[1]
        prio = None
        if depth == 0 and name.startswith("readme"):
            prio = 0
        elif depth == 0 and name in ("architecture.md", "design.md"):
            prio = 1
        elif depth == 0 and name in _MANIFESTS:
            prio = 1
        elif depth <= 2 and name in _MANIFESTS:
            prio = 3
        elif name in _ENTRY_NAMES and depth <= 2 and not (name == "index.html" and depth > 0):
            prio = 2
        elif depth == 2 and low.startswith("cmd/") and name == "main.go":
            prio = 2
        elif low.startswith(".github/workflows/") and name.endswith((".yml", ".yaml")):
            prio = 5
        elif low.startswith("docs/") and ext == ".md" and depth <= 2:
            prio = 4
        elif depth == 0 and ext in (".md", ".txt", ".rst") and size <= 20_000 and _DOC_KEYWORDS.search(name):
            prio = 4
        elif (ext in CODE_EXTS and depth <= 3 and 300 <= size <= 40_000
              and not (set(low.split("/")[:-1]) & _TEST_DIRS) and not _TOOLING_CONFIG.search(name)):
            prio = 6
        elif ext == ".ipynb" and depth <= 2 and size <= MAX_NOTEBOOK_BYTES:
            prio = 7
        if prio is None:
            continue
        if prio not in (0, 7) and size > max_file_bytes:
            continue
        candidates.append((prio, depth, path, size))

    candidates.sort(key=lambda c: (c[0], 0 if c[0] == 6 else c[1], -c[3] if c[0] == 6 else 0, c[2]))
    caps = {4: 3, 5: 2, 6: 6, 7: 3}
    used: dict[int, int] = {}
    picked: list[dict] = []
    for prio, _depth, path, size in candidates:
        if used.get(prio, 0) >= caps.get(prio, 999):
            continue
        used[prio] = used.get(prio, 0) + 1
        picked.append({"path": path, "size": size, "priority": prio})
        if len(picked) >= max_files:
            break
    return picked

