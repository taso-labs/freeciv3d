<%--
  Mentat (Web-LLM) AI Chat Component

  DISABLED in embed/observer mode to prevent:
  1. Parcel HMR code trying to connect to wss://freeciv.clashai.live/ in production
  2. Unnecessary WebSocket connections that may interfere with game WebSocket
  3. Console noise from failed HMR connections
--%>
<%
  String embedParam = request.getParameter("embed");
  String actionParam = request.getParameter("action");
  boolean isEmbedMode = "1".equals(embedParam) || "true".equals(embedParam);
  boolean isObserveMode = "observe".equals(actionParam);
  boolean skipWebLLM = isEmbedMode || isObserveMode;
%>

<div id="mentat_div" style="padding: 5px; padding-left: 20px;">
<h2>Mentat for Freeciv</h2>

<% if (skipWebLLM) { %>
  <p><i>Mentat AI Chat is disabled in observer/embed mode.</i></p>
<% } else { %>

<link href="/web-llm/src/llm_chat.css?<%= Math.random() %>" rel="stylesheet" type="text/css"/>

<div class="chatui">
   <div class="chatui-select-wrapper">
    <select id="chatui-select">
    </select>
   </div>
  <div class="chatui-chat" id="chatui-chat" height="100">
  </div>

  <div class="chatui-inputarea">
    <input id="chatui-input" type="text" class="chatui-input"  placeholder="Enter your message...">
    <button id="chatui-send-btn" class="chatui-send-btn"></button>
    <button id="chatui-reset-btn" class="chatui-reset-btn"></button>
  </div>
</div>

<div class="chatui-extra-control">
  <label id="chatui-info-label"></label>
</div>

  <b><i>
    Large Language Model AI Chat for Freeciv 3D. Requires WebGPU support in Google Chrome and Nvidia GPU hardware.<br>
    Try the TinyLlama (fast and not so smart) or Mistral (slow and smart) models.
    Download size: 2.2 GB.
   </i></b>

<!--- Place script after ui to make sure ui loads first -->
<script>
  // Add error handler for web-llm to prevent it from crashing the game
  window.addEventListener('error', function(event) {
    if (event.filename && (event.filename.includes('llm_chat') || event.filename.includes('web-llm'))) {
      console.warn('Web-LLM error (suppressed to prevent game crash):', event.message);
      event.preventDefault();
      return true;
    }
  });
</script>
<script src="/web-llm/dist/llm_chat.5e8e8dcb.js?<%= Math.random() %>" defer="" onerror="console.warn('Web-LLM failed to load (non-critical)')"></script>

<% } %>
</div>
