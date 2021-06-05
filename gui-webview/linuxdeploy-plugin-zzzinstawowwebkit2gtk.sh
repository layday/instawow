#! /bin/bash

# Adapted from https://github.com/linuxdeploy/linuxdeploy-plugin-gtk,
# licensed under MIT.

# abort on all errors
set -e

if [ "$DEBUG" != "" ]; then
    set -x
    verbose="--verbose"
fi

script=$(readlink -f "$0")

show_usage() {
    echo "Usage: $script --appdir <path to AppDir>"
    echo
    echo "Bundles resources for applications that use Gtk 2 or 3 into an AppDir"
}

copy_tree() {
    local src=("${@:1:$#-1}")
    local dst="${*:$#}"

    for elem in "${src[@]}"; do
        cp "$elem" --archive --parents --target-directory="$dst" $verbose
    done
}

APPDIR=

while [ "$1" != "" ]; do
    case "$1" in
        --plugin-api-version)
            echo "0"
            exit 0
            ;;
        --appdir)
            APPDIR="$2"
            shift
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            echo "Invalid argument: $1"
            echo
            show_usage
            exit 1
            ;;
    esac
done

if [ "$APPDIR" == "" ]; then
    show_usage
    exit 1
fi

mkdir -p "$APPDIR"

if command -v pkgconf > /dev/null; then
    PKG_CONFIG="pkgconf"
elif command -v pkg-config > /dev/null; then
    PKG_CONFIG="pkg-config"
else
    echo "$0: pkg-config/pkgconf not found in PATH, aborting"
    exit 1
fi

if [ -z "$LINUXDEPLOY" ]; then
    echo -e "$0: LINUXDEPLOY environment variable is not set.\nDownload a suitable linuxdeploy AppImage, set the environment variable and re-run the plugin."
    exit 1
fi

echo "Deploy proot"
curl -L https://gitlab.com/proot/proot/-/jobs/1316384571/artifacts/download -o proot.zip
unzip proot
chmod +x dist/proot
cp dist/proot "$APPDIR/usr/bin"

echo "Installing gi.repository typelibdir"
gir_typelibdir="$("$PKG_CONFIG" --variable=typelibdir gobject-introspection-1.0)"
copy_tree "$gir_typelibdir" "$APPDIR/"

echo "Installing WebKitGTK paraphernalia"
webkit2gtk_libdir="$("$PKG_CONFIG" --variable=libdir webkit2gtk-4.0)"
copy_tree "$webkit2gtk_libdir/webkit2gtk-4.0" "$APPDIR/"

echo "Modifying runner"
proot_args=()
proot_args+=( "-b \$APPDIR$gir_typelibdir:$gir_typelibdir" )
proot_args+=( "-b \$APPDIR$webkit2gtk_libdir/webkit2gtk-4.0:$webkit2gtk_libdir/webkit2gtk-4.0" )
for library in "$APPDIR/usr/lib/"*.so*
do
    name=$(basename "$library")
    proot_args+=( "-b \$APPDIR/usr/lib/$name:/usr/lib/$name" )
done
RUNNER="$APPDIR/usr/bin/org.instawow.instawow-gui-wrapper"
echo "#!/bin/bash
export PYTHONPATH=\$APPDIR/usr/app:\$APPDIR/usr/app_packages
\$APPDIR/usr/bin/proot" "${proot_args[@]}" "\$APPDIR/usr/bin/python3 -s -m instawow_gui_wrapper \"\$@\"
" > "$RUNNER"
