#!/bin/bash
# cleans up logs

find /home/freeciv/freeciv-web/freeciv-web/logs/*.log -exec cp /dev/null {} \;
