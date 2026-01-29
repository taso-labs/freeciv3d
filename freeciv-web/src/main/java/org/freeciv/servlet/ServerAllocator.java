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

import java.util.logging.Logger;

/**
 * Server allocation API for LLM game arena integration
 * Allocates available FreeCiv servers from the pool
 *
 * Supports game_id parameter for persistent game-port mapping:
 * - If game_id is provided and has an active allocation, returns the same port
 * - This enables reconnection to the same game after connection loss
 *
 * Includes stale allocation cleanup:
 * - Runs before each allocation to reclaim zombie ports
 * - Zombie ports occur when gateway crashes without releasing the port
 * - Allocations older than STALE_ALLOCATION_THRESHOLD_MINUTES are auto-released
 *
 * URL: /meta/allocate (mapped in web.xml)
 */
public class ServerAllocator extends HttpServlet {

	private static final long serialVersionUID = 1L;
	private static final Logger logger = Logger.getLogger(ServerAllocator.class.getName());

	// Connection timeout for local port check (milliseconds)
	private static final int LOCAL_PORT_CHECK_TIMEOUT_MS = 500;

	// Maximum age in seconds for a game allocation to be considered valid for reuse
	// After this time, the allocation is considered stale and a new port is assigned
	// 24 hours allows for long-running LLM games with extended pauses
	private static final int MAX_ALLOCATION_AGE_SECONDS = 86400; // 24 hours

	// Threshold for stale allocation cleanup (minutes without activity)
	// Allocations without last_seen updates for this long are considered zombies
	// IMPORTANT: This should be LONGER than SESSION_SUSPENSION_TIMEOUT_SECS to allow
	// reconnection without premature port release. Default 45 min supports 30 min reconnection.
	// Can be overridden via system property: -Dfreeciv.stale.allocation.threshold.minutes=60
	private static final int STALE_ALLOCATION_THRESHOLD_MINUTES =
		Integer.getInteger("freeciv.stale.allocation.threshold.minutes", 45);

	/**
	 * Check if a port is actively listening on the local machine.
	 *
	 * In Kubernetes, each pod runs its own FreeCiv servers (ports 6000-6009).
	 * The metaserver database tracks all servers globally with host='localhost',
	 * but a port listed in the DB might not be running on THIS pod.
	 *
	 * This method validates that the allocated port is actually available
	 * on the local machine before returning it to the client.
	 *
	 * @param port The port number to check
	 * @return true if the port is listening locally, false otherwise
	 */
	private boolean isPortListeningLocally(int port) {
		try (java.net.Socket socket = new java.net.Socket()) {
			socket.connect(new java.net.InetSocketAddress("127.0.0.1", port), LOCAL_PORT_CHECK_TIMEOUT_MS);
			return true;
		} catch (java.io.IOException e) {
			// Connection refused or timeout - port is not listening
			return false;
		}
	}

	/**
	 * Clean up stale allocations that haven't been seen recently.
	 *
	 * This is a defensive layer against zombie sessions where the gateway
	 * crashes without calling /meta/release. Such allocations would otherwise
	 * keep ports marked as unavailable indefinitely.
	 *
	 * The cleanup:
	 * 1. Finds allocations that haven't been updated in STALE_ALLOCATION_THRESHOLD_MINUTES
	 * 2. Marks those allocations as released (sets released_at)
	 * 3. Resets the corresponding servers to available/Pregame state
	 *
	 * This runs at the start of each allocation request, which is appropriate
	 * because allocation requests are infrequent (game starts only) and the
	 * cleanup is lightweight (single indexed query).
	 *
	 * @param conn Database connection to use (should be within a transaction)
	 * @return Number of stale allocations cleaned up
	 */
	private int cleanupStaleAllocations(Connection conn) {
		int cleaned = 0;
		try {
			// Find and release stale allocations in one atomic operation
			// Uses INNER JOIN to update both tables together
			// Criteria:
			//   - allocation not released
			//   - last_seen older than threshold
			//   - server still in 'Pregame' state (game never started OR already finished)
			// CRITICAL: The state='Pregame' check prevents cleaning up RUNNING games!
			// Active games change state to 'Running', so they won't be affected.
			String cleanupQuery =
				"UPDATE servers s " +
				"INNER JOIN game_allocations ga ON s.port = ga.port AND s.host = ga.host " +
				"SET s.available = 1, s.state = 'Pregame', s.stamp = NOW(), ga.released_at = NOW() " +
				"WHERE s.available = 0 " +
				"AND s.state = 'Pregame' " +  // Only clean up if game never started
				"AND ga.released_at IS NULL " +
				"AND ga.last_seen < DATE_SUB(NOW(), INTERVAL ? MINUTE)";

			try (PreparedStatement stmt = conn.prepareStatement(cleanupQuery)) {
				stmt.setInt(1, STALE_ALLOCATION_THRESHOLD_MINUTES);
				cleaned = stmt.executeUpdate();

				if (cleaned > 0) {
					logger.info("Cleaned up " + cleaned + " stale allocation(s) (no activity for " +
						STALE_ALLOCATION_THRESHOLD_MINUTES + " minutes)");
				}
			}
		} catch (SQLException e) {
			// Log but don't fail - cleanup is best-effort
			logger.warning("Failed to cleanup stale allocations: " + e.getMessage());
		}
		return cleaned;
	}

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

			// Run stale cleanup in a separate auto-commit connection BEFORE the allocation transaction
			// This ensures cleanup persists even if subsequent allocation fails and rolls back
			try (Connection cleanupConn = ds.getConnection()) {
				// Auto-commit is default (true), cleanup commits immediately
				cleanupStaleAllocations(cleanupConn);
			}

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

					// Find available servers of the requested type in Pregame state
					// SKIP LOCKED prevents race conditions: if another thread locked a row, skip it instead of waiting
					// Get all candidates (no LIMIT 1) to find one that's actually running on this pod
					String query = "SELECT host, port FROM servers WHERE type = ? AND state = 'Pregame' AND available != 0 ORDER BY port FOR UPDATE SKIP LOCKED";
					try (PreparedStatement statement = conn.prepareStatement(query)) {
						statement.setString(1, gameType);

						try (ResultSet rs = statement.executeQuery()) {
							boolean allocated = false;
							int candidatesChecked = 0;

							// Iterate through candidates, pick first that's actually listening locally
							// This handles Kubernetes distributed state where DB shows ports that
							// may not be running on this specific pod
							while (rs.next() && !allocated) {
								String host = rs.getString("host");
								int port = rs.getInt("port");
								candidatesChecked++;

								// Verify the port is actually running on this pod
								if (!isPortListeningLocally(port)) {
									// Port not listening locally - try next candidate
									// This happens in K8s when the metaserver DB has ports from other pods
									logger.info("Port " + port + " not listening locally, trying next candidate");
									continue;
								}

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
										allocated = true;
									}
									// If update failed (race condition), continue to next candidate
								}
							}

							if (!allocated) {
								conn.rollback();
								// No available servers running on this pod
								response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
								JSONObject errorJson = new JSONObject();
								if (candidatesChecked > 0) {
									errorJson.put("error", "No servers listening locally on this pod. Checked " + candidatesChecked + " candidates. Please retry.");
								} else {
									errorJson.put("error", "No available servers of type '" + gameType + "'. Please wait and retry.");
								}
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
