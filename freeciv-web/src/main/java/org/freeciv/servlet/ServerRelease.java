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
 * Server release API for LLM agent integration
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
			JSONObject errorJson = new JSONObject();
			errorJson.put("error", e.getMessage());
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
				// Mark server as available and reset to Pregame state
				int updated;
				try (PreparedStatement statement = conn.prepareStatement(
					"UPDATE servers SET available = 1, state = 'Pregame', stamp = NOW() WHERE host = ? AND port = ?")) {
					statement.setString(1, sHost);
					statement.setInt(2, port);
					updated = statement.executeUpdate();
				}

				// If game_id provided, mark the allocation as released (keep for history)
				// If no game_id, try to find and release by port
				boolean allocationReleased = false;
				if (gameId != null) {
					try (PreparedStatement releaseAllocation = conn.prepareStatement(
						"UPDATE game_allocations SET released_at = NOW() WHERE game_id = ? AND released_at IS NULL")) {
						releaseAllocation.setString(1, gameId);
						allocationReleased = releaseAllocation.executeUpdate() > 0;
					}
				} else {
					// Try to release by port if no game_id provided
					try (PreparedStatement releaseByPort = conn.prepareStatement(
						"UPDATE game_allocations SET released_at = NOW() WHERE port = ? AND released_at IS NULL")) {
						releaseByPort.setInt(1, port);
						allocationReleased = releaseByPort.executeUpdate() > 0;
					}
				}

				if (updated > 0) {
					JSONObject jsonResponse = new JSONObject();
					jsonResponse.put("success", true);
					jsonResponse.put("host", sHost);
					jsonResponse.put("port", port);
					jsonResponse.put("message", "Server released and available");
					if (allocationReleased) {
						jsonResponse.put("allocation_released", true);
					}

					out.write(jsonResponse.toString());
					response.setStatus(HttpServletResponse.SC_OK);
				} else {
					response.setStatus(HttpServletResponse.SC_NOT_FOUND);
					JSONObject errorJson = new JSONObject();
					errorJson.put("error", "Server not found or already available");
					out.write(errorJson.toString());
				}
			}

		} catch (Exception err) {
			response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
			JSONObject errorJson = new JSONObject();
			errorJson.put("error", "Server release failed: " + err.getMessage());
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
		docs.put("endpoint", "/meta/release");
		docs.put("method", "POST");

		JSONObject params = new JSONObject();
		params.put("host", "Server host (default: localhost)");
		params.put("port", "Server port (6000-6009)");
		params.put("game_id", "Optional. Game identifier to mark allocation as released in game_allocations table.");
		docs.put("parameters", params);

		JSONObject responseExample = new JSONObject();
		responseExample.put("success", true);
		responseExample.put("host", "localhost");
		responseExample.put("port", 6001);
		responseExample.put("message", "Server released and available");
		responseExample.put("allocation_released", "true if game_allocations record was updated");
		docs.put("response", responseExample);

		JSONObject errors = new JSONObject();
		errors.put("400", "Invalid parameters or game_id format");
		errors.put("404", "Server not found");
		errors.put("500", "Internal server error");
		docs.put("errors", errors);

		out.write(docs.toString());
	}
}
