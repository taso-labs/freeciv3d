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


var clinet_last_send = 0;
var debug_client_speed_list = [];

var freeciv_version = "+Freeciv.Web.Devel-3.3";

var ws = null;
var civserverport = null;

var ping_last = new Date().getTime();
var pingtime_check = 240000;
var ping_timer = null;
var network_init_called = false;  // Guard against double initialization

/****************************************************************************
  Initialized the Network communication, by requesting a valid server port.
****************************************************************************/
function network_init()
{
  // Prevent double initialization (both civclient.js and renderer_main.js call this)
  if (network_init_called) {
    freelog(LOG_DEBUG, "network_init: Already called, skipping duplicate initialization");
    return;
  }
  network_init_called = true;

  var civclient_request_url = "/civclientlauncher";
  if ($.getUrlVar('action') != null) civclient_request_url += "?action=" + $.getUrlVar('action');
  if ($.getUrlVar('action') == null && $.getUrlVar('civserverport') != null) civclient_request_url += "?";
  if ($.getUrlVar('civserverport') != null) civclient_request_url += "&civserverport=" + $.getUrlVar('civserverport');

  freelog(LOG_DEBUG, "network_init: Making request to " + civclient_request_url);

  $.ajax({
   type: 'POST',
   url: civclient_request_url,
   success: function(data, textStatus, request){
       civserverport = request.getResponseHeader('port');
       var connect_result = request.getResponseHeader('result');
       freelog(LOG_DEBUG, "civclientlauncher response - port: " + civserverport + ", result: " + connect_result);

       if (civserverport != null && connect_result == "success") {
         websocket_init();
         load_game_check();

       } else {
         freelog(LOG_ERROR, "civclientlauncher failed - port: " + civserverport + ", result: " + connect_result);
         show_dialog_message("Network error", "Invalid server port. Error: " + connect_result);
       }
   },
   error: function (request, textStatus, errorThrown) {
	show_dialog_message("Network error", "Unable to communicate with civclientlauncher servlet . Error: "
		+ textStatus + " " + errorThrown + " " + request.getResponseHeader('result'));
   }
  });
}

/****************************************************************************
  Initialized the WebSocket connection.
****************************************************************************/
function websocket_init()
{
  $.blockUI({ message: "<h2>Please wait while connecting to the server.</h2>" });

  // Debug logging
  freelog(LOG_DEBUG, "websocket_init: civserverport = " + civserverport);

  if (!civserverport) {
    freelog(LOG_ERROR, "ERROR: civserverport is null or undefined!");
    show_dialog_message("Network error", "Server port was not properly assigned. Please try again.");
    return;
  }

  // Calculate proxy port correctly: 6000 -> 7000, 6001 -> 7001, etc.
  var proxy_port = parseFloat(civserverport) - 6000 + 7000;
  var ws_protocol = ('https:' == window.location.protocol) ? "wss://" : "ws://";
  var port = window.location.port ? (':' + window.location.port) : '';
  // Use internal proxy port for nginx routing (7000+)
  var ws_url = ws_protocol + window.location.hostname + port + "/civsocket/" + proxy_port;

  freelog(LOG_DEBUG, "WebSocket URL: " + ws_url);
  freelog(LOG_DEBUG, "Attempting to connect to WebSocket...");

  ws = new WebSocket(ws_url);

  ws.onopen = function() {
    freelog(LOG_DEBUG, "WebSocket opened successfully!");
    check_websocket_ready();
  };

  ws.onerror = function(error) {
    freelog(LOG_ERROR, "WebSocket error: " + error);
  };

  ws.onmessage = function (event) {
     if (typeof client_handle_packet !== 'undefined') {
       var parsed_data = JSON.parse(event.data);
       client_handle_packet(parsed_data);
     } else {
       freelog(LOG_ERROR, "Error, freeciv-web not compiled correctly. Please run sync.sh in freeciv-proxy correctly.");
     }
  };

  ws.onclose = function (event) {
   freelog(LOG_ERROR, "WebSocket closed - code: " + event.code + ", reason: " + event.reason + ", wasClean: " + event.wasClean);
   swal("Network Error", "Connection to server is closed. Please reload the page to restart. Sorry!", "error");
   message_log.update({
     event: E_LOG_ERROR,
     message: "Error: connection to server is closed. Please reload the page to restart. Sorry!"
   });
   $("#turn_done_button").button( "option", "disabled", true);
   $("#save_button").button( "option", "disabled", true);


   /* The player can't save the game after the connection is down. */
   $(window).unbind('beforeunload');

   /* Don't ping a dead connection. */
   clearInterval(ping_timer);
  };

  ws.onerror = function (evt) {
   show_dialog_message("Network error", "A problem occured with the "
                       + document.location.protocol + " WebSocket connection to the server: " + ws.url);
   freelog(LOG_ERROR, "WebSocket error: Unable to communicate with server using " + document.location.protocol + " WebSockets. Error: " + evt);
  };
}

/****************************************************************************
  When the WebSocket connection is open and ready to communicate, then
  send the first login message to the server.
****************************************************************************/
function check_websocket_ready()
{
  if (ws != null && ws.readyState === 1) {

    var login_message = {"pid":4, "username" : username,
    "capability": freeciv_version, "version_label": "-dev",
    "major_version" : 3, "minor_version" : 1, "patch_version" : 90,
    "port": civserverport};
    ws.send(JSON.stringify(login_message));

    /* The connection is now up. Verify that it remains alive. */
    ping_timer = setInterval(ping_check, pingtime_check);

    $.unblockUI();
  } else {
    setTimeout(check_websocket_ready, 300);
  }
}

/****************************************************************************
  Stops network sync.
****************************************************************************/
function network_stop()
{
  if (ws != null) ws.close();
  ws = null;
}

/****************************************************************************
  Sends a request to the server, with a JSON packet.
****************************************************************************/
function send_request(packet_payload)
{
  if (ws != null) {
    ws.send(packet_payload);
  }

  if (debug_active) {
    clinet_last_send = new Date().getTime();
  }
}


/****************************************************************************
...
****************************************************************************/
function clinet_debug_collect()
{
  var time_elapsed = new Date().getTime() - clinet_last_send;
  debug_client_speed_list.push(time_elapsed);
  clinet_last_send = new Date().getTime();
}

/****************************************************************************
  Detect server disconnections, by checking the time since the last
  ping packet from the server.
****************************************************************************/
function ping_check()
{
  var time_since_last_ping = new Date().getTime() - ping_last;
  if (time_since_last_ping > pingtime_check) {
    freelog(LOG_ERROR, "Error: Missing PING message from server, indicates server connection problem.");
  }
}

/****************************************************************************
  send the chat message to the server after a delay.
****************************************************************************/
function send_message_delayed(message, delay)
{
  setTimeout("send_message('" + message + "');", delay);
}

/****************************************************************************
  sends a chat message to the server.
****************************************************************************/
function send_message(message)
{

  var packet = {"pid" : packet_chat_msg_req, 
                "message" : message};
  send_request(JSON.stringify(packet));
}
