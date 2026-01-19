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

import javax.naming.Context;
import javax.naming.InitialContext;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import javax.sql.DataSource;

import org.freeciv.util.Constants;
import org.json.JSONObject;

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
			JSONObject errorJson = new JSONObject();
			errorJson.put("error", "Invalid game type. Must be one of: singleplayer, multiplayer, pbem, longturn");
			out.write(errorJson.toString());
			return;
		}

		// Validate game_id format if provided (alphanumeric + hyphens, max 64 chars)
		if (gameId != null && !gameId.matches("^[a-zA-Z0-9\\-_]{1,64}$")) {
			response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
			JSONObject errorJson = new JSONObject();
			errorJson.put("error", "Invalid game_id format. Must be alphanumeric with hyphens/underscores, max 64 chars.");
			out.write(errorJson.toString());
			return;
		}

		try {
			Context env = (Context) (new InitialContext().lookup(Constants.JNDI_CONNECTION));
			DataSource ds = (DataSource) env.lookup(Constants.JNDI_DDBBCON_MYSQL);

			try (Connection conn = ds.getConnection()) {
				// Use transaction for atomicity (prevents race conditions)
				conn.setAutoCommit(false);

				try {
					// If game_id is provided, check for existing allocation first
					// Use FOR UPDATE to lock the row and prevent race conditions
					if (gameId != null) {
						String existingQuery = "SELECT port, host FROM game_allocations " +
							"WHERE game_id = ? AND released_at IS NULL " +
							"AND allocated_at > DATE_SUB(NOW(), INTERVAL ? SECOND) " +
							"FOR UPDATE";

						try (PreparedStatement statement = conn.prepareStatement(existingQuery)) {
							statement.setString(1, gameId);
							statement.setInt(2, MAX_ALLOCATION_AGE_SECONDS);

							try (ResultSet rs = statement.executeQuery()) {
								if (rs.next()) {
									int existingPort = rs.getInt("port");
									String existingHost = rs.getString("host");
									int proxyPort = existingPort + 1000;

									// Update last_seen timestamp
									try (PreparedStatement updateLastSeen = conn.prepareStatement(
										"UPDATE game_allocations SET last_seen = NOW() WHERE game_id = ?")) {
										updateLastSeen.setString(1, gameId);
										updateLastSeen.executeUpdate();
									}

									conn.commit();

									// Return existing allocation (reconnection case)
									JSONObject jsonResponse = new JSONObject();
									jsonResponse.put("success", true);
									jsonResponse.put("host", existingHost);
									jsonResponse.put("port", existingPort);
									jsonResponse.put("proxy_port", proxyPort);
									jsonResponse.put("type", gameType);
									jsonResponse.put("game_id", gameId);
									jsonResponse.put("reused", true);

									out.write(jsonResponse.toString());
									response.setStatus(HttpServletResponse.SC_OK);
									return;
								}
							}
						}
					}

					// Find an available server of the requested type in Pregame state
					String query = "SELECT host, port FROM servers WHERE type = ? AND state = 'Pregame' AND available != 0 ORDER BY port LIMIT 1 FOR UPDATE";
					try (PreparedStatement statement = conn.prepareStatement(query)) {
						statement.setString(1, gameType);

						try (ResultSet rs = statement.executeQuery()) {
							if (rs.next()) {
								String host = rs.getString("host");
								int port = rs.getInt("port");

								// Calculate proxy port (proxy port = game port + 1000)
								// Game ports: 6000-6009, Proxy ports: 7000-7009
								int proxyPort = port + 1000;

								// Mark server as unavailable (allocated)
								try (PreparedStatement updateStmt = conn.prepareStatement(
									"UPDATE servers SET available = 0, stamp = NOW() WHERE host = ? AND port = ?")) {
									updateStmt.setString(1, host);
									updateStmt.setInt(2, port);
									int updated = updateStmt.executeUpdate();

									if (updated > 0) {
										// If game_id provided, store the allocation mapping
										if (gameId != null) {
											try (PreparedStatement insertStmt = conn.prepareStatement(
												"INSERT INTO game_allocations (game_id, port, host, allocated_at) " +
												"VALUES (?, ?, ?, NOW()) " +
												"ON DUPLICATE KEY UPDATE port = VALUES(port), host = VALUES(host), " +
												"allocated_at = NOW(), released_at = NULL, last_seen = NOW()")) {
												insertStmt.setString(1, gameId);
												insertStmt.setInt(2, port);
												insertStmt.setString(3, host);
												insertStmt.executeUpdate();
											}
										}

										conn.commit();

										// Return allocation details
										JSONObject jsonResponse = new JSONObject();
										jsonResponse.put("success", true);
										jsonResponse.put("host", host);
										jsonResponse.put("port", port);
										jsonResponse.put("proxy_port", proxyPort);
										jsonResponse.put("type", gameType);
										if (gameId != null) {
											jsonResponse.put("game_id", gameId);
											jsonResponse.put("reused", false);
										}

										out.write(jsonResponse.toString());
										response.setStatus(HttpServletResponse.SC_OK);
									} else {
										conn.rollback();
										response.setStatus(HttpServletResponse.SC_CONFLICT);
										JSONObject errorJson = new JSONObject();
										errorJson.put("error", "Server allocation race condition. Please retry.");
										out.write(errorJson.toString());
									}
								}
							} else {
								conn.rollback();
								// No available servers
								response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
								JSONObject errorJson = new JSONObject();
								errorJson.put("error", "No available servers of type '" + gameType + "'. Please wait and retry.");
								out.write(errorJson.toString());
							}
						}
					}
				} catch (SQLException e) {
					conn.rollback();
					throw e;
				}
			}

		} catch (Exception err) {
			response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
			JSONObject errorJson = new JSONObject();
			errorJson.put("error", "Server allocation failed: " + err.getMessage());
			out.write(errorJson.toString());
			err.printStackTrace();
		}
	}

	@Override
	public void doGet(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {
		// GET method returns API documentation
		response.setContentType("application/json");
		response.setCharacterEncoding("UTF-8");
		PrintWriter out = response.getWriter();

		JSONObject docs = new JSONObject();
		docs.put("endpoint", "/meta/allocate");
		docs.put("method", "POST");

		JSONObject params = new JSONObject();
		params.put("type", "Game type (singleplayer, multiplayer, pbem, longturn). Default: multiplayer");
		params.put("game_id", "Optional. Unique game identifier (e.g., match_id from agent-clash). If provided, returns same port for same game_id on reconnection.");
		docs.put("parameters", params);

		JSONObject responseExample = new JSONObject();
		responseExample.put("success", true);
		responseExample.put("host", "localhost");
		responseExample.put("port", 6001);
		responseExample.put("proxy_port", 7001);
		responseExample.put("type", "multiplayer");
		responseExample.put("game_id", "optional - echoed back if provided");
		responseExample.put("reused", "true if returning existing allocation, false if new allocation");
		docs.put("response", responseExample);

		JSONObject errors = new JSONObject();
		errors.put("400", "Invalid game type or game_id format");
		errors.put("503", "No available servers");
		errors.put("409", "Race condition");
		errors.put("500", "Internal server error");
		docs.put("errors", errors);

		out.write(docs.toString());
	}
}
