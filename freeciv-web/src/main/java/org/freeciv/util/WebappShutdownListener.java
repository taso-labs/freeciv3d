package org.freeciv.util;

import jakarta.servlet.ServletContextEvent;
import jakarta.servlet.ServletContextListener;
import jakarta.servlet.annotation.WebListener;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Enumeration;

/**
 * Ensures JDBC drivers are deregistered and MySQL abandoned connection cleanup
 * thread is stopped when the web application is undeployed to avoid memory leak
 * warnings.
 */
@WebListener
public class WebappShutdownListener implements ServletContextListener {

    @Override
    public void contextInitialized(ServletContextEvent sce) {
        // no-op
    }

    @Override
    public void contextDestroyed(ServletContextEvent sce) {
        // Deregister JDBC drivers registered by this webapp
        ClassLoader cl = Thread.currentThread().getContextClassLoader();
        Enumeration<Driver> drivers = DriverManager.getDrivers();
        while (drivers.hasMoreElements()) {
            Driver driver = drivers.nextElement();
            if (driver.getClass().getClassLoader() == cl) {
                try {
                    DriverManager.deregisterDriver(driver);
                } catch (SQLException ex) {
                    // ignore - nothing sensible to do during shutdown
                }
            }
        }

        // Try to stop MySQL AbandonedConnectionCleanupThread if present
        try {
            com.mysql.cj.jdbc.AbandonedConnectionCleanupThread.checkedShutdown();
        } catch (Throwable t) {
            // ignore - driver may be different version or not present
        }
    }
}
