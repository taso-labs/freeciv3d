/**********************************************************************
    Freeciv-web - the web version of Freeciv. http://www.fciv.net/
    Copyright (C) 2009-2016  The Freeciv-web project

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

var maptiletypes;
var maptiles_data;

/****************************************************************************
  Initialize a 1x1 placeholder texture for maptiletypes.
  This ensures maptiletypes is never undefined when init_webgl_mapview() runs,
  preventing shader failures due to undefined uniform values.
  Called early during page initialization, before any packets arrive.
****************************************************************************/
function init_placeholder_tiletype_texture()
{
  if (maptiletypes != null) return;  // Already initialized

  // Create minimal 1x1 texture as placeholder
  var placeholder_data = new Uint8Array(4);  // RGBA for 1 pixel
  maptiletypes = new THREE.DataTexture(placeholder_data, 1, 1);
  maptiletypes.colorSpace = THREE.NoColorSpace;
  maptiletypes.magFilter = THREE.NearestFilter;
  maptiletypes.minFilter = THREE.NearestFilter;
  maptiletypes.needsUpdate = true;
}

/****************************************************************************
  Returns a texture containing each map tile, where the color of each pixel
  indicates which Freeciv tile type the pixel is.
****************************************************************************/
function init_map_tiletype_image()
{
  maptiles_data = new Uint8Array( 4 * map.xsize * map.ysize );

  maptiletypes = new THREE.DataTexture(maptiles_data, map.xsize, map.ysize);
  maptiletypes.flipY = true;
  // Prevent color space conversion - texture contains raw integer data, not colors
  maptiletypes.colorSpace = THREE.NoColorSpace;
  maptiletypes.magFilter = THREE.NearestFilter;
  maptiletypes.minFilter = THREE.NearestFilter;
  maptiletypes.generateMipmaps = false;

  for (let x = 0; x < map.xsize; x++) {
    for (let y = 0; y < map.ysize; y++) {
      let index = (y * map.xsize + x) * 4;
      maptiles_data[index] = 0;
      maptiles_data[index + 1] = 0;
      maptiles_data[index + 2] = 0;
      maptiles_data[index + 3] = 0;
    }
  }

  // CRITICAL: Update shader uniform reference after creating new texture.
  // This fixes a race condition where init_webgl_mapview() captures an old/empty
  // maptiletypes reference before this function creates the real texture.
  // Without this, the first observer shows black terrain while later observers work.
  update_shader_tiletype_uniform();
}

/****************************************************************************
  Update the shader uniform to reference the current maptiletypes texture.
  Must be called after init_map_tiletype_image() creates a new texture object
  to ensure the shader uses the correct texture reference.
****************************************************************************/
function update_shader_tiletype_uniform()
{
  if (typeof freeciv_uniforms !== 'undefined' && freeciv_uniforms !== null
      && freeciv_uniforms.maptiles && maptiletypes) {
    freeciv_uniforms.maptiles.value = maptiletypes;
  }
}

/****************************************************************************
  ...
****************************************************************************/
function update_tiletypes_tile(ptile)
{
  if (ptile == null) return;  // Safety check

  let terrain = tile_terrain(ptile);
  if (terrain == null) return;  // Skip tiles without terrain data yet

  let x = ptile.x;
  let y = ptile.y;
  let index = (y * map.xsize + x) * 4;

  maptiles_data[index] = terrain['id'] * 10;
  maptiles_data[index + 1] = tile_has_extra(ptile, EXTRA_RIVER) ? 10 : 0;
  if (tile_has_extra(ptile, EXTRA_FARMLAND)) {
    maptiles_data[index + 2] = 2;
  } else if (tile_has_extra(ptile, EXTRA_IRRIGATION)) {
    maptiles_data[index + 2] = 1;
  } else {
    maptiles_data[index + 2] = 0;
  }

  maptiletypes.needsUpdate = true;

}
