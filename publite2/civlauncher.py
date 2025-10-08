from threading import Thread
from subprocess import call
from shutil import *
import sys
from time import gmtime, strftime
import time

# The Civlauncher class launches a new instance of a Freeciv-web server in a 
# separate thread and restarts the process when the game ends.
class Civlauncher(Thread):

    def __init__ (self, gametype, scripttype, new_port, metahostpath, savesdir):
        Thread.__init__(self)
        self.daemon = True  # Allow program to exit even if threads are running
        self.new_port = new_port;
        self.gametype = gametype;
        self.scripttype = scripttype;
        self.metahostpath = metahostpath;
        self.savesdir = savesdir;
        self.started_time = strftime("%Y-%m-%d %H:%M:%S", gmtime());
        self.num_start = 0;
        self.num_error = 0;
        self.running = True;  # Flag for graceful shutdown
        self.max_errors = 10;  # Stop after too many consecutive errors

    def stop(self):
        """Gracefully stop this server launcher thread"""
        self.running = False;

    def run(self):
        consecutive_errors = 0;
        while self.running:
            try:
                print("Start freeciv-web on port " + str(self.new_port) +
                      " and freeciv-proxy on port " + str(1000 + self.new_port) + ".");
                retcode = call(["../publite2/init-freeciv-web.sh"
                               , self.savesdir
                               , str(self.new_port)
                               , str(1000 + self.new_port)
                               , self.metahostpath
                               , self.gametype
                               , self.scripttype])
                self.num_start += 1;
                if retcode > 0:
                    print("Freeciv-web port " + str(self.new_port) + " was terminated by signal " + str(retcode))
                    self.num_error += 1;
                    consecutive_errors += 1;

                    # Stop if too many consecutive errors
                    if consecutive_errors >= self.max_errors:
                        print(f"ERROR: Server on port {self.new_port} failed {consecutive_errors} times consecutively. Stopping.")
                        self.running = False;
                        break;
                else:
                    print("Freeciv-web port " + str(self.new_port) + " returned " + str(retcode))
                    consecutive_errors = 0;  # Reset on success
            except OSError as e:
                print("Execution failed:", e, file=sys.stderr)
                self.num_error += 1;
                consecutive_errors += 1;

                if consecutive_errors >= self.max_errors:
                    print(f"ERROR: Server on port {self.new_port} had {consecutive_errors} execution failures. Stopping.")
                    self.running = False;
                    break;
            time.sleep(5)

        print(f"Server launcher for port {self.new_port} shutting down gracefully.")

