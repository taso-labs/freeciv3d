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

var camera;

var camera_dx = 50;
var camera_dy = 410;
var camera_dz = 242;
var camera_current_x = 0;
var camera_current_y = 0;
var camera_current_z = 0;
var slide_init = false;

/****************************************************************************
  Camera presets for observer views.
  Each preset defines offsets that create different viewing angles:
  - dx: lateral offset (X axis)
  - dy: height offset (Y axis) - higher = more top-down view
  - dz: depth offset (Z axis) - higher = more distant/angled view

  Viewing angle from horizontal ≈ atan(dy/dz)
****************************************************************************/
var camera_presets = {
  'default':    { dx: 50,  dy: 410, dz: 242 },  // ~60° - standard view
  'strategic':  { dx: 50,  dy: 800, dz: 100 },  // ~83° - near top-down overview
  'cinematic':  { dx: 25,  dy: 150, dz: 200 },  // ~37° - close dramatic angle (2x zoom)
  'isometric':  { dx: 50,  dy: 500, dz: 500 },  // 45° - classic strategy game
  'worldmap':   { dx: 50,  dy: 1200, dz: 80 },  // ~86° - near top-down for full map recording
};

/****************************************************************************
  Apply a camera preset by name.
  @param {string} preset_name - One of: default, strategic, cinematic, isometric, worldmap
****************************************************************************/
function set_camera_preset(preset_name)
{
  var preset = camera_presets[preset_name] || camera_presets['default'];

  // Validate preset has required numeric properties (defensive coding)
  if (typeof preset.dx !== 'number' || typeof preset.dy !== 'number' || typeof preset.dz !== 'number') {
    console.error('[Camera] Invalid preset:', preset_name, '- missing or invalid dx/dy/dz, using default');
    preset = camera_presets['default'];
  }

  camera_dx = preset.dx;
  camera_dy = preset.dy;
  camera_dz = preset.dz;

  // Re-apply camera position with new offsets if camera has a current position
  if (camera_current_x !== 0 || camera_current_z !== 0) {
    camera_look_at(camera_current_x, camera_current_y, camera_current_z);
  }
}

/****************************************************************************
  Initialize camera preset from URL parameter.
  Parses ?camera=preset_name and applies the preset if valid.
****************************************************************************/
function init_camera_from_url_params()
{
  if (typeof $ !== 'undefined' && $.getUrlVar) {
    var camera_param = $.getUrlVar('camera');
    if (camera_param) {
      set_camera_preset(camera_param);
    }
  }
}


/****************************************************************************
  Point the camera to look at point x, y, z in Three.js coordinates.
****************************************************************************/
function camera_look_at(x, y, z)
{
  camera_current_x = x;
  camera_current_y = y;
  camera_current_z = z;

  if (camera != null) {
    camera.position.set( x + camera_dx, y + camera_dy, z + camera_dz);
    camera.lookAt( new THREE.Vector3(x, 0, z));

    spotlight.position.set( x + 500, 900, z + 500);
    spotlight.target.position.set(x - 200, 0, z - 200);
    spotlight.shadow.camera.position.copy(spotlight.position);
    spotlight.shadow.camera.lookAt(new THREE.Vector3(x - 200, 0, z + 500));

    if (sun_mesh != null) {
      sun_mesh.position.set( x + 500, 900, z + 500);
    }
  }

  if (controls != null) {
    controls.target = new THREE.Vector3(x + 50, 50, z + 50);
  }

}

/**************************************************************************
  Centers the mapview around the given tile..
**************************************************************************/
function center_tile_mapcanvas_3d(ptile)
{
  if (ptile != null) {
    if (slide_init) {
      enable_mapview_slide_3d(ptile);
    } else {
      var pos = map_to_scene_coords(ptile['x'], ptile['y']);
      camera_look_at(pos['x'] - 50, 0, pos['y'] - 50);       // -50 to get the center tile more in the center of the screen.
      slide_init = true;
    }

  }

}

/**************************************************************************
...
**************************************************************************/
function center_tile_city(city)
{
  var ptile = city_tile(city);
  if (ptile != null) {
    var pos = map_to_scene_coords(ptile['x'], ptile['y']);
    camera_look_at(pos['x'] , 0, pos['y'] );
  }

}

/**************************************************************************
  Enabled silding of the mapview to the given tile.
**************************************************************************/
function enable_mapview_slide_3d(ptile)
{
  var pos_dest = map_to_scene_coords(ptile['x'], ptile['y']);

  camera_dx = camera.position.x - controls.target.x + 50;
  camera_dy = camera.position.y - controls.target.y + 50;
  camera_dz = camera.position.z - controls.target.z + 50;

  mapview_slide['dx'] = camera_current_x - pos_dest['x'] + 50;
  mapview_slide['dy'] = camera_current_z - pos_dest['y'] + 50;
  mapview_slide['i'] = mapview_slide['max'];
  mapview_slide['prev'] = mapview_slide['i'];
  mapview_slide['start'] = new Date().getTime();
  mapview_slide['active'] = true;

}

/**************************************************************************
  Updates mapview slide, called once per frame.
**************************************************************************/
function update_map_slide_3d()
{
  var elapsed = 1 + new Date().getTime() - mapview_slide['start'];
  mapview_slide['i'] = Math.floor(mapview_slide['max']
                        * (mapview_slide['slide_time']
                        - elapsed) / mapview_slide['slide_time']);

  if (mapview_slide['i'] <= 0) {
    mapview_slide['active'] = false;
    return;
  }

  var dx = Math.floor(mapview_slide['dx'] * (mapview_slide['i'] - mapview_slide['prev']) / mapview_slide['max']);
  var dy = Math.floor(mapview_slide['dy'] * (mapview_slide['i'] - mapview_slide['prev']) / mapview_slide['max']);

  camera_look_at(camera_current_x + dx, 0, camera_current_z + dy);
  mapview_slide['prev'] = mapview_slide['i'];

}