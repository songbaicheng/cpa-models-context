#!/bin/sh
# Foreground build only; does not install or reload a host.
#
# Honours GOOS so a cross or native build picks the right shared-library
# extension: .so on Linux, .dylib on macOS, .dll on Windows. The plugin store's
# zip layout requires the library to be named after the plugin id, so the
# extension has to be right the first time.
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

goos=${GOOS:-$(go env GOOS)}
case "$goos" in
    linux) ext=so ;;
    darwin) ext=dylib ;;
    windows) ext=dll ;;
    *) printf 'Unsupported GOOS %s\n' "$goos" >&2; exit 1 ;;
esac

mkdir -p dist
CGO_ENABLED=1 go build -trimpath -buildmode=c-shared \
    -o "dist/models-context-v${version}.${ext}" .
printf 'Built dist/models-context-v%s.%s\n' "$version" "$ext"
