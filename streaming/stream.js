#!/usr/bin/env node
/**
 * FreeCiv Game Streaming - Puppeteer + FFmpeg orchestration
 *
 * Captures WebGL game view and streams to YouTube Live with local backup.
 *
 * Usage:
 *   # Production (YouTube):
 *   OBSERVER_URL=... STREAM_KEY=... node stream.js
 *
 *   # Development (local RTMP server):
 *   DEV_MODE=local OBSERVER_URL=... node stream.js
 *
 *   # File-only (no streaming):
 *   DEV_MODE=file OBSERVER_URL=... node stream.js
 *
 * Environment Variables:
 *   OBSERVER_URL    - FreeCiv observer URL with camera preset
 *   DEV_MODE        - Development mode: "local" (RTMP), "file" (backup only), or empty (YouTube)
 *   LOCAL_RTMP_URL  - Local RTMP server URL (default: rtmp://localhost:1935/stream/live)
 *   STREAM_KEY      - YouTube RTMPS stream key (required unless DEV_MODE is set)
 *   RESOLUTION      - Video resolution (default: 1280x720)
 *   FPS             - Frame rate (default: 30)
 *   BITRATE         - Video bitrate (default: 2500k)
 *   BACKUP_PATH     - Local backup file path (default: /backup/recording.mp4)
 *   DISPLAY         - X11 display (default: :99)
 */

const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { Storage } = require('@google-cloud/storage');

// GCS backup configuration (from environment)
// If GCS_BACKUP_BUCKET is not set, GCS upload is disabled
const GCS_BUCKET = process.env.GCS_BACKUP_BUCKET || '';
const GCS_PREFIX = process.env.GCS_BACKUP_PREFIX || 'stream-backups';
// Upload timeout to prevent blocking pod termination (default 5 min)
const GCS_UPLOAD_TIMEOUT_MS = parseInt(process.env.GCS_UPLOAD_TIMEOUT_MS, 10) || 300000;

// YouTube RTMPS ingestion URL (configurable for testing or region-specific endpoints)
const YOUTUBE_RTMPS_URL = process.env.YOUTUBE_RTMPS_URL || 'rtmps://a.rtmps.youtube.com/live2';

// Security: Allowed characters for file paths (prevents command injection in FFmpeg)
const SAFE_PATH_REGEX = /^[a-zA-Z0-9/_.-]+$/;

/**
 * Validate a file path to prevent command injection.
 * Only allows alphanumeric characters, slashes, underscores, dots, and hyphens.
 * @param {string} filePath - Path to validate
 * @returns {boolean} - True if path is safe
 */
function isValidPath(filePath) {
  if (!filePath || typeof filePath !== 'string') {
    return false;
  }
  // Check for safe characters only
  if (!SAFE_PATH_REGEX.test(filePath)) {
    return false;
  }
  // Prevent path traversal
  if (filePath.includes('..')) {
    return false;
  }
  return true;
}

/**
 * Validate observer URL to prevent malicious redirects.
 * Only allows http/https to known FreeCiv web hosts.
 *
 * @param {string} url - URL to validate
 * @returns {boolean} - True if URL is safe
 */
function isValidObserverUrl(url) {
  if (!url || typeof url !== 'string') {
    return false;
  }

  try {
    const parsed = new URL(url);

    // Only allow http/https protocols
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      console.error(`[Security] Observer URL uses disallowed protocol: ${parsed.protocol}`);
      return false;
    }

    // Whitelist of allowed hostnames (configurable via env)
    // Default includes common FreeCiv hosting domains and local development
    const allowedHostsEnv = process.env.ALLOWED_OBSERVER_HOSTS ||
      'localhost,host.docker.internal,freeciv.clashai.live,freeciv.agentclash.gg,127.0.0.1';
    const allowedHosts = allowedHostsEnv.split(',').map(h => h.trim().toLowerCase());

    // Check if hostname matches allowed list (exact match or subdomain)
    const hostname = parsed.hostname.toLowerCase();
    const isAllowed = allowedHosts.some(allowed =>
      hostname === allowed || hostname.endsWith('.' + allowed)
    );

    if (!isAllowed) {
      console.error(`[Security] Observer URL hostname not in allowlist: ${hostname}`);
      console.error(`[Security] Allowed hosts: ${allowedHosts.join(', ')}`);
      console.error('[Security] TIP: Set ALLOWED_OBSERVER_HOSTS to add custom hosts');
      return false;
    }

    return true;
  } catch (e) {
    console.error(`[Security] Invalid URL format: ${e.message}`);
    return false;
  }
}

/**
 * Get configuration from environment variables with defaults.
 */
function getConfigFromEnv() {
  return {
    observerUrl: process.env.OBSERVER_URL || '',
    streamKey: process.env.STREAM_KEY || '',
    devMode: process.env.DEV_MODE || '',  // "local", "file", or empty for YouTube
    localRtmpUrl: process.env.LOCAL_RTMP_URL || 'rtmp://localhost:1935/stream/live',
    resolution: process.env.RESOLUTION || '1280x720',
    fps: parseInt(process.env.FPS, 10) || 30,
    bitrate: process.env.BITRATE || '2500k',
    backupPath: process.env.BACKUP_PATH || '/backup/recording.mp4',
    display: process.env.DISPLAY || ':99',
    maxRetries: parseInt(process.env.MAX_RETRIES, 10) || 3,
    retryDelay: parseInt(process.env.RETRY_DELAY_MS, 10) || 5000,
  };
}

/**
 * StreamCapture - Orchestrates browser capture and FFmpeg streaming.
 */
class StreamCapture {
  constructor(config) {
    // Validate backup path before storing (prevent command injection in FFmpeg)
    const backupPath = config.backupPath || '/backup/recording.mp4';
    if (!isValidPath(backupPath)) {
      throw new Error(`Invalid backup path: contains unsafe characters. Allowed: alphanumeric, /, _, ., -`);
    }

    this.config = {
      observerUrl: config.observerUrl,
      streamKey: config.streamKey,
      devMode: config.devMode || '',
      localRtmpUrl: config.localRtmpUrl || 'rtmp://localhost:1935/stream/live',
      resolution: config.resolution || '1280x720',
      fps: config.fps || 30,
      bitrate: config.bitrate || '2500k',
      backupPath: backupPath,
      display: config.display || ':99',
      maxRetries: config.maxRetries || 3,
      retryDelay: config.retryDelay || 5000,
    };

    // Time-based progress logging (deterministic, every 10 seconds)
    this.lastProgressLog = 0;
    this.progressLogIntervalMs = 10000;

    this.browser = null;
    this.page = null;
    this.ffmpegProcess = null;
    this.isShuttingDown = false;

    // Parse resolution
    const [width, height] = this.config.resolution.split('x').map(Number);
    this.width = width;
    this.height = height;
  }

  /**
   * Launch Chrome with SwiftShader for software WebGL rendering.
   */
  async launchBrowser() {
    console.log('[StreamCapture] Launching browser with SwiftShader...');

    this.browser = await puppeteer.launch({
      headless: false, // Need visible window for x11grab
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        // SwiftShader WebGL configuration
        '--use-gl=swiftshader',
        '--use-angle=swiftshader',
        '--enable-webgl',
        '--enable-webgl2',
        // Memory and stability optimizations
        '--disable-dev-shm-usage',
        '--disable-background-networking',
        '--disable-default-apps',
        '--disable-extensions',
        '--disable-sync',
        '--disable-translate',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-features=TranslateUI',
        '--disable-ipc-flooding-protection',
        // Reduce memory pressure
        '--renderer-process-limit=1',
        '--single-process',
        '--memory-pressure-off',
        '--max-gum-fps=30',
        // Window settings
        '--window-size=' + this.config.resolution.replace('x', ','),
        '--no-first-run',
        '--mute-audio',
      ],
      defaultViewport: null, // Use window size
    });

    this.page = await this.browser.newPage();

    await this.page.setViewport({
      width: this.width,
      height: this.height,
    });

    // Log console messages for debugging
    this.page.on('console', msg => {
      console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`);
    });

    // Log page errors
    this.page.on('pageerror', err => {
      console.error(`[Browser Error] ${err.message}`);
    });

    console.log('[StreamCapture] Browser launched successfully');
  }

  /**
   * Navigate to the FreeCiv observer URL and wait for game to render.
   */
  async navigateToGame() {
    let lastError;

    for (let attempt = 1; attempt <= this.config.maxRetries; attempt++) {
      try {
        console.log(`[StreamCapture] Navigating to game (attempt ${attempt}/${this.config.maxRetries})...`);

        // Use 'domcontentloaded' instead of 'networkidle2' because WebSocket
        // reconnection attempts (from web-llm HMR) can block networkidle2 indefinitely.
        // We rely on the explicit canvas wait below instead.
        await this.page.goto(this.config.observerUrl, {
          waitUntil: 'domcontentloaded',
          timeout: 60000,
        });

        // Wait for WebGL canvas to be present (this is the real readiness check)
        console.log('[StreamCapture] Waiting for WebGL canvas...');
        await this.page.waitForSelector('canvas', {
          timeout: 90000, // Allow more time for game to initialize
        });

        // Verify WebGL is working
        const webglWorking = await this.page.evaluate(() => {
          const canvas = document.querySelector('canvas');
          if (!canvas) return false;
          const gl = canvas.getContext('webgl') || canvas.getContext('webgl2');
          return gl !== null;
        });

        if (!webglWorking) {
          throw new Error('WebGL context not available');
        }

        console.log('[StreamCapture] Game loaded successfully');
        return;

      } catch (error) {
        lastError = error;
        console.error(`[StreamCapture] Navigation failed: ${error.message}`);

        if (attempt < this.config.maxRetries) {
          console.log(`[StreamCapture] Retrying in ${this.config.retryDelay}ms...`);
          await this.sleep(this.config.retryDelay);
        }
      }
    }

    throw lastError;
  }

  /**
   * Build FFmpeg output arguments based on dev mode.
   * @returns {Object} { args: string[], streamTarget: string }
   */
  _buildFfmpegOutput() {
    const { devMode, localRtmpUrl, streamKey, backupPath } = this.config;

    if (devMode === 'file') {
      // File-only mode: just save to backup, no streaming
      return {
        args: ['-f', 'mp4', backupPath],
        streamTarget: 'file only',
      };
    }

    if (devMode === 'local') {
      // Local RTMP mode: stream to MediaMTX + backup
      // Key options for reliable RTMP streaming:
      // - flvflags=no_duration_filesize: prevents FFmpeg from seeking back to update headers
      // - bsfs/v=dump_extra: CRITICAL - adds H264 SPS/PPS to every keyframe
      //   This fixes "unable to parse H264 config: invalid size 1" errors in MediaMTX
      return {
        args: [
          '-f', 'tee',
          '-map', '0:v',
          `[f=flv:flvflags=no_duration_filesize:bsfs/v=dump_extra]${localRtmpUrl}|[f=mp4]${backupPath}`,
        ],
        streamTarget: localRtmpUrl,
      };
    }

    // Production mode: YouTube RTMPS + backup
    // bsfs/v=dump_extra adds H264 SPS/PPS to every keyframe for robust RTMP streaming
    const rtmpsOutput = `${YOUTUBE_RTMPS_URL}/${streamKey}`;
    return {
      args: [
        '-f', 'tee',
        '-map', '0:v',
        `[f=flv:bsfs/v=dump_extra]${rtmpsOutput}|[f=mp4]${backupPath}`,
      ],
      streamTarget: `${YOUTUBE_RTMPS_URL}/***`,
    };
  }

  /**
   * Start FFmpeg to capture X11 display and stream to YouTube + local backup.
   */
  async startFfmpeg() {
    let lastError;

    for (let attempt = 1; attempt <= this.config.maxRetries; attempt++) {
      try {
        console.log(`[StreamCapture] Starting FFmpeg (attempt ${attempt}/${this.config.maxRetries})...`);

        const { args: outputArgs, streamTarget } = this._buildFfmpegOutput();

        // FFmpeg args for x11grab -> encoder -> output
        const ffmpegArgs = [
          // Input: X11 display capture
          '-f', 'x11grab',
          '-video_size', this.config.resolution,
          '-framerate', String(this.config.fps),
          '-i', this.config.display,

          // Video encoding: H.264 with good streaming settings
          '-c:v', 'libx264',
          '-preset', 'veryfast',
          '-tune', 'zerolatency',
          '-b:v', this.config.bitrate,
          '-maxrate', this.config.bitrate,
          '-bufsize', this.config.bitrate.replace('k', '') * 2 + 'k',

          // Keyframe settings: fixed 2-second GOP for RTMP compatibility
          // -sc_threshold 0 disables scene change detection for predictable keyframes
          // -keyint_min should match -g for consistent GOP structure
          '-g', String(this.config.fps * 2), // Keyframe every 2 seconds
          '-keyint_min', String(this.config.fps * 2),
          '-sc_threshold', '0',

          // Global header ensures SPS/PPS stored in extradata for FLV container
          '-flags', '+global_header',

          // Pixel format for compatibility
          '-pix_fmt', 'yuv420p',

          // No audio (game has no audio worth capturing)
          '-an',

          // Output (mode-dependent)
          ...outputArgs,
        ];

        this.ffmpegProcess = spawn('ffmpeg', ffmpegArgs, {
          stdio: ['pipe', 'pipe', 'pipe'],
        });

        // Handle FFmpeg stdout/stderr
        this.ffmpegProcess.stdout.on('data', data => {
          console.log(`[FFmpeg] ${data.toString().trim()}`);
        });

        this.ffmpegProcess.stderr.on('data', data => {
          // FFmpeg outputs most info to stderr
          const msg = data.toString().trim();
          if (msg.includes('frame=') || msg.includes('fps=')) {
            // Progress update - use time-based throttling (deterministic, every 10 seconds)
            const now = Date.now();
            if (now - this.lastProgressLog > this.progressLogIntervalMs) {
              console.log(`[FFmpeg Progress] ${msg.substring(0, 80)}`);
              this.lastProgressLog = now;
            }
          } else {
            console.log(`[FFmpeg] ${msg}`);
          }
        });

        // Handle FFmpeg exit
        this.ffmpegProcess.on('exit', (code, signal) => {
          console.log(`[FFmpeg] Process exited with code ${code}, signal ${signal}`);
          if (!this.isShuttingDown && code !== 0) {
            console.error('[FFmpeg] Unexpected exit - stream may have failed');
          }
        });

        // Handle FFmpeg errors
        this.ffmpegProcess.on('error', error => {
          console.error(`[FFmpeg] Process error: ${error.message}`);
        });

        console.log(`[StreamCapture] FFmpeg started (PID: ${this.ffmpegProcess.pid})`);
        console.log(`[StreamCapture] Streaming to: ${streamTarget}`);
        console.log(`[StreamCapture] Backup to: ${this.config.backupPath}`);

        return;

      } catch (error) {
        lastError = error;
        console.error(`[StreamCapture] FFmpeg start failed: ${error.message}`);

        if (attempt < this.config.maxRetries) {
          console.log(`[StreamCapture] Retrying in ${this.config.retryDelay}ms...`);
          await this.sleep(this.config.retryDelay);
        }
      }
    }

    throw lastError;
  }

  /**
   * Upload backup recording to Google Cloud Storage.
   *
   * Uses Workload Identity in GKE for authentication (no explicit credentials needed).
   * If GCS_BACKUP_BUCKET is not set, upload is silently skipped.
   *
   * This is a best-effort operation - upload failures are logged but don't
   * prevent graceful shutdown (YouTube still has the recording).
   */
  async uploadBackupToGCS() {
    if (!GCS_BUCKET) {
      console.log('[GCS] Backup upload disabled (GCS_BACKUP_BUCKET not set)');
      return;
    }

    const backupPath = this.config.backupPath;
    if (!fs.existsSync(backupPath)) {
      console.warn(`[GCS] Backup file not found: ${backupPath}`);
      return;
    }

    // Get file size for logging
    const stats = fs.statSync(backupPath);
    const fileSizeMB = (stats.size / (1024 * 1024)).toFixed(2);

    // Storage client uses Workload Identity automatically in GKE
    const storage = new Storage();
    const bucket = storage.bucket(GCS_BUCKET);

    // Derive destination path: {prefix}/{filename}
    // backupPath format: /backup/{game_id}-{view}.mp4
    const fileName = path.basename(backupPath); // e.g., "game123-global.mp4"
    const destination = `${GCS_PREFIX}/${fileName}`;

    const timeoutSec = (GCS_UPLOAD_TIMEOUT_MS / 1000).toFixed(0);
    console.log(`[GCS] Uploading ${backupPath} (${fileSizeMB} MB) to gs://${GCS_BUCKET}/${destination} (timeout: ${timeoutSec}s)`);

    const startTime = Date.now();
    try {
      // Create upload promise
      const uploadPromise = bucket.upload(backupPath, {
        destination,
        metadata: {
          contentType: 'video/mp4',
          metadata: {
            uploadedBy: 'fciv-streamer',
            uploadedAt: new Date().toISOString(),
            resolution: this.config.resolution,
            fps: String(this.config.fps),
            bitrate: this.config.bitrate,
          }
        },
        resumable: true, // For large files (>5MB) - supports resume on failure
      });

      // Create timeout promise to prevent blocking pod termination
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error(`Upload timed out after ${timeoutSec}s`)), GCS_UPLOAD_TIMEOUT_MS);
      });

      // Race upload against timeout
      await Promise.race([uploadPromise, timeoutPromise]);

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      console.log(`[GCS] Upload complete: gs://${GCS_BUCKET}/${destination} (${elapsed}s)`);
    } catch (error) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      console.error(`[GCS] Upload failed after ${elapsed}s: ${error.message}`);
      // Don't throw - backup upload failure shouldn't prevent clean shutdown
      // YouTube still has the recording, and the local file persists for 30 min
    }
  }

  /**
   * Gracefully shutdown streaming.
   */
  async shutdown() {
    if (this.isShuttingDown) {
      console.log('[StreamCapture] Already shutting down...');
      return;
    }

    this.isShuttingDown = true;
    console.log('[StreamCapture] Initiating graceful shutdown...');

    // Stop FFmpeg first to ensure backup is written
    if (this.ffmpegProcess) {
      console.log('[StreamCapture] Stopping FFmpeg...');
      this.ffmpegProcess.kill('SIGTERM');

      // Wait for FFmpeg to finish writing
      await new Promise(resolve => {
        const timeout = setTimeout(() => {
          console.log('[StreamCapture] FFmpeg did not exit gracefully, forcing...');
          this.ffmpegProcess.kill('SIGKILL');
          resolve();
        }, 10000);

        this.ffmpegProcess.on('exit', () => {
          clearTimeout(timeout);
          resolve();
        });
      });
    }

    // Upload backup to GCS before closing browser
    // This happens after FFmpeg finishes to ensure the MP4 is complete
    await this.uploadBackupToGCS();

    // Close browser
    if (this.browser) {
      console.log('[StreamCapture] Closing browser...');
      await this.browser.close();
    }

    console.log('[StreamCapture] Shutdown complete');
  }

  /**
   * Helper: Sleep for ms milliseconds.
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Run the full capture pipeline.
   */
  async run() {
    try {
      await this.launchBrowser();
      await this.navigateToGame();
      await this.startFfmpeg();

      console.log('[StreamCapture] Streaming started successfully!');
      console.log('[StreamCapture] Press Ctrl+C to stop...');

      // Keep running until SIGTERM/SIGINT
      await new Promise(resolve => {
        process.on('SIGTERM', resolve);
        process.on('SIGINT', resolve);
      });

    } catch (error) {
      console.error(`[StreamCapture] Fatal error: ${error.message}`);
      throw error;

    } finally {
      await this.shutdown();
    }
  }
}

// Main entry point
async function main() {
  const config = getConfigFromEnv();

  if (!config.observerUrl) {
    console.error('ERROR: OBSERVER_URL environment variable is required');
    process.exit(1);
  }

  // Security: Validate observer URL before using it
  if (!isValidObserverUrl(config.observerUrl)) {
    console.error('ERROR: OBSERVER_URL is invalid or uses a disallowed hostname');
    console.error('TIP: Set ALLOWED_OBSERVER_HOSTS environment variable to add custom hosts');
    process.exit(1);
  }

  // Validate stream key requirement based on mode
  if (!config.devMode && !config.streamKey) {
    console.error('ERROR: STREAM_KEY environment variable is required for YouTube streaming');
    console.error('TIP: Set DEV_MODE=local for local RTMP, or DEV_MODE=file for file-only mode');
    process.exit(1);
  }

  // Log mode-specific configuration
  console.log('[StreamCapture] Configuration:');
  if (config.devMode) {
    console.log(`  Mode: DEVELOPMENT (${config.devMode})`);
    if (config.devMode === 'local') {
      console.log(`  RTMP Server: ${config.localRtmpUrl}`);
      console.log('  View stream: http://localhost:8888/stream/live/index.m3u8 (HLS)');
      console.log('               http://localhost:8889/stream/live (WebRTC)');
    } else if (config.devMode === 'file') {
      console.log('  Output: File only (no streaming)');
    }
  } else {
    console.log('  Mode: PRODUCTION (YouTube)');
  }
  console.log(`  Observer URL: ${config.observerUrl}`);
  console.log(`  Resolution: ${config.resolution}`);
  console.log(`  FPS: ${config.fps}`);
  console.log(`  Bitrate: ${config.bitrate}`);
  console.log(`  Backup Path: ${config.backupPath}`);

  const capture = new StreamCapture(config);
  await capture.run();
}

// Export for testing
module.exports = { StreamCapture, getConfigFromEnv, isValidPath, isValidObserverUrl };

// Run if executed directly
if (require.main === module) {
  main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}
