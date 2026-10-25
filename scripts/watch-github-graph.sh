#!/usr/bin/env bash
# Keep graphify-out/ in step with the project's GitHub branch.
#
# The graph is local-only: graphify-out/ is git-ignored and never committed or
# pushed. Every INTERVAL seconds this fetches REMOTE/BRANCH, fast-forwards when
# GitHub has new commits, then re-runs graphify's LLM-free code rebuild if
# graph.json was built at a different commit than HEAD. It never commits,
# pushes, rebases, or forces: git's own checkout safety decides what it may
# update, and a blocked sync is retried on the next pass.
#
# When something needs a human or agent (changed docs/media that need semantic
# extraction, a rebuild failure, divergence), it writes
# graphify-out/.graphify_watch/agent-task.md with the reason, files and a
# suggested command, and logs "agent action requested".
#
#   scripts/watch-github-graph.sh           # run until SIGINT/SIGTERM
#   scripts/watch-github-graph.sh --once    # one check, then exit
#
# Environment overrides:
#   INTERVAL=60  REMOTE=origin  BRANCH=main  REPO_DIR=<repo>  GRAPHIFY_BIN=<path>
#
# Logs and state live in graphify-out/.graphify_watch/ (git-ignored).

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: watch-github-graph.sh [--once]

Fetch REMOTE/BRANCH, fast-forward when GitHub has new commits, and rebuild the
graphify code graph when graph.json was built at a different commit than HEAD.
Work only an agent can do is written to graphify-out/.graphify_watch/agent-task.md.

  --once    run a single check and exit (0 = no error, 1 = check failed)

Environment: INTERVAL=60 REMOTE=origin BRANCH=main REPO_DIR=<repo> GRAPHIFY_BIN=<path>
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
INTERVAL="${INTERVAL:-60}"
ONCE=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --once) ONCE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "watch-github-graph: unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

if ! git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    echo "watch-github-graph: $REPO_DIR is not a git repository" >&2
    exit 1
fi

GRAPH_JSON="$REPO_DIR/graphify-out/graph.json"
STATE_DIR="$REPO_DIR/graphify-out/.graphify_watch"
LOG_FILE="$STATE_DIR/watch.log"
TASK_FILE="$STATE_DIR/agent-task.md"
BLOCKED_FILE="$STATE_DIR/blocked_sha"
FAILED_FILE="$STATE_DIR/failed_head"
GRAPHIFIED_FILE="$STATE_DIR/graphified_sha"
BRANCH_NOTICE="$STATE_DIR/branch_notice"
REQUEST_KEY_FILE="$STATE_DIR/request.key"
KEPT_FILE="$STATE_DIR/kept.key"
PID_FILE="$STATE_DIR/watch.pid"

# Files whose content only a semantic (LLM) pass can add to the graph.
SEMANTIC_RE='\.(md|mdx|rst|txt|pdf|png|jpe?g|gif|webp|svg|mp4|mov|webm|mp3|wav|m4a)$'

mkdir -p "$STATE_DIR"
if [ -f "$LOG_FILE" ] && [ "$(wc -c <"$LOG_FILE")" -gt 2097152 ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1"
fi

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

GRAPHIFY_BIN="${GRAPHIFY_BIN:-$(command -v graphify || true)}"
if [ -z "$GRAPHIFY_BIN" ] || [ ! -x "$GRAPHIFY_BIN" ]; then
    for candidate in "$HOME/.local/bin/graphify" /usr/local/bin/graphify; do
        if [ -x "$candidate" ]; then
            GRAPHIFY_BIN="$candidate"
            break
        fi
    done
fi
if [ -z "${GRAPHIFY_BIN:-}" ] || [ ! -x "$GRAPHIFY_BIN" ]; then
    echo "watch-github-graph: graphify CLI not found (install graphifyy or set GRAPHIFY_BIN)" >&2
    exit 1
fi

PYTHON="$(cat "$REPO_DIR/graphify-out/.graphify_python" 2>/dev/null || true)"
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3 || true)"
fi

# One watcher per checkout: two rebuilds racing on graph.json would fight.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$STATE_DIR/watch.lock"
    if ! flock -n 9; then
        echo "watch-github-graph: another watcher is already running for $REPO_DIR" >&2
        exit 0
    fi
fi
printf '%s\n' "$$" >"$PID_FILE"

fetch_remote() {
    GIT_TERMINAL_PROMPT=0 timeout 60 \
        git -C "$REPO_DIR" fetch --quiet "$REMOTE" \
        "+refs/heads/$BRANCH:refs/remotes/$REMOTE/$BRANCH" >>"$LOG_FILE" 2>&1
}

graph_stamp() {
    [ -n "$PYTHON" ] || return 0
    [ -f "$GRAPH_JSON" ] || return 0
    "$PYTHON" - "$GRAPH_JSON" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.load(fh).get("built_at_commit") or "")
except Exception:
    print("")
PY
}

graph_summary() {
    [ -n "$PYTHON" ] || { echo "graph.json updated"; return 0; }
    "$PYTHON" - "$GRAPH_JSON" <<'PY' 2>/dev/null || echo "graph.json updated"
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        graph = json.load(fh)
    nodes = len(graph.get("nodes", []))
    links = len(graph.get("links", graph.get("edges", [])))
    stamp = (graph.get("built_at_commit") or "")[:8] or "unknown"
    print(f"{nodes} nodes, {links} edges at {stamp}")
except Exception:
    print("graph.json updated")
PY
}

# Docs, papers, images and media that changed between two commits. These need
# the semantic pass, which the CLI's code-only rebuild cannot do.
semantic_changes() {
    local from="$1" to="$2"
    {
        if [ -z "$from" ] || ! git -C "$REPO_DIR" cat-file -e "$from^{commit}" 2>/dev/null; then
            git -C "$REPO_DIR" ls-files
        else
            git -C "$REPO_DIR" diff --name-only --diff-filter=ACMR "$from" "$to"
        fi
    } | grep -Ei "$SEMANTIC_RE" || true
}

# Hand work to a local agent through a file it can read. One request per state:
# the key stops the same request being rewritten and re-logged every tick.
agent_request() {
    local kind="$1" reason="$2" files="${3:-}" hint="${4:-}"
    local head graph key tmp

    head="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    graph="$(graph_stamp)"
    key="${kind}|${head}|${graph}|$(printf '%s\n%s' "$reason" "$files" | cksum | cut -d' ' -f1)"

    if [ "$(cat "$REQUEST_KEY_FILE" 2>/dev/null || true)" = "$key" ]; then
        return 0
    fi

    # Keep a pending semantic request visible even while a transient problem
    # (failed fetch, divergence) is being reported in the log.
    if [ "$kind" = "transient" ] && [ -f "$TASK_FILE" ] &&
        grep -q '^- kind: semantic$' "$TASK_FILE"; then
        if [ "$(cat "$KEPT_FILE" 2>/dev/null || true)" != "$key" ]; then
            printf '%s\n' "$key" >"$KEPT_FILE"
            log "note: $reason (existing semantic request kept)"
        fi
        return 0
    fi

    printf '%s\n' "$key" >"$REQUEST_KEY_FILE"
    tmp="$TASK_FILE.tmp"
    {
        printf '# Graphify: agent action requested\n\n'
        printf -- '- kind: %s\n' "$kind"
        printf -- '- detected: %s\n' "$(date -Iseconds)"
        printf -- '- repo: %s\n' "$REPO_DIR"
        printf -- '- branch: %s/%s\n' "$REMOTE" "$BRANCH"
        printf -- '- head: %s\n' "$head"
        printf -- '- graph: %s\n' "${graph:-none}"
        printf '\n## Why\n\n%s\n' "$reason"
        if [ -n "$files" ]; then
            printf '\n## Files\n\n'
            printf '%s\n' "$files" | sed 's/^/- /'
        fi
        if [ -n "$hint" ]; then
            printf '\n## Suggested action\n\n%s\n' "$hint"
        fi
        printf '\nThis file is local-only (graphify-out/ is ignored). Delete it once the graph is updated.\n'
    } >"$tmp"
    mv -f "$tmp" "$TASK_FILE"
    log "agent action requested ($kind): $reason - see $TASK_FILE"
}

# Clear a request the watcher itself raised, once the condition is gone. A
# semantic request stays until an agent handles it and deletes the file.
clear_transient_request() {
    [ -f "$TASK_FILE" ] || return 0
    if grep -q '^- kind: transient$' "$TASK_FILE"; then
        rm -f "$TASK_FILE" "$REQUEST_KEY_FILE"
    fi
}

# $1 = HEAD being graphed, $2 = commit graph.json currently describes.
rebuild_graph() {
    local head="$1" stamp="$2" new_stamp

    log "graph is at ${stamp:0:8}, HEAD is ${head:0:8}: rebuilding (AST only, no LLM)"
    if (cd "$REPO_DIR" && GRAPHIFY_NO_TIPS=1 "$GRAPHIFY_BIN" update "$REPO_DIR") >>"$LOG_FILE" 2>&1; then
        new_stamp="$(graph_stamp)"
        rm -f "$FAILED_FILE"
        # graphify skips rewriting graph.json when the code topology did not
        # change; the update still succeeded, so record that this HEAD is done.
        printf '%s\n' "$head" >"$GRAPHIFIED_FILE"
        if [ "$new_stamp" = "$head" ]; then
            log "graph rebuilt: $(graph_summary)"
        else
            log "graph unchanged at ${head:0:8}: no code-topology change (graph.json still stamped ${new_stamp:0:8})"
        fi
        return 0
    fi

    printf '%s\n' "$head" >"$FAILED_FILE"
    log "graph rebuild failed; details in $LOG_FILE (retrying when HEAD changes)"
    return 1
}

FETCH_FAILURES=0
SLEEP_PID=""

tick() {
    local current remote_sha head stamp graphified subject docs blocked=0

    current="$(git -C "$REPO_DIR" symbolic-ref --quiet --short HEAD || true)"
    if [ "$current" != "$BRANCH" ]; then
        if [ "$(cat "$BRANCH_NOTICE" 2>/dev/null || true)" != "$current" ]; then
            log "checked-out branch is '${current:-detached HEAD}', not '$BRANCH': sync paused"
            printf '%s\n' "$current" >"$BRANCH_NOTICE"
        fi
        agent_request transient \
            "checked-out branch is '${current:-detached HEAD}', not '$BRANCH'" "" \
            "Check out $BRANCH (or run with BRANCH=$current). The watcher resumes automatically."
        return 0
    fi
    rm -f "$BRANCH_NOTICE"

    if ! fetch_remote; then
        FETCH_FAILURES=$((FETCH_FAILURES + 1))
        if [ "$FETCH_FAILURES" -eq 1 ] || [ $((FETCH_FAILURES % 10)) -eq 0 ]; then
            log "fetch of $REMOTE/$BRANCH failed ($FETCH_FAILURES in a row); check credentials/network, details in $LOG_FILE"
        fi
        agent_request transient \
            "fetching $REMOTE/$BRANCH failed ($FETCH_FAILURES in a row)" "" \
            "Check network access and git credentials. The watcher retries automatically."
        return 1
    fi
    FETCH_FAILURES=0

    remote_sha="$(git -C "$REPO_DIR" rev-parse --verify --quiet "refs/remotes/$REMOTE/$BRANCH")" || {
        log "no ref refs/remotes/$REMOTE/$BRANCH after fetch"
        return 1
    }
    head="$(git -C "$REPO_DIR" rev-parse HEAD)" || {
        log "cannot resolve HEAD in $REPO_DIR"
        return 1
    }

    if [ "$remote_sha" != "$head" ]; then
        if git -C "$REPO_DIR" merge-base --is-ancestor "$head" "$remote_sha"; then
            # GitHub has commits we lack: fast-forward only, so local work is
            # never rewritten. A dirty tree that would be overwritten aborts.
            if git -C "$REPO_DIR" merge --ff-only --quiet "$remote_sha" >>"$LOG_FILE" 2>&1; then
                head="$remote_sha"
                rm -f "$BLOCKED_FILE"
                subject="$(git -C "$REPO_DIR" log -1 --format=%s "$head")"
                log "fast-forwarded to ${remote_sha:0:8} - $subject"
                clear_transient_request
            else
                if [ "$(cat "$BLOCKED_FILE" 2>/dev/null || true)" != "$remote_sha" ]; then
                    log "cannot fast-forward to ${remote_sha:0:8}: local changes or a checkout error blocked it; graph left alone (details in $LOG_FILE)"
                    printf '%s\n' "$remote_sha" >"$BLOCKED_FILE"
                fi
                blocked=1
                agent_request transient \
                    "cannot fast-forward to ${remote_sha:0:8}" "" \
                    "Commit or stash the local changes that conflict. The next pass retries the fast-forward."
            fi
        elif git -C "$REPO_DIR" merge-base --is-ancestor "$remote_sha" "$head"; then
            # Local branch is ahead of GitHub; nothing new to take.
            rm -f "$BLOCKED_FILE"
        else
            if [ "$(cat "$BLOCKED_FILE" 2>/dev/null || true)" != "$remote_sha" ]; then
                log "local $BRANCH and $REMOTE/$BRANCH have diverged (${head:0:8} vs ${remote_sha:0:8}); merge or rebase to resume"
                printf '%s\n' "$remote_sha" >"$BLOCKED_FILE"
            fi
            blocked=1
            agent_request transient \
                "local $BRANCH (${head:0:8}) and $REMOTE/$BRANCH (${remote_sha:0:8}) have diverged" "" \
                "Merge or rebase $REMOTE/$BRANCH. The next pass rebuilds the graph automatically."
        fi
    fi

    stamp="$(graph_stamp)"
    graphified="$(cat "$GRAPHIFIED_FILE" 2>/dev/null || true)"
    if [ "$stamp" = "$head" ] || [ "$graphified" = "$head" ]; then
        [ "$blocked" -eq 0 ] && clear_transient_request
        return 0
    fi

    if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$head" ]; then
        return 0
    fi

    docs="$(semantic_changes "$stamp" "$head")"
    if rebuild_graph "$head" "$stamp"; then
        if [ -n "$docs" ]; then
            agent_request semantic \
                "$(printf '%s\n' "$docs" | wc -l | tr -d ' ') changed documentation/media file(s) need semantic extraction$([ "$blocked" -eq 1 ] && printf ' (git is also diverged from %s/%s)' "$REMOTE" "$BRANCH")" \
                "$docs" \
                "Run the graphify skill's incremental update for these files (graphify update alone only re-extracts code), then delete this file. If git is diverged, merge or rebase $REMOTE/$BRANCH too."
        elif [ "$blocked" -eq 0 ]; then
            clear_transient_request
        fi
    else
        agent_request transient \
            "graphify rebuild failed for ${head:0:8}" "" \
            "Inspect $LOG_FILE, then run graphify update \"$REPO_DIR\"."
    fi
}

log "watching $REMOTE/$BRANCH every ${INTERVAL}s in $REPO_DIR"
initial_stamp="$(graph_stamp)"
if [ -n "$initial_stamp" ]; then
    log "graph built at ${initial_stamp:0:8}; log: $LOG_FILE"
else
    log "no graph yet; log: $LOG_FILE"
fi

if [ "$ONCE" -eq 1 ]; then
    if tick; then
        date -Iseconds >"$STATE_DIR/last_check" 2>/dev/null || true
        exit 0
    fi
    date -Iseconds >"$STATE_DIR/last_check" 2>/dev/null || true
    exit 1
fi

trap 'kill "${SLEEP_PID:-""}" 2>/dev/null || true; log "watcher stopped"; exit 0' INT TERM
while :; do
    tick || true
    date -Iseconds >"$STATE_DIR/last_check" 2>/dev/null || true
    # 9>&- keeps the sleep child from inheriting (and holding) the flock.
    sleep "$INTERVAL" 9>&- &
    SLEEP_PID=$!
    wait "$SLEEP_PID" || true
    SLEEP_PID=""
done
