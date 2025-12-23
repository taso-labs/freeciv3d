#!/bin/bash
# Sync JavaScript files from source to running Docker container
# Usage: ./scripts/sync-js-to-docker.sh [specific-file.js]

CONTAINER="fciv-net"
SRC_DIR="freeciv-web/src/main/webapp/javascript"
DEST_DIR="/var/lib/tomcat10/webapps/freeciv-web/javascript"

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Error: Container ${CONTAINER} is not running"
    exit 1
fi

if [ -n "$1" ]; then
    # Sync specific file
    FILE="$1"
    if [ -f "${SRC_DIR}/${FILE}" ]; then
        docker cp "${SRC_DIR}/${FILE}" "${CONTAINER}:${DEST_DIR}/${FILE}"
        echo "Synced: ${FILE}"
    elif [ -f "${SRC_DIR}/webgl/${FILE}" ]; then
        docker cp "${SRC_DIR}/webgl/${FILE}" "${CONTAINER}:${DEST_DIR}/webgl/${FILE}"
        echo "Synced: webgl/${FILE}"
    else
        echo "Error: File not found: ${FILE}"
        exit 1
    fi
else
    # Sync all modified JS files (compared to container)
    echo "Syncing all JavaScript files..."

    # Core files that are commonly modified
    CORE_FILES=(
        "civclient.js"
        "client_main.js"
        "messages.js"
        "packhand.js"
        "clinet.js"
        "pregame.js"
    )

    # WebGL files
    WEBGL_FILES=(
        "webgl/renderer_main.js"
        "webgl/mapview.js"
        "webgl/mapctrl.js"
    )

    for file in "${CORE_FILES[@]}"; do
        if [ -f "${SRC_DIR}/${file}" ]; then
            docker cp "${SRC_DIR}/${file}" "${CONTAINER}:${DEST_DIR}/${file}"
            echo "  Synced: ${file}"
        fi
    done

    for file in "${WEBGL_FILES[@]}"; do
        if [ -f "${SRC_DIR}/${file}" ]; then
            docker cp "${SRC_DIR}/${file}" "${CONTAINER}:${DEST_DIR}/${file}"
            echo "  Synced: ${file}"
        fi
    done

    echo "Done! Hard refresh your browser (Cmd+Shift+R) to see changes."
fi
