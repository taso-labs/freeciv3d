<%@ page import="java.util.Properties" %>
<%@ page import="java.io.IOException" %>
<%@ page import="static org.apache.commons.lang3.StringUtils.stripToNull" %>
<%@ page import="static org.apache.commons.lang3.StringUtils.stripToEmpty" %>
<%@ page import="static java.lang.Boolean.parseBoolean" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%
// Extract spectator parameters
String gameId = request.getParameter("game_id");
String gamePort = request.getParameter("port");
String spectatorMode = request.getParameter("mode");

// Default values
if (gameId == null) gameId = "";
if (gamePort == null) gamePort = "6000";
if (spectatorMode == null) spectatorMode = "full";

// Detect LLM games - multiple detection criteria
boolean isLlmGame = false;

// Check if explicitly LLM game (game_id starts with "llm_" or "game_")
if (gameId != null && (gameId.startsWith("llm_") || gameId.startsWith("game_"))) {
    isLlmGame = true;
}
// Check if game_id is "default" (common for LLM gateway games)
else if ("default".equals(gameId)) {
    isLlmGame = true;
}

// SPECTATOR FIX: DO NOT override port for LLM games!
// The port parameter from URL (6001, 6002, 6003, etc.) is the correct civserver port.
// Previously, this code forced port=8003 (LLM Gateway API port), which was wrong.
// Now we trust the port from the URL, which comes from the LLM Gateway's spectator URL generation.

// Configuration loading
String gaTrackingId = null;
String googleSigninClientKey = null;
String captchaKey = null;
boolean fcwDebug = false;
boolean webgpu = false;
boolean app = false;

try {
  Properties prop = new Properties();
  prop.load(getServletContext().getResourceAsStream("/WEB-INF/config.properties"));
  gaTrackingId = stripToNull(prop.getProperty("ga-tracking-id"));
  googleSigninClientKey = stripToEmpty(prop.getProperty("google-signin-client-key"));
  captchaKey = stripToEmpty(prop.getProperty("captcha_public"));

  String debugParam = request.getParameter("debug");
  fcwDebug = (debugParam != null && (debugParam.isEmpty() || parseBoolean(debugParam)));

  String webgpuParam = request.getParameter("webgpu");
  webgpu = (webgpuParam != null && (!webgpuParam.isEmpty() || parseBoolean(webgpuParam)));

  String appParam = request.getParameter("app");
  app = (appParam != null && (appParam.isEmpty() || parseBoolean(appParam)));

} catch (IOException e) {
  e.printStackTrace();
}
%>
<!DOCTYPE html>
<html>
<head>
<title>FreeCiv3D Spectator - Game <%= gameId %></title>

<link href="${pageContext.request.contextPath}/static/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="${pageContext.request.contextPath}/css/fontawesome.min.css">
<link rel="stylesheet" href="${pageContext.request.contextPath}/css/solid.min.css">
<link rel="stylesheet" type="text/css" href="${pageContext.request.contextPath}/css/webclient.min.css?ts=${initParam.buildTimeStamp}" />
<meta name="description" content="FreeCiv3D Spectator - Watch LLM agents play FreeCiv">

<script type="text/javascript">
// CRITICAL: Set spectator flags BEFORE loading any game client scripts
// This prevents civclient_init() from running (see civclient.js:63-66)
window.isSpectator = true;
window.observing = true;

// Spectator configuration
var ts="${initParam.buildTimeStamp}";
var fcwDebug = true;  // SPECTATOR FIX: Force debug mode to see packet logs
var webgpu = <%= webgpu %>;
var spectatorGameId = "<%= gameId %>";
var spectatorGamePort = <%= gamePort %>;
var spectatorMode = "<%= spectatorMode %>";
var isSpectator = true;  // Keep for backwards compatibility
var observing = true;    // Keep for backwards compatibility
var isLlmGame = <%= isLlmGame %>;
</script>

<script type="text/javascript" src="${pageContext.request.contextPath}/javascript/libs/jquery.min.js?ts=${initParam.buildTimeStamp}"></script>
<script src="https://apis.google.com/js/platform.js"></script>
<script type="text/javascript" src="${pageContext.request.contextPath}/javascript/libs/stacktrace.min.js"></script>
<script async src="https://ga.jspm.io/npm:es-module-shims@1.7.1/dist/es-module-shims.js"></script>

<% if (!webgpu) { %>
  <script type="importmap">
        {
                "imports": {
                        "three": "${pageContext.request.contextPath}/javascript/webgl/libs/three.module.min.js?ts=${initParam.buildTimeStamp}"
                }
        }
  </script>
<% } else { %>
  <script type="importmap">
        {
                "imports": {
                        "three": "${pageContext.request.contextPath}/javascript/webgpu/libs/three-webgpu.module.min.js?ts=${initParam.buildTimeStamp}"
                }
        }
  </script>
<% } %>

<script type="module">
  import * as THREE from 'three';
  window.THREE = THREE;

<% if (webgpu) { %>
  import { WebGPURenderer } from '${pageContext.request.contextPath}/javascript/webgpu/libs/webgpu-renderer.module.min.js?ts=${initParam.buildTimeStamp}';
  window.WebGPURenderer = WebGPURenderer;
<% } %>

  import { DRACOLoader } from '${pageContext.request.contextPath}/javascript/webgl/libs/DRACOLoader.js?ts=${initParam.buildTimeStamp}';
  window.DRACOLoader = DRACOLoader;

  import { GLTFLoader } from '${pageContext.request.contextPath}/javascript/webgl/libs/GLTFLoader.js?ts=${initParam.buildTimeStamp}';
  window.GLTFLoader = GLTFLoader;

  import { OrbitControls } from '${pageContext.request.contextPath}/javascript/webgl/libs/OrbitControls.js?ts=${initParam.buildTimeStamp}';
  window.OrbitControls = OrbitControls;

<% if (!webgpu) { %>
  import { AnaglyphEffect } from '${pageContext.request.contextPath}/javascript/webgl/effects/AnaglyphEffect.js?ts=${initParam.buildTimeStamp}';
  window.AnaglyphEffect = AnaglyphEffect;

  import { Water } from '${pageContext.request.contextPath}/javascript/webgl/libs/Water2.js?ts=${initParam.buildTimeStamp}';
  window.Water = Water;
<% } %>
</script>

<style>
/* Spectator-specific styles */
body {
  background: linear-gradient(135deg, #1a1a2e, #16213e);
  color: #ffffff;
}

#spectator_header {
  background: rgba(0,0,0,0.8);
  padding: 10px;
  text-align: center;
  border-bottom: 2px solid #4a90e2;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  height: 50px;
}

#spectator_content {
  margin-top: 50px;
  height: calc(100vh - 50px);
}

/* Hide player-specific UI elements */
#turn_done_button_div,
#civ_tab,
#tech_tab,
#mentat_tab {
  display: none !important;
}

/* Simplify tabs for spectator */
#tabs_menu li a {
  color: #4a90e2;
}

#tabs_menu li a:hover {
  background: rgba(74, 144, 226, 0.2);
}

.spectator-info {
  display: inline-block;
  margin: 0 15px;
  font-size: 14px;
}

.spectator-status {
  color: #4CAF50;
  font-weight: bold;
}
</style>

</head>
<body class="ui-widget">

<div id="spectator_header">
  <div class="spectator-info">
    <i class="fa fa-eye" aria-hidden="true"></i>
    <span class="spectator-status">SPECTATING<% if (isLlmGame) { %> LLM GAME<% } %></span>
  </div>
  <div class="spectator-info">
    Game ID: <strong><%= gameId %></strong>
  </div>
  <div class="spectator-info">
    Port: <strong><%= gamePort %></strong><% if (isLlmGame) { %> <i class="fa fa-robot" aria-hidden="true" style="color: #FFD700;"></i><% } %>
  </div>
  <div class="spectator-info" id="connection_status">
    Status: <span id="connection_indicator">Connecting...</span>
  </div>
</div>

<div id="spectator_content">
  <div id="game_page">
    <div id="tabs">
      <ul id="tabs_menu">
        <div id="freeciv_logo"></div>
        <li id="map_tab"><a href="#tabs-map"><i class="fa fa-globe" aria-hidden="true"></i> Map</a></li>
        <li id="players_tab"><a href="#tabs-nat"><i class="fa fa-flag" aria-hidden="true"></i> Nations</a></li>
        <li id="cities_tab"><a href="#tabs-cities"><i class="fa fa-city" aria-hidden="true"></i> Cities</a></li>
        <li id="opt_tab"><a href="#tabs-opt"><i class="fa fa-cogs" aria-hidden="true"></i> Options</a></li>
        <li id="hel_tab"><a href="#tabs-hel"><i class="fa fa-circle-info" aria-hidden="true"></i> Manual</a></li>

        <div id="game_status_panel_top"></div>
      </ul>

      <div id="tabs-map" tabindex="-1">
        <jsp:include page="canvas.jsp" flush="false"/>
      </div>
      <div id="tabs-nat">
        <jsp:include page="nations.jsp" flush="false"/>
      </div>
      <div id="tabs-cities">
        <jsp:include page="cities.jsp" flush="false"/>
      </div>
      <div id="tabs-hel" class="manual_doc">
      </div>
      <div id="tabs-opt">
        <jsp:include page="options.jsp" flush="false"/>
      </div>
    </div>
  </div>
</div>

<div id="dialog"></div>
<div id="city_name_dialog"></div>

<!-- Load minified FreeCiv client JavaScript -->
<script type="text/javascript" src="${pageContext.request.contextPath}/javascript/webclient.min.js?ts=${initParam.buildTimeStamp}"></script>

<!-- Load spectator-specific client -->
<script type="text/javascript" src="${pageContext.request.contextPath}/javascript/spectator_client.js?ts=${initParam.buildTimeStamp}"></script>

<script type="text/javascript">
$(document).ready(function() {
  console.log("Spectator page ready, initializing...");

  // Initialize UI components first
  $("#tabs").tabs();
  $("#tabs").css("height", "100%");

  // Hide non-essential tabs for spectator mode
  $("#opt_tab").hide();
  $("#hel_tab").hide();

  // Force the Map tab to be active and visible
  $("#tabs").tabs("option", "active", 0);

  // Ensure map tab content is shown and others are hidden
  $("#tabs-map").show();
  $("#tabs-civ").hide();
  $("#tabs-nat").hide();
  $("#tabs-cities").hide();

  // Show map canvas - don't overwrite canvas.jsp content
  $("#mapcanvas").show();

  // Wait for all required FreeCiv components to be ready
  function waitForFreeCivReady() {
    // Note: Removed 'websocket_connect' - spectator uses its own connection function
    // Note: Removed 'init_mapcanvas_2d' - doesn't exist in 3D version, uses WebGL only
    var requiredFunctions = [
      'init_webgl_renderer', 'game_init', 'control_init'
    ];

    var allReady = requiredFunctions.every(function(funcName) {
      return typeof window[funcName] === 'function';
    });

    if (allReady && typeof client !== 'undefined') {
      console.log("All FreeCiv components ready, initializing spectator...");

      // Initialize minimal client state for spectator
      if (!client.conn) {
        client.conn = {
          playing: null,
          observer: true,
          established: false
        };
      }

      // Set global spectator state
      if (typeof observing === 'undefined') window.observing = true;
      if (typeof isSpectator === 'undefined') window.isSpectator = true;

      // Initialize spectator client
      init_spectator_client();
    } else {
      console.log("Waiting for FreeCiv components:", requiredFunctions.filter(function(f) {
        return typeof window[f] !== 'function';
      }));
      setTimeout(waitForFreeCivReady, 500);
    }
  }

  // Start waiting for FreeCiv components
  waitForFreeCivReady();
});
</script>

<!-- WebGL Shader Templates (required for 3D renderer) -->
<script id="terrain_fragment_shh" type="x-shader/x-fragment">
  <jsp:include page="/javascript/webgl/shaders/terrain_fragment_shader.glsl" flush="false"/>
</script>

<script id="terrain_vertex_shh" type="x-shader/x-vertex">
  <jsp:include page="/javascript/webgl/shaders/terrain_vertex_shader.glsl" flush="false"/>
</script>

</body>
</html><\!-- force rebuild -->
