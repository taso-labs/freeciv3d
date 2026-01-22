#! /bin/bash
# starts freeciv-proxy and freeciv-web.
# This script is started by civlauncher.py in publite2.

if [ "$#" -ne 6 ]; then
  echo "init-freeciv-web.sh error: incorrect number of parameters." >&2
  exit 1
fi

declare -a args

addArgs() {
  local i=${#args[*]}
  for v in "$@"; do
    args[i]=${v}
    let i++
  done
}

echo "init-freeciv-web.sh port ${2}"

addArgs --debug verbose
addArgs --port "${2}"
addArgs --Announce none
addArgs --exit-on-end
addArgs --meta --keep --Metaserver "http://${4}" --identity localhost
addArgs --type "${5}"
addArgs --read "pubscript_${6}.serv"
addArgs --log "../logs/freeciv-web-log-${2}.log"

if [ "$5" = "pbem" ]; then
  addArgs --Ranklog "/var/lib/tomcat10/webapps/data/ranklogs/rank_${2}.log"
fi

savesdir=${1}
if [ "$5" = "longturn" ]; then
  savesdir="${savesdir}/lt/${6}"
  mkdir -p "${savesdir}"

  grep -q '^#\s*autoreload\s*$' "pubscript_${6}.serv"
  if [ $? -eq 0 ]; then
    lastsave=$(ls -t "${savesdir}" | head -n 1)
    if [ -n "${lastsave}" ]; then
      addArgs --file "${lastsave%.*}"
    fi
  fi
else
  # 300 seconds (5 minutes) allows time for reconnection after WebSocket disruptions
  # Previously 20 seconds caused civserver to exit during network issues, destroying game state
  # Fix for mid-game reconnection failures (E142 + E120)
  addArgs --quitidle 300
fi
addArgs --saves "${savesdir}"

export FREECIV_SAVE_PATH=${savesdir};
rm -f "/var/lib/tomcat10/webapps/data/scorelogs/score-${2}.log"
rm -f "../logs/freeciv-web-log-${2}.log"

# Export LLM Gateway environment variables for freeciv-proxy
export CACHE_HMAC_SECRET="${CACHE_HMAC_SECRET:-75d6fd1ee3fb974b9a04f64eae2d48f2d7acdbc294cda59bc75485bcfe0bf861}"
export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export SESSION_TIMEOUT_SECONDS="${SESSION_TIMEOUT_SECONDS:-3600}"
export API_KEY_SECRET="${API_KEY_SECRET:-test12345678901234567890123456789012}"
export LLM_API_TOKENS="${LLM_API_TOKENS:-test-token-fc3d-001,test-token-fc3d-002}"

python3 ../freeciv-proxy/freeciv-proxy.py "${3}" > "../logs/freeciv-proxy-${3}.log" 2>&1 &
proxy_pid=$! && 
${HOME}/freeciv/bin/freeciv-web "${args[@]}" > "../logs/freeciv-web-stdout-${2}.log" 2> "../logs/freeciv-web-stderr-${2}.log"

rc=$?; 
kill -9 $proxy_pid; 
exit $rc
