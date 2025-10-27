# -*- coding: utf-8 -*-

"""
Freeciv - Copyright (C) 2009-2017 - Andreas Røsdal   andrearo@pvv.ntnu.no
  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2, or (at your option)
  any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.
"""

import platform
import threading
import time
from tornado import version as tornado_version
from civcom import CivCom

startTime = time.time()


def get_debug_info(civcoms: dict[str, CivCom]):
    code = f"""<html>
    <head>
        <meta http-equiv="refresh" content="20">
        <link href='/css/bootstrap.min.css' rel='stylesheet'>
    </head>
    <body>
        <div class='container'>
            <h2>Freeciv WebSocket Proxy Status</h2>
            <font color="green">Process status: OK</font>
            <br>
            <b>Process Uptime: {int(time.time() - startTime)} s.</b>
            <br>
            Python version: {platform.python_implementation()} {platform.python_version()} ({platform.python_build()[0]})
            <br>
            Platform: {platform.machine()} {platform.system()} on '{' '.join(platform.processor().split())}'
            <br>
            Tornado version {tornado_version}
            <br>
            Number of threads: {threading.active_count()}
            <br>
            <h3>Logged in users  (count {len(civcoms)}) :</h3>
"""
    for val in civcoms.values():
        code += f"""
        username: <b>{val.username}</b>
        <br>
        Civserver: {val.civserverport}
        <br>
        Connect time: {time.time() - val.connect_time}
        <br>
        <br>"""
    code += """        </div>
    </body>
</html>
"""

    return code
