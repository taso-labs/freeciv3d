/**
 * TDD tests for FreeCiv streaming container.
 *
 * Tests cover:
 * - Browser launch with SwiftShader flags for WebGL
 * - Navigation to observer URL
 * - FFmpeg capture with dual output (RTMPS + local backup)
 * - Graceful shutdown handling
 * - Error handling and retries
 *
 * All external dependencies (Puppeteer, FFmpeg) are mocked.
 */

// Setup mocks before any imports
// Note: Jest allows variables prefixed with 'mock' to be referenced in jest.mock() factories
let mockPage;
let mockBrowser;
let mockFfmpegProcess;
let mockSpawnImpl;
let mockPuppeteerLaunchImpl;

jest.mock('child_process', () => ({
  spawn: jest.fn((...args) => mockSpawnImpl(...args)),
}));

jest.mock('puppeteer', () => ({
  launch: jest.fn((...args) => mockPuppeteerLaunchImpl(...args)),
}));

const { spawn } = require('child_process');
const puppeteer = require('puppeteer');

describe('StreamCapture', () => {
  let StreamCapture;
  let getConfigFromEnv;
  let isValidPath;

  beforeEach(() => {
    // Reset module cache to get fresh imports
    jest.resetModules();

    // Create fresh mock objects
    mockPage = {
      goto: jest.fn().mockResolvedValue(undefined),
      waitForSelector: jest.fn().mockResolvedValue(undefined),
      evaluate: jest.fn().mockResolvedValue(true),
      setViewport: jest.fn().mockResolvedValue(undefined),
      on: jest.fn(),
      close: jest.fn().mockResolvedValue(undefined),
    };

    mockBrowser = {
      newPage: jest.fn().mockResolvedValue(mockPage),
      close: jest.fn().mockResolvedValue(undefined),
    };

    mockFfmpegProcess = {
      stdin: { write: jest.fn(), end: jest.fn() },
      stdout: { on: jest.fn().mockReturnThis() },
      stderr: { on: jest.fn().mockReturnThis() },
      on: jest.fn().mockReturnThis(),
      kill: jest.fn(),
      pid: 12345,
    };

    // Configure mock implementations
    mockPuppeteerLaunchImpl = jest.fn().mockResolvedValue(mockBrowser);
    mockSpawnImpl = jest.fn().mockReturnValue(mockFfmpegProcess);

    // Re-import after mocks are configured
    const streamModule = require('../stream');
    StreamCapture = streamModule.StreamCapture;
    getConfigFromEnv = streamModule.getConfigFromEnv;
    isValidPath = streamModule.isValidPath;
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('Browser Launch', () => {
    test('launches Chrome with SwiftShader flags for software WebGL', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/?action=observe',
        streamKey: 'test-stream-key',
      });

      await capture.launchBrowser();

      expect(mockPuppeteerLaunchImpl).toHaveBeenCalledWith(
        expect.objectContaining({
          args: expect.arrayContaining([
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--use-gl=swiftshader',
            '--enable-webgl',
          ]),
        })
      );
    });

    test('sets viewport to 1280x720 for streaming', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        resolution: '1280x720',
      });

      await capture.launchBrowser();

      expect(mockPage.setViewport).toHaveBeenCalledWith({
        width: 1280,
        height: 720,
      });
    });

    test('uses custom resolution when provided', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        resolution: '1920x1080',
      });

      await capture.launchBrowser();

      expect(mockPage.setViewport).toHaveBeenCalledWith({
        width: 1920,
        height: 1080,
      });
    });
  });

  describe('Navigation', () => {
    test('navigates to observer URL', async () => {
      const observerUrl = 'http://localhost:8080/webclient/?action=observe&camera=strategic';
      const capture = new StreamCapture({
        observerUrl,
        streamKey: 'test-key',
      });

      await capture.launchBrowser();
      await capture.navigateToGame();

      expect(mockPage.goto).toHaveBeenCalledWith(observerUrl, expect.any(Object));
    });

    test('waits for WebGL canvas to render', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
      });

      await capture.launchBrowser();
      await capture.navigateToGame();

      expect(mockPage.waitForSelector).toHaveBeenCalledWith(
        'canvas',
        expect.objectContaining({ timeout: expect.any(Number) })
      );
    });

    test('retries navigation on WebSocket disconnect', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        maxRetries: 3,
        retryDelay: 10,
      });

      mockPage.goto
        .mockRejectedValueOnce(new Error('WebSocket closed'))
        .mockResolvedValueOnce(undefined);

      await capture.launchBrowser();
      await capture.navigateToGame();

      expect(mockPage.goto).toHaveBeenCalledTimes(2);
    });
  });

  describe('FFmpeg Capture', () => {
    test('starts FFmpeg with correct x11grab settings', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-stream-key',
        resolution: '1280x720',
        fps: 30,
      });

      await capture.startFfmpeg();

      expect(mockSpawnImpl).toHaveBeenCalledWith(
        'ffmpeg',
        expect.arrayContaining([
          '-f', 'x11grab',
          '-video_size', '1280x720',
          '-framerate', '30',
        ]),
        expect.any(Object)
      );
    });

    test('outputs to both RTMPS and local file using tee muxer', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'my-stream-key',
        backupPath: '/backup/recording.mp4',
      });

      await capture.startFfmpeg();

      const ffmpegArgs = mockSpawnImpl.mock.calls[0][1];
      const argsString = ffmpegArgs.join(' ');

      expect(argsString).toContain('tee');
      expect(argsString).toContain('rtmps://');
      expect(argsString).toContain('my-stream-key');
      expect(argsString).toContain('/backup/recording.mp4');
    });

    test('uses specified bitrate', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        bitrate: '4000k',
      });

      await capture.startFfmpeg();

      const ffmpegArgs = mockSpawnImpl.mock.calls[0][1];
      expect(ffmpegArgs).toContain('4000k');
    });
  });

  describe('Graceful Shutdown', () => {
    test('stops FFmpeg on SIGTERM', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
      });

      await capture.launchBrowser();
      await capture.startFfmpeg();

      // Simulate immediate exit
      mockFfmpegProcess.on.mockImplementation((event, cb) => {
        if (event === 'exit') {
          setTimeout(cb, 10);
        }
        return mockFfmpegProcess;
      });

      await capture.shutdown();

      expect(mockFfmpegProcess.kill).toHaveBeenCalledWith('SIGTERM');
    });

    test('closes browser on shutdown', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
      });

      await capture.launchBrowser();
      await capture.shutdown();

      expect(mockBrowser.close).toHaveBeenCalled();
    });

    test('waits for FFmpeg to finish writing before exit', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
      });

      await capture.launchBrowser();
      await capture.startFfmpeg();

      const exitCalls = mockFfmpegProcess.on.mock.calls.filter(
        call => call[0] === 'exit'
      );
      expect(exitCalls.length).toBeGreaterThan(0);
    });
  });

  describe('Error Handling', () => {
    test('reports error when canvas not found', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        maxRetries: 1,
        retryDelay: 10,
      });

      mockPage.waitForSelector.mockRejectedValue(
        new Error('Timeout waiting for selector')
      );

      await capture.launchBrowser();
      await expect(capture.navigateToGame()).rejects.toThrow();
    });

    test('handles FFmpeg crash gracefully', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
      });

      await capture.startFfmpeg();

      const errorCalls = mockFfmpegProcess.on.mock.calls.filter(
        call => call[0] === 'error'
      );
      expect(errorCalls.length).toBeGreaterThan(0);
    });

    test('retries on transient FFmpeg errors', async () => {
      const capture = new StreamCapture({
        observerUrl: 'http://localhost:8080/webclient/',
        streamKey: 'test-key',
        maxRetries: 3,
        retryDelay: 10,
      });

      mockSpawnImpl
        .mockImplementationOnce(() => {
          throw new Error('FFmpeg not found');
        })
        .mockReturnValueOnce(mockFfmpegProcess);

      await capture.startFfmpeg();
      expect(mockSpawnImpl).toHaveBeenCalledTimes(2);
    });
  });

  describe('Configuration', () => {
    test('reads configuration from environment variables', () => {
      process.env.OBSERVER_URL = 'http://test:8080/webclient/';
      process.env.STREAM_KEY = 'env-stream-key';
      process.env.RESOLUTION = '1920x1080';
      process.env.FPS = '60';
      process.env.BITRATE = '6000k';

      // Re-import to get fresh getConfigFromEnv
      jest.resetModules();
      const { getConfigFromEnv: freshGetConfig } = require('../stream');
      const config = freshGetConfig();

      expect(config.observerUrl).toBe('http://test:8080/webclient/');
      expect(config.streamKey).toBe('env-stream-key');
      expect(config.resolution).toBe('1920x1080');
      expect(config.fps).toBe(60);
      expect(config.bitrate).toBe('6000k');

      delete process.env.OBSERVER_URL;
      delete process.env.STREAM_KEY;
      delete process.env.RESOLUTION;
      delete process.env.FPS;
      delete process.env.BITRATE;
    });

    test('uses default values when env vars not set', () => {
      delete process.env.OBSERVER_URL;
      delete process.env.STREAM_KEY;
      delete process.env.RESOLUTION;
      delete process.env.FPS;
      delete process.env.BITRATE;

      jest.resetModules();
      const { getConfigFromEnv: freshGetConfig } = require('../stream');
      const config = freshGetConfig();

      expect(config.resolution).toBe('1280x720');
      expect(config.fps).toBe(30);
      expect(config.bitrate).toBe('2500k');
    });
  });

  describe('Security: Path Validation', () => {
    test('isValidPath accepts safe paths', () => {
      expect(isValidPath('/backup/recording.mp4')).toBe(true);
      expect(isValidPath('/tmp/game-123/output.mp4')).toBe(true);
      expect(isValidPath('/data/streams/match_456.mp4')).toBe(true);
      expect(isValidPath('recording.mp4')).toBe(true);
    });

    test('isValidPath rejects command injection attempts', () => {
      // Shell command injection
      expect(isValidPath('/backup/$(whoami).mp4')).toBe(false);
      expect(isValidPath('/backup/`id`.mp4')).toBe(false);
      expect(isValidPath('/backup/;rm -rf /')).toBe(false);
      expect(isValidPath('/backup/|cat /etc/passwd')).toBe(false);

      // Quotes that could escape FFmpeg arguments
      expect(isValidPath('/backup/"test.mp4')).toBe(false);
      expect(isValidPath("/backup/'test.mp4")).toBe(false);

      // Newlines/special chars
      expect(isValidPath('/backup/test\nrm.mp4')).toBe(false);
      expect(isValidPath('/backup/test\x00.mp4')).toBe(false);
    });

    test('isValidPath rejects path traversal attempts', () => {
      expect(isValidPath('/backup/../../../etc/passwd')).toBe(false);
      expect(isValidPath('../../../etc/passwd')).toBe(false);
      expect(isValidPath('/backup/..\\..\\windows\\system32')).toBe(false);
    });

    test('isValidPath rejects null/undefined/non-string inputs', () => {
      expect(isValidPath(null)).toBe(false);
      expect(isValidPath(undefined)).toBe(false);
      expect(isValidPath(123)).toBe(false);
      expect(isValidPath({})).toBe(false);
      expect(isValidPath('')).toBe(false);
    });

    test('StreamCapture constructor rejects unsafe backup paths', () => {
      expect(() => {
        new StreamCapture({
          observerUrl: 'http://localhost:8080/webclient/',
          streamKey: 'test-key',
          backupPath: '/backup/$(whoami).mp4',
        });
      }).toThrow('Invalid backup path');
    });

    test('StreamCapture constructor accepts safe backup paths', () => {
      expect(() => {
        new StreamCapture({
          observerUrl: 'http://localhost:8080/webclient/',
          streamKey: 'test-key',
          backupPath: '/backup/game-123/recording.mp4',
        });
      }).not.toThrow();
    });
  });
});
