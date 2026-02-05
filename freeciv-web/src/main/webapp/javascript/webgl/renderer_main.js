/**********************************************************************
    Freeciv-web - the web version of Freeciv. http://www.fciv.net/
    Copyright (C) 2009-2017  The Freeciv-web project

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

***********************************************************************/

var QUALITY_MEDIUM = 2; // medium quality.
var QUALITY_HIGH = 3;   // best quality, add features which require high-end graphics hardware here.

var graphics_quality = QUALITY_HIGH;

var terrain_quality = 8; // 8 is slow, 7 has problems with rivers.

var anaglyph_3d_enabled = false;

var stats = null;

/****************************************************************************
  Init the Freeciv-web WebGL renderer
****************************************************************************/
function init_webgl_renderer()
{
  if (!Detector.webgl) {
    swal("3D WebGL not supported by your browser or you don't have a 3D graphics card. ");
    return;
  }

  var stored_graphics_quality_setting = simpleStorage.get("graphics_quality", "");
  if (stored_graphics_quality_setting != null && stored_graphics_quality_setting > 0) {
    graphics_quality = stored_graphics_quality_setting;
  } else if (is_small_screen()) {
    graphics_quality = QUALITY_MEDIUM;
  } else {
    graphics_quality = QUALITY_HIGH; //default value
  }

}


/****************************************************************************
  Preload is complete.
****************************************************************************/
function webgl_preload_complete()
{
  $.unblockUI();

  // Always call network_init() - this is the proper place in the initialization chain
  // The network_init_called guard in clinet.js prevents duplicate WebSocket connections
  network_init();
}

/****************************************************************************
 Init the map renderer
 ****************************************************************************/
function renderer_init() {
  freelog(LOG_DEBUG, '[Renderer] renderer_init() called, client_state: ' + client_state());
  if (!Detector.webgl) {
    swal("3D WebGL not supported by your browser or you don't have a 3D graphics card. ");
    return;
  }

  if (C_S_RUNNING === client_state() || C_S_OVER === client_state()) {
    freelog(LOG_DEBUG, '[Renderer] Starting webgl_start_renderer()');
    webgl_start_renderer();
    init_webgl_mapview();
    init_webgl_mapctrl();
    init_game_unit_panel();
    // Skip chatbox init in embed mode - mCustomScrollbar plugin fails on hidden elements
    if (typeof is_embed_mode !== 'function' || !is_embed_mode()) {
      init_chatbox();
    }
   keyboard_input=true;
    $.unblockUI();
    freelog(LOG_DEBUG, '[Renderer] Scheduling mapcanvas fadeIn');
    setTimeout(function() {
      freelog(LOG_DEBUG, '[Renderer] Executing mapcanvas fadeIn');
      $('#mapcanvas').fadeIn(2500);
      // Notify parent iframe that renderer is ready and map is becoming visible
      if (typeof notify_parent_iframe === 'function') {
        notify_parent_iframe('renderer_ready', {
          renderer_type: 'webgl',
          map_visible: true
        });
      }

      // Fire terrain_ready AFTER renderer_ready, when terrain data is populated.
      // This ensures both conditions are met: renderer initialized AND terrain in texture.
      // Solves race condition where iframe shows sky-only before terrain renders.
      if (typeof terrain_data_populated !== 'undefined' && terrain_data_populated
          && typeof terrain_ready_notified !== 'undefined' && !terrain_ready_notified
          && typeof notify_parent_iframe === 'function'
          && typeof map !== 'undefined' && map
          && typeof map.xsize === 'number' && typeof map.ysize === 'number') {
        terrain_ready_notified = true;
        notify_parent_iframe('terrain_ready', {
          map_xsize: map.xsize,
          map_ysize: map.ysize,
          total_tiles: map.xsize * map.ysize
        });
        freelog(LOG_DEBUG, '[IframeNotify] terrain_ready fired from renderer_init, tiles: ' + (map.xsize * map.ysize));
      } else if (typeof terrain_data_populated !== 'undefined' && !terrain_data_populated) {
        freelog(LOG_DEBUG, '[Renderer] terrain_data_populated=false, terrain_ready deferred');
      }
    }, 300);
    freelog(LOG_DEBUG, '[Renderer] renderer_init() completed successfully');
  }
}
