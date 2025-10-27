/**********************************************************************
    Freeciv-web - the web version of Freeciv. http://www.fciv.net/
    Copyright (C) 2009-2015  The Freeciv-web project

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


var LOG_FATAL = 0;
var LOG_ERROR = 1;		/* non-fatal errors */
var LOG_NORMAL = 2;
var LOG_VERBOSE = 3;		/* not shown by default */
var LOG_DEBUG = 4;		/* suppressed unless DEBUG defined;
				   may be enabled on file/line basis */



/**
 * Centralized logging function with level-based filtering
 *
 * @param {number} level - Log level (LOG_FATAL, LOG_ERROR, LOG_NORMAL, LOG_VERBOSE, LOG_DEBUG)
 * @param {string} message - Message to log
 */
function freelog(level, message)
{
  // In production, suppress verbose and debug logs unless debug_active is enabled
  if (typeof debug_active !== 'undefined' && !debug_active && level >= LOG_VERBOSE) {
    return;
  }

  // Use appropriate console method based on log level
  switch(level) {
    case LOG_FATAL:
    case LOG_ERROR:
      console.error(message);
      break;
    case LOG_NORMAL:
      console.info(message);
      break;
    case LOG_VERBOSE:
    case LOG_DEBUG:
      console.log(message);
      break;
    default:
      console.log(message);
  }
}

