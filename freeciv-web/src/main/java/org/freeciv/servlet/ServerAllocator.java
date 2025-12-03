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

/**
 * Server allocation API for LLM game arena integration
 * Allocates available FreeCiv servers from the pool
 *
 * URL: /meta/allocate (mapped in web.xml)
 */
public class ServerAllocator extends HttpServlet {

	private static final long serialVersionUID = 1L;

	@Override
	public void doPost(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {

		response.setContentType("application/json");
		response.setCharacterEncoding("UTF-8");
		PrintWriter out = response.getWriter();

		String gameType = request.getParameter("type");
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

		Connection conn = null;
		PreparedStatement statement = null;
		ResultSet rs = null;

		try {
			Context env = (Context) (new InitialContext().lookup(Constants.JNDI_CONNECTION));
			DataSource ds = (DataSource) env.lookup(Constants.JNDI_DDBBCON_MYSQL);
			conn = ds.getConnection();

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
					// Return allocation details
					String jsonResponse = String.format(
						"{\"success\": true, \"host\": \"%s\", \"port\": %d, \"proxy_port\": %d, \"type\": \"%s\"}",
						host, port, proxyPort, gameType
					);
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
			+ "\"parameters\": {\"type\": \"Game type (singleplayer, multiplayer, pbem, longturn). Default: multiplayer\"},"
			+ "\"response\": {\"success\": true, \"host\": \"localhost\", \"port\": 6001, \"proxy_port\": 7001, \"type\": \"multiplayer\"},"
			+ "\"errors\": {\"400\": \"Invalid game type\", \"503\": \"No available servers\", \"500\": \"Internal server error\"}"
			+ "}";

		out.write(docs);
	}
}
