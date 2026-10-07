#!/usr/bin/env bash
# Start or stop one of the web apps in the background — what webview.sh, webalign.sh and
# their -stop.sh siblings in the repo root call.
#
#   scripts/serve.sh start <name> <default port> <monday subcommand> [options…]
#   scripts/serve.sh stop  <name> <default port>
#
# `start` runs the app in its own session, so the terminal comes straight back, and waits
# until the port answers. The port is the wrapper's default unless `--port` is passed
# through, and is always handed to the app itself. The output goes to .run/<name>.log; the process group and the port
# are kept in .run/<name>.pid and .run/<name>.port. `stop` ends the whole group — uv, the
# uvicorn reloader and its worker — and, if anything still holds the port, that too.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$REPO/.run"

action="${1:?usage: serve.sh start|stop <name> <port> [subcommand options…]}"
name="${2:?name missing}"
default_port="${3:?port missing}"
shift 3

pidfile="$RUN/$name.pid"
portfile="$RUN/$name.port"
logfile="$RUN/$name.log"

listening() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
holders() { lsof -t -i ":$1" -sTCP:LISTEN 2>/dev/null || true; }

start() {
    local subcommand="${1:?subcommand missing}"
    shift
    # The port the app will use: the default, unless --port is passed through.
    local port="$default_port" prev=""
    for arg in "$@"; do
        case "$arg" in
            --port=*) port="${arg#--port=}" ;;
            *) [[ "$prev" == "--port" ]] && port="$arg" ;;
        esac
        prev="$arg"
    done
    if listening "$port"; then
        echo "$name is already running on http://127.0.0.1:$port  (stop it with ./$name-stop.sh)"
        return 0
    fi
    mkdir -p "$RUN"
    # setsid makes the app a process group of its own, so stop can end it as a whole.
    # The port goes to the app explicitly, so what this waits on and what it binds are one value.
    setsid uv run --project "$REPO" monday "$subcommand" "$@" --port "$port" >"$logfile" 2>&1 </dev/null &
    echo "$!" >"$pidfile"
    echo "$port" >"$portfile"
    printf "starting %s" "$name"
    for _ in $(seq 60); do
        if listening "$port"; then
            echo
            echo "$name runs on http://127.0.0.1:$port  (log: .run/$name.log, stop: ./$name-stop.sh)"
            return 0
        fi
        if ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            echo
            echo "$name did not start. The end of .run/$name.log:" >&2
            tail -n 20 "$logfile" >&2
            rm -f "$pidfile" "$portfile"
            return 1
        fi
        printf "."
        sleep 0.5
    done
    echo
    echo "$name is still starting; see .run/$name.log" >&2
}

stop() {
    local port="$default_port" pgid=""
    [[ -f "$portfile" ]] && port="$(cat "$portfile")"
    [[ -f "$pidfile" ]] && pgid="$(cat "$pidfile")"
    if [[ -n "$pgid" ]] && kill -0 "$pgid" 2>/dev/null; then
        kill -TERM -- "-$pgid" 2>/dev/null || true
    fi
    # Started some other way (or the group outlived its pid file): end whatever holds the port.
    for _ in $(seq 20); do
        listening "$port" || break
        holders "$port" | xargs -r kill -TERM 2>/dev/null || true
        sleep 0.5
    done
    if listening "$port"; then
        holders "$port" | xargs -r kill -KILL 2>/dev/null || true
        sleep 0.5
    fi
    rm -f "$pidfile" "$portfile"
    if listening "$port"; then
        echo "port $port is still in use; check with: lsof -i :$port" >&2
        return 1
    fi
    echo "$name stopped (port $port is free)"
}

case "$action" in
    start) start "$@" ;;
    stop) stop ;;
    *) echo "usage: serve.sh start|stop <name> <port> [subcommand options…]" >&2; exit 2 ;;
esac
