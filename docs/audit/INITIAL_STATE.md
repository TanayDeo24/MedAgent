# INITIAL_STATE.md — Forensic Audit, MedAgent

Audit performed: 2026-09-23. Read-only audit; no files outside `docs/audit/` and
`artifacts/audit/` were modified. No `git rebase/reset/checkout/commit` commands
were run.

## 1. CRITICAL: the working tree currently has ZERO Python source files

This is the single most important fact about the repository's current state and
governs how the rest of this audit had to be conducted.

- `git status` reports: *"interactive rebase in progress; onto 58a2b2f... Last
  commands done (4 commands done): pick b4af5c0 ...; reset [new root]... Next
  commands to do (135 remaining commands)"*.
- `HEAD` currently points at commit `58a2b2f5ebb63d464fa31e8c420333124ad0819d`,
  which `git show 58a2b2f --stat` proves is an **empty commit with no files at
  all** (`git ls-tree -r 58a2b2f --name-only` returns nothing). It is the `reset
  [new root]` step of the in-progress interactive rebase (`.git/rebase-merge/onto`
  = `58a2b2f...`, `.git/rebase-merge/orig-head` = `14a59b9e4c514714883245e8ac1e95a2f1457775`).
- Because `git checkout`/rebase machinery only touches **tracked** files, and every
  file was tracked before the rebase reset HEAD to an empty root, checking out the
  empty root **deleted every tracked `.py`/`.md`/`.json` source file from the
  working directory**. What remains on disk under `agent/`, `config/`,
  `evaluation/`, `retrieval/`, `tests/`, `tools/`, `utils/` is **only
  `__pycache__/` directories** (compiled `.pyc` bytecode, which was never tracked
  by git and so survived the checkout untouched). Verified directly:
  `find agent config evaluation retrieval tests tools utils -not -path
  '*/__pycache__*'` returns nothing but the bare directories themselves.
- `git status` also lists the root `*_COMPLETE.md` narrative files, `data/`,
  `logs/`, and `.env` as **untracked** (`??`) — they were never committed at all
  (they postdate the last commit, or were always gitignored/untracked), which is
  why they survived the reset intact.
- `git reflog` shows the rebase's `orig-head` / branch tip before the rebase
  started was `14a59b9` ("Phase 1 to Phase 3 complete of the build with clean
  hybrid RAG and BM25 and RRF pipeline"), reachable from `main` and
  `phase3-rag`. `git stash list` is empty — nothing is stashed.
- **This audit's only way to inspect the actual source code was to read it
  read-only out of git history** — `git archive 14a59b9 | tar -x` into this
  session's scratchpad directory (never touching the working tree or the
  in-progress rebase), because `git show <rev>:<path>` / `git archive <rev>` are
  non-destructive, read-only git operations, not checkout/reset/rebase. All code
  citations elsewhere in this audit that reference `agent/`, `config/`,
  `tools/`, `retrieval/`, `evaluation/`, `utils/` `.py` files are citing this
  git-history snapshot (commit `14a59b9`), **not** files present in the current
  working tree, unless explicitly stated otherwise. This is clearly marked
  throughout.
- Practical consequence verified directly: `venv/bin/python -m pytest tests/ -q`
  run from the actual working directory produces **"no tests ran in 0.00s"** —
  the test suite is currently uncollectable and unrunnable in this repository's
  present on-disk state, regardless of what any completion doc claims about test
  pass rates.
- **This audit does not resolve, continue, or abort the rebase**, per
  instructions. The repository is left exactly as found.

## 2. Git state

| Field | Value |
|---|---|
| `git status` branch | `(no branch, rebasing main)` — mid interactive rebase |
| `main` branch tip (before rebase) | `14a59b9e4c514714883245e8ac1e95a2f1457775` |
| Other local branch | `phase3-rag` |
| Remote | `remotes/origin/main` |
| Current `HEAD` | `58a2b2f5ebb63d464fa31e8c420333124ad0819d` (empty commit, rebase's new root) |
| Rebase todo remaining | 136 lines in `.git/rebase-merge/git-rebase-todo` (~135 commands) |
| Currently editing | commit `b4af5c0` ("Initial commit: MedAgent baseline state (Day 1-3 / Phase 1-3 work)") via `exec git commit --amend --no-edit --reset-author` |
| Stash | empty |
| Untracked files | `.env`, all 11 root `*_COMPLETE.md`/`*_INVESTIGATION.md` files, `agent/`, `config/`, `data/`, `evaluation/`, `logs/`, `retrieval/`, `tests/`, `tools/`, `utils/`, `venv/` |

## 3. Environment

| Field | Value |
|---|---|
| Python | 3.12.7 (`python3 --version`) |
| OS | Darwin 24.6.0 (macOS, arm64 / Apple Silicon — `Darwin Mac 24.6.0 ... RELEASE_ARM64_T8122`) |
| Repo total size | 1.6 GB (`du -sh .`) |
| `venv/` size | 1.2 GB (excluded from manual reading per instructions; a real, populated virtualenv exists, `venv/bin/pytest` present) |
| `data/` size | 406 MB |
| `logs/` size | 3.9 MB (`logs/medagent.log`, 19,159 lines) |
| `agent/`, `config/`, `evaluation/`, `retrieval/`, `tests/`, `tools/`, `utils/` sizes | 92K/28K/116K/40K/116K/60K/32K — this is `__pycache__` bytecode only (see §1), not source |
| Dependencies | No `requirements*.txt` present anywhere in the current working tree (git history's `requirements.txt`, read via `git show 14a59b9:requirements.txt`, lists pinned versions — see `ACTUAL_ARCHITECTURE.md` §Dependencies) |

## 4. `.env` (existence and key names only — no values printed)

`.env` exists in the working directory (untracked). It defines exactly these keys:
`NVIDIA_API_KEY`, `LOG_LEVEL`, `LOG_FILE`. `NVIDIA_API_KEY`'s value was not
inspected for content beyond confirming the key name is present (per instructions,
values are never printed). Whether it holds a live, working key was not
determined — see `AUDIT_REPORT.md` §35 (Reproducibility) for why no live-API
evaluation run was attempted.

## 5. Data / index directories present on disk (from the current, untracked working tree)

```
data/corpus/abstracts.jsonl            9,000 lines  (biomedical abstracts)
data/corpus/abstracts_raw_all.jsonl   13,115 lines  (pre-filter raw pull)
data/index/faiss.index, chunks.jsonl (22,674 lines), bm25.pkl, bm25_meta.json, index_meta.json
data/index/variants/bge_base_180_30/       (alternate embedding-model index build)
data/index/variants/chunk_256_50/          (alternate chunk-size index build)
data/index/variants/chunk_384_64/          (alternate chunk-size index build)
```
Full detail in `AUDIT_REPORT.md` §13.
