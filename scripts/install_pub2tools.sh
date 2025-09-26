#!/usr/bin/env bash
set -euo pipefail


# Install Pub2Tools development version from source (see https://github.com/bio-tools/pub2tools/blob/develop/INSTALL.md)
# Usage: scripts/install_pub2tools.sh [branch]
# If branch is omitted, defaults to 'develop'

BRANCH="${1:-develop}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$ROOT_DIR/tools/pub2tools"
BIN_DIR="$ROOT_DIR/bin"
SRC_DIR="$DEST_DIR/pub2tools-src"
JAR_GLOB="$DEST_DIR/pub2tools-cli-*.jar"
mkdir -p "$DEST_DIR" "$BIN_DIR"


echo "Cloning Pub2Tools ($BRANCH) into $SRC_DIR ..." >&2
rm -rf "$SRC_DIR"
git clone --depth 1 --branch "$BRANCH" https://github.com/bio-tools/pub2tools.git "$SRC_DIR"


# Install pubfetcher dependency (always use develop branch)
PUBFETCHER_DIR="$DEST_DIR/pubfetcher-src"
echo "Cloning pubfetcher into $PUBFETCHER_DIR ..." >&2
rm -rf "$PUBFETCHER_DIR"
git clone --depth 1 --branch develop https://github.com/edamontology/pubfetcher.git "$PUBFETCHER_DIR"
echo "Building pubfetcher with Maven ..." >&2
cd "$PUBFETCHER_DIR"
mvn clean install -DskipTests

# Install edammap dependency (always use develop branch)
EDAMMAP_DIR="$DEST_DIR/edammap-src"
echo "Cloning edammap into $EDAMMAP_DIR ..." >&2
rm -rf "$EDAMMAP_DIR"
git clone --depth 1 --branch develop https://github.com/edamontology/edammap.git "$EDAMMAP_DIR"
echo "Building edammap with Maven ..." >&2
cd "$EDAMMAP_DIR"
mvn clean install -DskipTests

# Build Pub2Tools after dependencies
echo "Building Pub2Tools with Maven ..." >&2
cd "$SRC_DIR"
mvn clean package -DskipTests

# Copy all jar files to DEST_DIR (there are more than one!)
JAR_FILES=$(find "$SRC_DIR/target" -type f -name 'pub2tools-*.jar')
if [[ -z "$JAR_FILES" ]]; then
  echo "ERROR: Could not locate built pub2tools JARs in $SRC_DIR/target" >&2
  exit 1
fi
cp $JAR_FILES "$DEST_DIR/"

# Move lib folder to DEST_DIR
if [[ -d "$SRC_DIR/target/lib" ]]; then
  cp -r "$SRC_DIR/target/lib" "$DEST_DIR/"
fi

WRAPPER="$BIN_DIR/pub2tools"
cat > "$WRAPPER" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="$(find "${DIR}"/tools/pub2tools/ -maxdepth 2 -type f -name 'pub2tools-cli-*.jar' | head -n1)"
exec java -jar "${JAR}" "$@"
EOF
chmod +x "$WRAPPER"

echo "Installed Pub2Tools development wrapper at $WRAPPER" >&2
echo "Export PUB2TOOLS_CLI=$WRAPPER to use it from our CLI." >&2
