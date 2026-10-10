#!/bin/sh
# Foreground build only; does not install or reload a host.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
version=$(while IFS= read -r line; do
    case "$line" in
        *'pluginVersion = "'*)
            value=${line#*'pluginVersion = "'}
            printf '%s' "${value%%\"*}"
            break
            ;;
    esac
done < main.go)
[ -n "$version" ] || { printf '%s\n' 'Cannot determine pluginVersion' >&2; exit 1; }
mkdir -p dist
CGO_ENABLED=1 go build -trimpath -buildmode=c-shared -o "dist/models-context-v${version}.so" .
printf 'Built dist/models-context-v%s.so\n' "$version"
