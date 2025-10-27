Freeciv C server
----------------

This is the forked Freeciv C server.

prepare_freeciv.sh  - a script which will checkout Freeciv from Git, then patch apply the patches and finally configure and compile the Freeciv C server.


version.txt - contains the Git revision of Freeciv to check out from Git.


## Protocol Definition and JavaScript Client Integration

### packets.def - Network Protocol Definition

The file `freeciv/common/networking/packets.def` is the **single source of truth** for the network protocol between the C server and JavaScript client.

**After modifying packets.def**, you must regenerate the JavaScript packet handlers:

```bash
# From project root, regenerate JavaScript packet handlers
./scripts/generate_js_hand/generate_js_hand.py \
  -f ./freeciv/freeciv \
  -o ./freeciv-web/src/main/webapp

# Or use the full sync script (recommended - also syncs help, sprites, sounds)
./scripts/sync-js-hand.sh \
  -f ./freeciv/freeciv \
  -i ./freeciv/freeciv/install \
  -o ./freeciv-web/src/main/webapp \
  -d ./freeciv-web/src/main/webapp
```

**Generated files** (not tracked in git):
- `freeciv-web/src/main/webapp/javascript/packets.js` - Client-to-server packet constants
- `freeciv-web/src/main/webapp/javascript/packhand_gen.js` - Server-to-client packet dispatcher

These files are automatically regenerated during:
- Docker builds (via `install.sh`)
- Maven builds (via `install.sh`)
- Manual execution of the scripts above

**Important**: The generated JavaScript files should NOT be manually edited or committed to git.

