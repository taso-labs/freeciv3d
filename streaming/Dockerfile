# FreeCiv Streaming Container
# Captures WebGL game view via Puppeteer + x11grab FFmpeg and streams to YouTube
#
# Architecture:
#   Chrome (SwiftShader) → Xvfb (virtual display) → FFmpeg (x11grab) → RTMPS + local backup
#
# Usage:
#   docker build -t fciv-streamer .
#   docker run -e OBSERVER_URL=... -e STREAM_KEY=... fciv-streamer

# Stage 1: Get static FFmpeg binary
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

# Stage 2: Build streaming container
FROM ghcr.io/puppeteer/puppeteer:23.11.1

# Switch to root to install additional packages
USER root

# Copy static ffmpeg from first stage (no apt needed!)
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

# Install only Xvfb (minimal apt usage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Create directories and set permissions (as root)
WORKDIR /app
RUN mkdir -p /backup && chown -R pptruser:pptruser /app /backup

# Copy entrypoint script (as root for execute permissions)
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Switch to pptruser for security
USER pptruser

# Copy package files and install dependencies
COPY --chown=pptruser:pptruser package.json package-lock.json* ./
RUN npm ci --omit=dev

# Copy application code
COPY --chown=pptruser:pptruser stream.js ./

# Set environment defaults
ENV DISPLAY=:99 \
    RESOLUTION=1280x720 \
    FPS=30 \
    BITRATE=2500k \
    MAX_RETRIES=3 \
    RETRY_DELAY_MS=5000 \
    BACKUP_PATH=/backup/recording.mp4

# Expose no ports - this container only makes outbound RTMPS connections

# Health check - verify Xvfb and Chrome are running
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -x Xvfb && pgrep -f chrome || exit 1

# Entrypoint script:
# 1. Launches Xvfb virtual display
# 2. Runs the Node.js streaming script
# 3. Handles graceful shutdown
ENTRYPOINT ["/docker-entrypoint.sh"]
