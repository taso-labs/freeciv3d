#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Structured JSON logging with trace context injection for GCP Cloud Logging.

This module provides JSON-formatted logging that integrates with GCP Cloud Logging
and Cloud Trace. When a trace is active, log entries include the trace ID in the
format expected by Cloud Logging, enabling click-through from logs to traces.

Usage:
    from structured_logging import configure_structured_logging

    # At startup
    configure_structured_logging("llm-gateway", log_level="INFO")

    # Then use standard logging
    logger = logging.getLogger("llm-gateway")
    logger.info("Message with trace context auto-injected")
"""

import os
import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Try to import python-json-logger
try:
    from pythonjsonlogger import jsonlogger
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False

# Try to import OpenTelemetry for trace context
try:
    from opentelemetry import trace
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


class CloudLoggingFormatter(logging.Formatter):
    """
    JSON formatter that outputs logs in a format compatible with GCP Cloud Logging.

    Features:
    - JSON output on a single line
    - RFC3339 timestamps
    - Severity mapping to Cloud Logging levels
    - Automatic trace context injection from OpenTelemetry
    - Source location (file, line, function)
    """

    # Map Python log levels to Cloud Logging severity
    SEVERITY_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def __init__(self, service_name: str = "unknown"):
        super().__init__()
        self.service_name = service_name
        self.project_id = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", ""))

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON for Cloud Logging."""
        log_entry: Dict[str, Any] = {}

        # Timestamp in RFC3339 format
        log_entry["timestamp"] = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).isoformat()

        # Severity
        log_entry["severity"] = self.SEVERITY_MAP.get(record.levelno, "DEFAULT")

        # Message
        log_entry["message"] = record.getMessage()

        # Logger name
        log_entry["logger"] = record.name

        # Service name
        log_entry["serviceContext"] = {"service": self.service_name}

        # Source location
        log_entry["logging.googleapis.com/sourceLocation"] = {
            "file": record.pathname,
            "line": str(record.lineno),
            "function": record.funcName,
        }

        # Inject trace context if OpenTelemetry is available and span is active
        if OTEL_AVAILABLE:
            try:
                span = trace.get_current_span()
                if span and span.is_recording():
                    ctx = span.get_span_context()
                    if ctx.is_valid:
                        # Format for Cloud Logging trace correlation
                        if self.project_id:
                            log_entry["logging.googleapis.com/trace"] = (
                                f"projects/{self.project_id}/traces/{ctx.trace_id:032x}"
                            )
                        log_entry["logging.googleapis.com/spanId"] = f"{ctx.span_id:016x}"
                        log_entry["logging.googleapis.com/trace_sampled"] = bool(
                            ctx.trace_flags & 0x01
                        )
            except Exception:
                pass  # Don't fail logging if trace context extraction fails

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "taskName"
            ):
                # Sanitize value for JSON serialization
                try:
                    json.dumps(value)  # Test if serializable
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        # Exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Return single-line JSON
        return json.dumps(log_entry, default=str)


class TraceContextFilter(logging.Filter):
    """
    Logging filter that adds trace context fields to log records.

    This allows trace context to be used in format strings even with
    non-JSON formatters.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add trace context fields to the log record."""
        record.trace_id = ""
        record.span_id = ""
        record.trace_sampled = False

        if OTEL_AVAILABLE:
            try:
                span = trace.get_current_span()
                if span and span.is_recording():
                    ctx = span.get_span_context()
                    if ctx.is_valid:
                        record.trace_id = f"{ctx.trace_id:032x}"
                        record.span_id = f"{ctx.span_id:016x}"
                        record.trace_sampled = bool(ctx.trace_flags & 0x01)
            except Exception:
                pass

        return True


def configure_structured_logging(
    service_name: str,
    log_level: str = "INFO",
    use_json: bool = True,
    add_console_handler: bool = True
) -> logging.Logger:
    """
    Configure structured JSON logging for GCP Cloud Logging integration.

    Args:
        service_name: Name of the service (used in logs and trace correlation)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: Whether to use JSON format (True for GCP, False for local dev)
        add_console_handler: Whether to add a stdout handler

    Returns:
        Configured root logger
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    if add_console_handler:
        # Console handler for stdout (captured by GCP Cloud Logging)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        if use_json:
            # Use our Cloud Logging compatible formatter
            formatter = CloudLoggingFormatter(service_name=service_name)
        else:
            # Plain text format for local development
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - [trace_id=%(trace_id)s] - %(message)s"
            )
            # Add filter for trace context in format string
            console_handler.addFilter(TraceContextFilter())

        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Return the service-specific logger
    return logging.getLogger(service_name)


def get_trace_context_for_logging() -> Dict[str, Any]:
    """
    Get trace context as a dict for manual logging inclusion.

    Useful when you need to include trace context in a specific log message
    or when not using structured logging.

    Returns:
        Dict with trace_id, span_id, trace_sampled (empty if no active trace)
    """
    context: Dict[str, Any] = {
        "trace_id": "",
        "span_id": "",
        "trace_sampled": False,
    }

    if OTEL_AVAILABLE:
        try:
            span = trace.get_current_span()
            if span and span.is_recording():
                ctx = span.get_span_context()
                if ctx.is_valid:
                    context["trace_id"] = f"{ctx.trace_id:032x}"
                    context["span_id"] = f"{ctx.span_id:016x}"
                    context["trace_sampled"] = bool(ctx.trace_flags & 0x01)
        except Exception:
            pass

    return context
