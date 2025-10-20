/** *****************************************************************************
 * Freeciv-web - the web version of Freeciv. http://www.fciv.net/
 * Copyright (C) 2009-2017 The Freeciv-web project
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 * *****************************************************************************
 */
package org.freeciv.servlet;

import java.io.IOException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.naming.Context;
import javax.naming.InitialContext;

import jakarta.servlet.ServletException;
import jakarta.servlet.annotation.MultipartConfig;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import javax.sql.DataSource;

import org.freeciv.util.Constants;
import org.json.JSONObject;

import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Collection;

import javax.naming.NamingException;

import org.apache.commons.io.IOUtils;
import java.util.logging.Logger;
import java.util.logging.Level;

import jakarta.servlet.http.Part;

/**
 * Displays the multiplayer games
 *
 * URL: /meta/metaserver
 */
@MultipartConfig
public class Metaserver extends HttpServlet {

    private static final long serialVersionUID = 1L;

    private static final Logger LOGGER = Logger.getLogger(Metaserver.class.getName());

    private static final String CONTENT_TYPE = "application/json";

    private static final String INTERNAL_SERVER_ERROR = new JSONObject() //
            .put("statusCode", HttpServletResponse.SC_INTERNAL_SERVER_ERROR) //
            .put("error", "Internal server error.") //
            .toString();

    private static final String FORBIDDEN = new JSONObject() //
            .put("statusCode", HttpServletResponse.SC_FORBIDDEN) //
            .put("error", "Forbidden.") //
            .toString();

    private static final String BAD_REQUEST = new JSONObject() //
            .put("statusCode", HttpServletResponse.SC_BAD_REQUEST) //
            .put("error", "Bad Request.") //
            .toString();

    private static final List<String> SERVER_COLUMNS = new ArrayList<>();

    static {
        SERVER_COLUMNS.add("version");
        SERVER_COLUMNS.add("patches");
        SERVER_COLUMNS.add("capability");
        SERVER_COLUMNS.add("state");
        SERVER_COLUMNS.add("ruleset");
        SERVER_COLUMNS.add("message");
        SERVER_COLUMNS.add("type");
        SERVER_COLUMNS.add("available");
        SERVER_COLUMNS.add("humans");
        SERVER_COLUMNS.add("serverid");
        SERVER_COLUMNS.add("host");
        SERVER_COLUMNS.add("port");
    }

    @Override
    public void doPost(HttpServletRequest request, HttpServletResponse response) throws ServletException, IOException {

        String localAddr = request.getLocalAddr();
        String remoteAddr = request.getRemoteAddr();

        // In containerized / proxied deployments nginx will forward requests
        // to the webapp and the servlet will see nginx's IP as the remote
        // address. Historically the servlet required request.getLocalAddr()
        // == request.getRemoteAddr() to accept updates, which blocks proxied
        // requests. Allow requests when they come from loopback or from the
        // internal Docker network forwarded by nginx (via X-Real-IP / X-Forwarded-For).
        String xRealIp = request.getHeader("X-Real-IP");
        String xForwardedFor = request.getHeader("X-Forwarded-For");
        String clientIp = remoteAddr;
        if (xRealIp != null && !xRealIp.isEmpty()) {
            clientIp = xRealIp.split(",")[0].trim();
        } else if (xForwardedFor != null && !xForwardedFor.isEmpty()) {
            clientIp = xForwardedFor.split(",")[0].trim();
        }

        boolean allowed = false;
        if (localAddr != null && localAddr.equals(remoteAddr)) {
            allowed = true; // direct localhost call
        } else if ("127.0.0.1".equals(clientIp) || "::1".equals(clientIp)) {
            allowed = true; // proxied from loopback
        } else if (clientIp != null && clientIp.startsWith("172.")) {
            // permissive check for Docker default networks (172.16.0.0/12)
            allowed = true;
        }

        if (!allowed) {
            response.setContentType(CONTENT_TYPE);
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.getOutputStream().print(FORBIDDEN);
            return;
        }

        // Wrap the request with a buffering wrapper that caches the
        // incoming request body so the container can parse multipart
        // fields and we can still read the raw body for logging.
        BufferedRequestWrapper buffered = new BufferedRequestWrapper(request);
        request = buffered;
        String rawRequestBody;
        try {
            String rb = buffered.getRequestBodyString();
            if (rb == null) {
                rawRequestBody = "<empty-body>";
            } else {
                rawRequestBody = rb.length() > 1000 ? rb.substring(0, 1000) + "..." : rb;
            }
        } catch (Exception e) {
            rawRequestBody = "<error-reading-body>";
        }

        String serverIsStopping = request.getParameter("bye");
        String sHost = request.getParameter("host");
        String sPort = request.getParameter("port");
        String dropPlayers = request.getParameter("dropplrs");

        List<String> sPlUser = request.getParameterValues("plu[]") == null ? null
                : Arrays.asList(request.getParameterValues("plu[]"));
        List<String> sPlName = request.getParameterValues("pll[]") == null ? null
                : Arrays.asList(request.getParameterValues("pll[]"));
        List<String> sPlNation = request.getParameterValues("pln[]") == null ? null
                : Arrays.asList(request.getParameterValues("pln[]"));
        List<String> sPlFlag = request.getParameterValues("plf[]") == null ? null
                : Arrays.asList(request.getParameterValues("plf[]"));
        List<String> sPlType = request.getParameterValues("plt[]") == null ? null
                : Arrays.asList(request.getParameterValues("plt[]"));
        List<String> sPlHost = request.getParameterValues("plh[]") == null ? null
                : Arrays.asList(request.getParameterValues("plh[]"));
        List<String> variableNames = request.getParameterValues("vn[]") == null ? null
                : Arrays.asList(request.getParameterValues("vn[]"));
        List<String> variableValues = request.getParameterValues("vv[]") == null ? null
                : Arrays.asList(request.getParameterValues("vv[]"));

        // If this is a multipart/form-data POST (browser forms with files or
        // multipart encoding) the servlet container may not populate
        // getParameter()/getParameterValues() for form fields. Parse parts
        // and use their contents as a fallback for parameters and arrays.
        Map<String, List<String>> multipartParams = new HashMap<>();
        String reqContentType = request.getContentType();
        if (reqContentType != null && reqContentType.toLowerCase().startsWith("multipart/")) {
            try {
                Collection<Part> parts = request.getParts();
                for (Part p : parts) {
                    String name = p.getName();
                    if (p.getSubmittedFileName() == null) {
                        // Use IOUtils to read the part input stream into a String.
                        try (InputStreamReader isr = new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8)) {
                            String v = IOUtils.toString(isr);
                            multipartParams.computeIfAbsent(name, k -> new ArrayList<>()).add(v);
                            String preview = v.length() > 200 ? v.substring(0, 200) + "..." : v;
                            if (LOGGER.isLoggable(Level.FINE)) {
                                LOGGER.fine("MULTIPART: part name='" + name + "' size=" + v.length() + " preview='" + preview + "'");
                            }
                        }
                    } else {
                        if (LOGGER.isLoggable(Level.FINE)) {
                            LOGGER.fine("MULTIPART: part name='" + name + "' is a file (" + p.getSubmittedFileName() + ") size=" + p.getSize());
                        }
                    }
                }
            } catch (ServletException | IOException e) {
                LOGGER.log(Level.WARNING, "MULTIPART: error parsing parts", e);
            }

            // If container did not expose parts (some environments) try a
            // fallback: read the raw request body and parse the multipart
            // sections manually to extract simple text fields.
            if (multipartParams.isEmpty()) {
                try {
                    String raw = readRequestBodyFull(request);
                    if (raw != null && !raw.isEmpty()) {
                        // extract boundary from content-type
                        String boundary = null;
                        int bi = reqContentType.indexOf("boundary=");
                        if (bi >= 0) {
                            boundary = reqContentType.substring(bi + "boundary=".length()).trim();
                            if (boundary.startsWith("\"") && boundary.endsWith("\"")) {
                                boundary = boundary.substring(1, boundary.length() - 1);
                            }
                        }
                        String sep = (boundary == null) ? null : "--" + boundary;
                        String[] partsRaw = (sep == null) ? new String[0] : raw.split(java.util.regex.Pattern.quote(sep));
                        for (String partRaw : partsRaw) {
                            if (partRaw == null) {
                                continue;
                            }
                            String pr = partRaw.trim();
                            if (pr.length() == 0 || pr.equals("--")) {
                                continue;
                            }
                            int hi = pr.indexOf("\r\n\r\n");
                            if (hi < 0) {
                                hi = pr.indexOf("\n\n");
                            }
                            if (hi < 0) {
                                continue;
                            }
                            String headers = pr.substring(0, hi);
                            String body = pr.substring(hi + (pr.charAt(hi) == '\r' ? 4 : 2)).trim();
                            // find name="..."
                            int ni = headers.indexOf("name=");
                            if (ni >= 0) {
                                int q1 = headers.indexOf('"', ni);
                                int q2 = (q1 >= 0) ? headers.indexOf('"', q1 + 1) : -1;
                                String name = null;
                                if (q1 >= 0 && q2 > q1) {
                                    name = headers.substring(q1 + 1, q2);
                                }
                                if (name != null) {
                                    multipartParams.computeIfAbsent(name, k -> new ArrayList<>()).add(body);
                                    String preview = body.length() > 200 ? body.substring(0, 200) + "..." : body;
                                    if (LOGGER.isLoggable(Level.FINE)) {
                                        LOGGER.fine("MULTIPART-FALLBACK: part name='" + name + "' size=" + body.length() + " preview='" + preview + "'");
                                    }
                                }
                            }
                        }
                    }
                } catch (Exception e) {
                    LOGGER.log(Level.FINE, "MULTIPART-FALLBACK: error parsing raw body", e);
                    // ignore and continue
                }
            }

            // Override scalar parameters if they were not supplied via
            // request.getParameter (common when container doesn't populate them)
            if ((sHost == null || sHost.isEmpty()) && multipartParams.containsKey("host")) {
                sHost = multipartParams.get("host").get(0);
            }
            if ((sPort == null || sPort.isEmpty()) && multipartParams.containsKey("port")) {
                sPort = multipartParams.get("port").get(0);
            }
            if ((dropPlayers == null || dropPlayers.isEmpty()) && multipartParams.containsKey("dropplrs")) {
                dropPlayers = multipartParams.get("dropplrs").get(0);
            }

            // Arrays: use multipart values when original lists are null
            if (sPlUser == null && multipartParams.containsKey("plu[]")) {
                sPlUser = multipartParams.get("plu[]");
            }
            if (sPlName == null && multipartParams.containsKey("pll[]")) {
                sPlName = multipartParams.get("pll[]");
            }
            if (sPlNation == null && multipartParams.containsKey("pln[]")) {
                sPlNation = multipartParams.get("pln[]");
            }
            if (sPlFlag == null && multipartParams.containsKey("plf[]")) {
                sPlFlag = multipartParams.get("plf[]");
            }
            if (sPlType == null && multipartParams.containsKey("plt[]")) {
                sPlType = multipartParams.get("plt[]");
            }
            if (sPlHost == null && multipartParams.containsKey("plh[]")) {
                sPlHost = multipartParams.get("plh[]");
            }
            if (variableNames == null && multipartParams.containsKey("vn[]")) {
                variableNames = multipartParams.get("vn[]");
            }
            if (variableValues == null && multipartParams.containsKey("vv[]")) {
                variableValues = multipartParams.get("vv[]");
            }
        }

        Map<String, String> serverVariables = new HashMap<>();
        for (String serverParameter : SERVER_COLUMNS) {
            String parameter = request.getParameter(serverParameter);
            // If container didn't populate parameters for multipart/form-data,
            // fall back to values parsed earlier from parts (multipartParams).
            if ((parameter == null || parameter.isEmpty()) && multipartParams.containsKey(serverParameter)) {
                List<String> vals = multipartParams.get(serverParameter);
                if (vals != null && !vals.isEmpty()) {
                    parameter = vals.get(0);
                }
            }
            if (parameter != null) {
                serverVariables.put(serverParameter, parameter);
            }
        }

        // Data validation
        String query;
        int port;
        try {
            if (sPort == null) {
                throw new IllegalArgumentException("Port must be supplied.");
            }
            port = Integer.parseInt(sPort);
            if ((port < 1024) || (port > 65535)) {
                throw new IllegalArgumentException("Invalid port supplied. Expected a number between 1024 and 65535");
            }
            if (sHost == null) {
                throw new IllegalArgumentException("Host parameter is required to perform this request.");
            }
        } catch (IllegalArgumentException e) {
            // Log parameters and raw body for debugging malformed requests
            try {
                String pd = (rawRequestBody != null && !rawRequestBody.isEmpty()) ? rawRequestBody : null;
                if ((pd == null || pd.isEmpty()) && !multipartParams.isEmpty()) {
                    StringBuilder mp = new StringBuilder();
                    for (Map.Entry<String, List<String>> me : multipartParams.entrySet()) {
                        mp.append(me.getKey()).append('=');
                        List<String> vals = me.getValue();
                        if (vals == null) {
                            mp.append("<null>");
                        } else if (vals.size() == 1) {
                            mp.append(vals.get(0));
                        } else {
                            mp.append('[');
                            for (int j = 0; j < vals.size(); j++) {
                                if (j > 0) {
                                    mp.append(',');
                                }
                                mp.append(vals.get(j));
                            }
                            mp.append(']');
                        }
                        mp.append(';');
                    }
                    pd = mp.toString();
                }
                if (pd == null || pd.isEmpty()) {
                    pd = dumpRequestParameters(request);
                }
                if (pd == null || pd.isEmpty()) {
                    pd = dumpRequestBody(request);
                }
                LOGGER.log(Level.WARNING, "BAD_REQUEST: {0} {1}", new Object[]{e, pd});
            } catch (Exception ex) {
                // ignore logging errors
            }
            response.setContentType(CONTENT_TYPE);
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            response.getOutputStream().print(BAD_REQUEST);
            return;
        }

        String hostPort = sHost + ':' + sPort;
        try {
            Context env = (Context) (new InitialContext().lookup(Constants.JNDI_CONNECTION));
            DataSource ds = (DataSource) env.lookup(Constants.JNDI_DDBBCON_MYSQL);

            try (Connection conn = ds.getConnection()) {
                // Handle server stopping: delete rows atomically
                if (serverIsStopping != null) {
                    try (PreparedStatement st = conn.prepareStatement("DELETE FROM servers WHERE host = ? AND port = ?")) {
                        st.setString(1, sHost);
                        st.setInt(2, port);
                        st.executeUpdate();
                    }
                    try (PreparedStatement st = conn.prepareStatement("DELETE FROM variables WHERE hostport = ?")) {
                        st.setString(1, hostPort);
                        st.executeUpdate();
                    }
                    try (PreparedStatement st = conn.prepareStatement("DELETE FROM players WHERE hostport = ?")) {
                        st.setString(1, hostPort);
                        st.executeUpdate();
                    }
                    return;
                }

                boolean isSettingPlayers = (sPlUser != null) && !sPlUser.isEmpty() //
                        && (sPlName != null) && !sPlName.isEmpty() //
                        && (sPlNation != null) && !sPlNation.isEmpty() //
                        && (sPlFlag != null) && !sPlFlag.isEmpty() //
                        && (sPlType != null) && !sPlType.isEmpty() //
                        && (sPlHost != null) && !sPlHost.isEmpty();

                if (isSettingPlayers || (dropPlayers != null)) {
                    try (PreparedStatement st = conn.prepareStatement("DELETE FROM players WHERE hostport = ?")) {
                        st.setString(1, hostPort);
                        st.executeUpdate();
                    }

                    if (dropPlayers != null) {
                        try (PreparedStatement st = conn.prepareStatement("UPDATE servers SET available = 0, humans = -1 WHERE host = ? AND port = ?")) {
                            st.setString(1, sHost);
                            st.setInt(2, port);
                            st.executeUpdate();
                        }
                    }

                    if (isSettingPlayers) {
                        // Copy lists to local non-null references to avoid static analysis warnings
                        assert sPlUser != null && sPlName != null && sPlNation != null && sPlFlag != null && sPlType != null && sPlHost != null;
                        List<String> users = sPlUser;
                        List<String> names = sPlName;
                        List<String> nations = sPlNation;
                        List<String> flags = sPlFlag;
                        List<String> types = sPlType;
                        List<String> hosts = sPlHost;
                        try (PreparedStatement st = conn.prepareStatement("INSERT INTO players (hostport, name, user, nation, type, host, flag) VALUES (?, ?, ?, ?, ?, ?, ?)")) {
                            for (int i = 0; i < users.size(); i++) {
                                st.setString(1, hostPort);
                                st.setString(2, names.get(i));
                                st.setString(3, users.get(i));
                                st.setString(4, nations.get(i));
                                st.setString(5, types.get(i));
                                if (i >= hosts.size()) {
                                    st.setString(6, "");
                                } else {
                                    st.setString(6, hosts.get(i));
                                }
                                st.setString(7, flags.get(i));
                                st.addBatch();
                            }
                            st.executeBatch();
                        } catch (IndexOutOfBoundsException e) {
                            // Log parameters for debugging malformed player arrays
                            try {
                                String pd = (rawRequestBody != null && !rawRequestBody.isEmpty()) ? rawRequestBody : null;
                                if ((pd == null || pd.isEmpty()) && !multipartParams.isEmpty()) {
                                    StringBuilder mp = new StringBuilder();
                                    for (Map.Entry<String, List<String>> me : multipartParams.entrySet()) {
                                        mp.append(me.getKey()).append('=');
                                        List<String> vals = me.getValue();
                                        if (vals == null) {
                                            mp.append("<null>");
                                        } else if (vals.size() == 1) {
                                            mp.append(vals.get(0));
                                        } else {
                                            mp.append('[');
                                            for (int j = 0; j < vals.size(); j++) {
                                                if (j > 0) {
                                                    mp.append(',');
                                                }
                                                mp.append(vals.get(j));
                                            }
                                            mp.append(']');
                                        }
                                        mp.append(';');
                                    }
                                    pd = mp.toString();
                                }
                                if (pd == null || pd.isEmpty()) {
                                    pd = dumpRequestParameters(request);
                                }
                                if (pd == null || pd.isEmpty()) {
                                    pd = dumpRequestBody(request);
                                }
                                LOGGER.log(Level.WARNING, "BAD_REQUEST (players): {0}", new Object[]{pd});
                            } catch (Exception ex) {
                                LOGGER.log(Level.FINE, "Error logging BAD_REQUEST (players)", ex);
                            }
                            response.setContentType(CONTENT_TYPE);
                            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
                            response.getOutputStream().print(BAD_REQUEST);
                            return;
                        }
                    }
                }

                // delete this variables that this server might have already set
                try (PreparedStatement st = conn.prepareStatement("DELETE FROM variables WHERE hostport = ?")) {
                    st.setString(1, hostPort);
                    st.executeUpdate();
                }

                // variableNames / variableValues may be null when no variables were
                // posted. Check for null before calling isEmpty() to avoid
                // NullPointerException (which previously produced a 500 error).
                if ((variableNames != null && !variableNames.isEmpty()) && (variableValues != null && !variableValues.isEmpty())) {
                    try (PreparedStatement st = conn.prepareStatement("INSERT INTO variables (hostport, name, value) VALUES (?, ?, ?)")) {
                        for (int i = 0; i < variableNames.size(); i++) {
                            st.setString(1, hostPort);
                            st.setString(2, variableNames.get(i));
                            st.setString(3, variableValues.get(i));
                            st.addBatch();
                        }
                        st.executeBatch();
                    } catch (IndexOutOfBoundsException e) {
                        try {
                            String pd = (rawRequestBody != null && !rawRequestBody.isEmpty()) ? rawRequestBody : null;
                            if ((pd == null || pd.isEmpty()) && !multipartParams.isEmpty()) {
                                StringBuilder mp = new StringBuilder();
                                for (Map.Entry<String, List<String>> me : multipartParams.entrySet()) {
                                    mp.append(me.getKey()).append('=');
                                    List<String> vals = me.getValue();
                                    if (vals == null) {
                                        mp.append("<null>");
                                    } else if (vals.size() == 1) {
                                        mp.append(vals.get(0));
                                    } else {
                                        mp.append('[');
                                        for (int j = 0; j < vals.size(); j++) {
                                            if (j > 0) {
                                                mp.append(',');
                                            }
                                            mp.append(vals.get(j));
                                        }
                                        mp.append(']');
                                    }
                                    mp.append(';');
                                }
                                pd = mp.toString();
                            }
                            if (pd == null || pd.isEmpty()) {
                                pd = dumpRequestParameters(request);
                            }
                            if (pd == null || pd.isEmpty()) {
                                pd = dumpRequestBody(request);
                            }
                            LOGGER.log(Level.WARNING, "BAD_REQUEST (variables): {0}", new Object[]{pd});
                        } catch (Exception ex) {
                            LOGGER.log(Level.FINE, "Error logging BAD_REQUEST (variables)", ex);
                        }
                        response.setContentType(CONTENT_TYPE);
                        response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
                        response.getOutputStream().print(BAD_REQUEST);
                        return;
                    }
                }

                // Use an atomic upsert to avoid races between concurrent requests
                // that can lead to Duplicate entry PRIMARY key errors. Ensure
                // host and port are always included in the INSERT columns so the
                // ON DUPLICATE KEY UPDATE can match on the correct key.
                List<String> setServerVariables = new ArrayList<>(serverVariables.keySet());
                if (!setServerVariables.contains("host")) {
                    setServerVariables.add("host");
                }
                if (!setServerVariables.contains("port")) {
                    setServerVariables.add("port");
                }

                StringBuilder insertCols = new StringBuilder();
                StringBuilder insertPlaceholders = new StringBuilder();
                for (String parameter : setServerVariables) {
                    insertCols.append(parameter).append(", ");
                    insertPlaceholders.append("?, ");
                }
                // Remove trailing comma+space
                if (insertCols.length() >= 2) {
                    insertCols.setLength(insertCols.length() - 2);
                }
                if (insertPlaceholders.length() >= 2) {
                    insertPlaceholders.setLength(insertPlaceholders.length() - 2);
                }

                StringBuilder updateBuilder = new StringBuilder();
                for (String parameter : setServerVariables) {
                    updateBuilder.append(parameter).append(" = VALUES(").append(parameter).append("), ");
                }
                updateBuilder.append("stamp = NOW()");

                query = "INSERT INTO servers (" + insertCols.toString() + ", stamp) VALUES (" + insertPlaceholders.toString() + ", NOW()) ON DUPLICATE KEY UPDATE " + updateBuilder.toString();
                try (PreparedStatement st = conn.prepareStatement(query)) {
                    int idx = 1;
                    for (String parameter : setServerVariables) {
                        if ("port".equals(parameter)) {
                            // Use the validated numeric port variable
                            st.setInt(idx++, port);
                        } else if ("available".equals(parameter)) {
                            // available is numeric when supplied
                            String v = serverVariables.get("available");
                            try {
                                st.setInt(idx++, v == null ? 0 : Integer.parseInt(v));
                            } catch (NumberFormatException nfe) {
                                st.setInt(idx++, 0);
                            }
                        } else if (serverVariables.containsKey(parameter)) {
                            String v = serverVariables.get(parameter);
                            st.setString(idx++, v);
                        } else if ("host".equals(parameter)) {
                            st.setString(idx++, sHost);
                        } else {
                            // Fallback to empty string for unexpected missing values
                            st.setString(idx++, "");
                        }
                    }
                    st.executeUpdate();
                }
            }
        } catch (SQLException | NamingException err) {
            // Log the exception so we can diagnose runtime errors in the servlet
            LOGGER.log(Level.SEVERE, "Runtime error in Metaserver#doPost", err);
            response.setContentType(CONTENT_TYPE);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            try {
                response.getOutputStream().print(INTERNAL_SERVER_ERROR);
            } catch (IOException e) {
                LOGGER.log(Level.WARNING, "Failed to write error response", e);
            }
        }
    }

    // Helper to dump request parameters for debugging bad requests
    private String dumpRequestParameters(HttpServletRequest request) {
        StringBuilder sb = new StringBuilder();
        try {
            Map<String, String[]> params = request.getParameterMap();
            for (Map.Entry<String, String[]> e : params.entrySet()) {
                sb.append(e.getKey()).append('=');
                String[] vals = e.getValue();
                if (vals == null) {
                    sb.append("<null>");
                } else if (vals.length == 1) {
                    sb.append(vals[0]);
                } else {
                    sb.append('[');
                    for (int i = 0; i < vals.length; i++) {
                        if (i > 0) {
                            sb.append(',');
                        }
                        sb.append(vals[i]);
                    }
                    sb.append(']');
                }
                sb.append(';');
            }
        } catch (Exception e) {
            sb.append("<error>");
        }
        return sb.toString();
    }

    // Helper to read raw request body for non-form posts (debug only)
    private String dumpRequestBody(HttpServletRequest request) {
        try {
            String contentType = request.getContentType();
            if (contentType == null) {
                return "<no-content-type>";
            }
            // Only attempt to read when request has a body. Use IOUtils
            // to handle the reader content in one call and ensure UTF-8.
            try (InputStreamReader isr = new InputStreamReader(request.getInputStream(), StandardCharsets.UTF_8)) {
                String body = IOUtils.toString(isr);
                if (body == null || body.length() == 0) {
                    return "<empty-body>";
                }
                return body.length() > 1000 ? body.substring(0, 1000) + "..." : body;
            }
        } catch (IOException e) {
            return "<error-reading-body>";
        }
    }

    // Read the entire request body as a String. Caller must handle cases
    // where the stream has already been consumed.
    private String readRequestBodyFull(HttpServletRequest request) {
        try {
            return IOUtils.toString(request.getReader());
        } catch (IOException e) {
            return null;
        }
    }

    // BufferedRequestWrapper: caches the request body so it can be read
    // multiple times (by container parsers and by our debug code).
    private static class BufferedRequestWrapper extends jakarta.servlet.http.HttpServletRequestWrapper {

        private final byte[] buffer;

        public BufferedRequestWrapper(HttpServletRequest req) throws IOException {
            super(req);
            this.buffer = IOUtils.toByteArray(req.getInputStream());
        }

        @Override
        public jakarta.servlet.ServletInputStream getInputStream() {
            final java.io.ByteArrayInputStream bais = new java.io.ByteArrayInputStream(this.buffer == null ? new byte[0] : this.buffer);
            return new jakarta.servlet.ServletInputStream() {
                @Override
                public int read() throws IOException {
                    return bais.read();
                }

                @Override
                public boolean isFinished() {
                    return bais.available() == 0;
                }

                @Override
                public boolean isReady() {
                    return true;
                }

                @Override
                public void setReadListener(jakarta.servlet.ReadListener readListener) {
                    throw new UnsupportedOperationException();
                }
            };
        }

        @Override
        public java.io.BufferedReader getReader() throws IOException {
            return new java.io.BufferedReader(new java.io.InputStreamReader(getInputStream(), java.nio.charset.StandardCharsets.UTF_8));
        }

        public String getRequestBodyString() {
            return this.buffer != null ? new String(this.buffer, java.nio.charset.StandardCharsets.UTF_8) : null;
        }
    }

}
