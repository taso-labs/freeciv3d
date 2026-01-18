/*******************************************************************************
 * Freeciv-web - the web version of Freeciv. http://www.fciv.net/
 * Copyright (C) 2009-2025 The Freeciv-web project
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
 *******************************************************************************/
package org.freeciv.servlet;

import java.io.IOException;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;

import javax.naming.Context;
import javax.naming.InitialContext;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import javax.sql.DataSource;

import org.freeciv.util.Constants;

/**
 * Server allocation API for LLM game arena integration
 * Allocates available FreeCiv servers from the pool
 *
 * Supports game_id parameter for persistent game-port mapping:
 * - If game_id is provided and has an active allocation, returns the same port
 * - This enables reconnection to the same game after connection loss
 *
 * URL: /meta/allocate (mapped in web.xml)
 */
public class ServerAllocator extends HttpServlet {

	private static final long serialVersionUID = 1L;

	// Maximum age in seconds for a game allocation to be considered valid for reuse
	// After this time, the allocation is considered stale and a new port is assigned
	private static final int MAX_ALLOCATION_AGE_SECONDS = 3600; // 1 hour

	@Override
	public void doPost(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {

		response.setContentType("application/json");
		response.setCharacterEncoding("UTF-8");
		PrintWriter out = response.getWriter();

		String gameType = request.getParameter("type");
		String gameId = request.getParameter("game_id");

		if (gameType == null) {
			gameType = "multiplayer";
		}

		// Validate game type
		if (!gameType.equals("singleplayer") && !gameType.equals("multiplayer") &&
		    !gameType.equals("pbem") && !gameType.equals("longturn")) {
			response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
			out.write("{\"error\": \"Invalid game type. Must be one of: singleplayer, multiplayer, pbem, longturn\"}");
			return;
		}

		// Validate game_id format if provided (alphanumeric + hyphens, max 64 chars)
		if (gameId != null && !gameId.matches("^[a-zA-Z0-9\\-_]{1,64}$")) {
			response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
			out.write("{\"error\": \"Invalid game_id format. Must be alphanumeric with hyphens/underscores, max 64 chars.\"}");
			return;
		}

		Connection conn = null;
		PreparedStatement statement = null;
		ResultSet rs = null;

		try {
			Context env = (Context) (new InitialContext().lookup(Constants.JNDI_CONNECTION));
			DataSource ds = (DataSource) env.lookup(Constants.JNDI_DDBBCON_MYSQL);
			conn = ds.getConnection();

			// If game_id is provided, check for existing allocation first
			if (gameId != null) {
				String existingQuery = "SELECT port, host FROM game_allocations " +
					"WHERE game_id = ? AND released_at IS NULL " +
					"AND allocated_at > DATE_SUB(NOW(), INTERVAL ? SECOND)";
				statement = conn.prepareStatement(existingQuery);
				statement.setString(1, gameId);
				statement.setInt(2, MAX_ALLOCATION_AGE_SECONDS);
				rs = statement.executeQuery();

				if (rs.next()) {
					int existingPort = rs.getInt("port");
					String existingHost = rs.getString("host");
					int proxyPort = existingPort + 1000;

					// Update last_seen timestamp
					PreparedStatement updateLastSeen = conn.prepareStatement(
						"UPDATE game_allocations SET last_seen = NOW() WHERE game_id = ?");
					updateLastSeen.setString(1, gameId);
					updateLastSeen.executeUpdate();
					updateLastSeen.close();

					// Close existing result set before returning
					rs.close();
					statement.close();

					// Return existing allocation (reconnection case)
					String jsonResponse = String.format(
						"{\"success\": true, \"host\": \"%s\", \"port\": %d, \"proxy_port\": %d, \"type\": \"%s\", \"game_id\": \"%s\", \"reused\": true}",
						existingHost, existingPort, proxyPort, gameType, gameId
					);
					out.write(jsonResponse);
					response.setStatus(HttpServletResponse.SC_OK);
					return;
				}

				// Clean up for new allocation
				rs.close();
				statement.close();
				rs = null;
				statement = null;
			}

			// Find an available server of the requested type in Pregame state
			String query = "SELECT host, port FROM servers WHERE type = ? AND state = 'Pregame' AND available != 0 ORDER BY port LIMIT 1";
			statement = conn.prepareStatement(query);
			statement.setString(1, gameType);
			rs = statement.executeQuery();

			if (rs.next()) {
				String host = rs.getString("host");
				int port = rs.getInt("port");

				// Calculate proxy port (proxy port = game port + 1000)
				// Game ports: 6000-6009, Proxy ports: 7000-7009
				int proxyPort = port + 1000;

				// Mark server as unavailable (allocated)
				String updateQuery = "UPDATE servers SET available = 0, stamp = NOW() WHERE host = ? AND port = ?";
				PreparedStatement updateStmt = conn.prepareStatement(updateQuery);
				updateStmt.setString(1, host);
				updateStmt.setInt(2, port);
				int updated = updateStmt.executeUpdate();
				updateStmt.close();

				if (updated > 0) {
					// If game_id provided, store the allocation mapping
					if (gameId != null) {
						String insertAllocation = "INSERT INTO game_allocations (game_id, port, host, allocated_at) " +
							"VALUES (?, ?, ?, NOW()) " +
							"ON DUPLICATE KEY UPDATE port = VALUES(port), host = VALUES(host), " +
							"allocated_at = NOW(), released_at = NULL, last_seen = NOW()";
						PreparedStatement insertStmt = conn.prepareStatement(insertAllocation);
						insertStmt.setString(1, gameId);
						insertStmt.setInt(2, port);
						insertStmt.setString(3, host);
						insertStmt.executeUpdate();
						insertStmt.close();
					}

					// Return allocation details
					String jsonResponse;
					if (gameId != null) {
						jsonResponse = String.format(
							"{\"success\": true, \"host\": \"%s\", \"port\": %d, \"proxy_port\": %d, \"type\": \"%s\", \"game_id\": \"%s\", \"reused\": false}",
							host, port, proxyPort, gameType, gameId
						);
					} else {
						jsonResponse = String.format(
							"{\"success\": true, \"host\": \"%s\", \"port\": %d, \"proxy_port\": %d, \"type\": \"%s\"}",
							host, port, proxyPort, gameType
						);
					}
					out.write(jsonResponse);
					response.setStatus(HttpServletResponse.SC_OK);
				} else {
					response.setStatus(HttpServletResponse.SC_CONFLICT);
					out.write("{\"error\": \"Server allocation race condition. Please retry.\"}");
				}
			} else {
				// No available servers
				response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
				out.write("{\"error\": \"No available servers of type '" + gameType + "'. Please wait and retry.\"}");
			}

		} catch (Exception err) {
			response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
			out.write("{\"error\": \"Server allocation failed: " + err.getMessage() + "\"}");
			err.printStackTrace();
		} finally {
			if (rs != null) {
				try {
					rs.close();
				} catch (SQLException e) {
					e.printStackTrace();
				}
			}
			if (statement != null) {
				try {
					statement.close();
				} catch (SQLException e) {
					e.printStackTrace();
				}
			}
			if (conn != null) {
				try {
					conn.close();
				} catch (SQLException e) {
					e.printStackTrace();
				}
			}
		}
	}

	@Override
	public void doGet(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {
		// GET method returns API documentation
		response.setContentType("application/json");
		response.setCharacterEncoding("UTF-8");
		PrintWriter out = response.getWriter();

		String docs = "{"
			+ "\"endpoint\": \"/meta/allocate\","
			+ "\"method\": \"POST\","
			+ "\"parameters\": {"
			+ "\"type\": \"Game type (singleplayer, multiplayer, pbem, longturn). Default: multiplayer\","
			+ "\"game_id\": \"Optional. Unique game identifier (e.g., match_id from agent-clash). If provided, returns same port for same game_id on reconnection.\""
			+ "},"
			+ "\"response\": {"
			+ "\"success\": true,"
			+ "\"host\": \"localhost\","
			+ "\"port\": 6001,"
			+ "\"proxy_port\": 7001,"
			+ "\"type\": \"multiplayer\","
			+ "\"game_id\": \"optional - echoed back if provided\","
			+ "\"reused\": \"true if returning existing allocation, false if new allocation\""
			+ "},"
			+ "\"errors\": {\"400\": \"Invalid game type or game_id format\", \"503\": \"No available servers\", \"409\": \"Race condition\", \"500\": \"Internal server error\"}"
			+ "}";

		out.write(docs);
	}
}
