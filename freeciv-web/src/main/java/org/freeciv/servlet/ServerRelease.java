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
import java.sql.SQLException;

import javax.naming.Context;
import javax.naming.InitialContext;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import javax.sql.DataSource;

import org.freeciv.util.Constants;

/**
 * Server release API for LLM game arena integration
 * Releases allocated servers back to the available pool
 *
 * Supports game_id parameter:
 * - If game_id is provided, marks the game_allocations record as released
 * - This preserves allocation history for debugging
 *
 * URL: /meta/release (mapped in web.xml)
 */
public class ServerRelease extends HttpServlet {

	private static final long serialVersionUID = 1L;

	@Override
	public void doPost(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {

		response.setContentType("application/json");
		response.setCharacterEncoding("UTF-8");
		PrintWriter out = response.getWriter();

		String sPort = request.getParameter("port");
		String sHost = request.getParameter("host");
		String gameId = request.getParameter("game_id");

		if (sHost == null) {
			sHost = "localhost";
		}

		int port;
		try {
			if (sPort == null) {
				throw new IllegalArgumentException("Port parameter is required");
			}
			port = Integer.parseInt(sPort);
			if ((port < 6000) || (port > 6009)) {
				throw new IllegalArgumentException("Invalid port. Expected value between 6000-6009");
			}
		} catch (IllegalArgumentException e) {
			response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
			out.write("{\"error\": \"" + e.getMessage() + "\"}");
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

		try {
			Context env = (Context) (new InitialContext().lookup(Constants.JNDI_CONNECTION));
			DataSource ds = (DataSource) env.lookup(Constants.JNDI_DDBBCON_MYSQL);
			conn = ds.getConnection();

			// Mark server as available and reset to Pregame state
			String updateQuery = "UPDATE servers SET available = 1, state = 'Pregame', stamp = NOW() WHERE host = ? AND port = ?";
			statement = conn.prepareStatement(updateQuery);
			statement.setString(1, sHost);
			statement.setInt(2, port);
			int updated = statement.executeUpdate();
			statement.close();

			// If game_id provided, mark the allocation as released (keep for history)
			// If no game_id, try to find and release by port
			String allocationUpdateMsg = "";
			if (gameId != null) {
				PreparedStatement releaseAllocation = conn.prepareStatement(
					"UPDATE game_allocations SET released_at = NOW() WHERE game_id = ? AND released_at IS NULL");
				releaseAllocation.setString(1, gameId);
				int allocationUpdated = releaseAllocation.executeUpdate();
				releaseAllocation.close();
				if (allocationUpdated > 0) {
					allocationUpdateMsg = ", allocation_released: true";
				}
			} else {
				// Try to release by port if no game_id provided
				PreparedStatement releaseByPort = conn.prepareStatement(
					"UPDATE game_allocations SET released_at = NOW() WHERE port = ? AND released_at IS NULL");
				releaseByPort.setInt(1, port);
				int allocationUpdated = releaseByPort.executeUpdate();
				releaseByPort.close();
				if (allocationUpdated > 0) {
					allocationUpdateMsg = ", allocation_released: true";
				}
			}

			if (updated > 0) {
				String jsonResponse = String.format(
					"{\"success\": true, \"host\": \"%s\", \"port\": %d, \"message\": \"Server released and available\"%s}",
					sHost, port, allocationUpdateMsg
				);
				out.write(jsonResponse);
				response.setStatus(HttpServletResponse.SC_OK);
			} else {
				response.setStatus(HttpServletResponse.SC_NOT_FOUND);
				out.write("{\"error\": \"Server not found or already available\"}");
			}

		} catch (Exception err) {
			response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
			out.write("{\"error\": \"Server release failed: " + err.getMessage() + "\"}");
			err.printStackTrace();
		} finally {
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
			+ "\"endpoint\": \"/meta/release\","
			+ "\"method\": \"POST\","
			+ "\"parameters\": {"
			+ "\"host\": \"Server host (default: localhost)\","
			+ "\"port\": \"Server port (6000-6009)\","
			+ "\"game_id\": \"Optional. Game identifier to mark allocation as released in game_allocations table.\""
			+ "},"
			+ "\"response\": {"
			+ "\"success\": true,"
			+ "\"host\": \"localhost\","
			+ "\"port\": 6001,"
			+ "\"message\": \"Server released and available\","
			+ "\"allocation_released\": \"true if game_allocations record was updated\""
			+ "},"
			+ "\"errors\": {\"400\": \"Invalid parameters or game_id format\", \"404\": \"Server not found\", \"500\": \"Internal server error\"}"
			+ "}";

		out.write(docs);
	}
}
