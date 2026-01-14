#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Distributed tracing infrastructure for FreeCiv3D

Uses OpenTelemetry with GCP Cloud Trace exporter for end-to-end request tracing.
Trace context is propagated in-band via WebSocket message payload since WebSocket
doesn't support HTTP headers after the initial handshake.

Usage:
    from tracing import init_tracing, extract_trace_context, create_child_span, inject_trace_context

    # At startup
    init_tracing("llm-gateway", enable_cloud_trace=True)

    # In message handler
    parent_ctx = extract_trace_context(message)
    with create_child_span("handle_state_query", parent_ctx, {"agent_id": agent_id}) as span:
        # ... handle message ...
        response["trace_context"] = inject_trace_context(span)
"""

import os
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Global tracer instance
_tracer = None
_initialized = False

# Try to import OpenTelemetry - gracefully degrade if not available
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_NAMESPACE
    from opentelemetry.trace import SpanContext, TraceFlags, SpanKind, Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    OTEL_AVAILABLE = True

    # Try to import Cloud Trace exporter
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        CLOUD_TRACE_AVAILABLE = True
    except ImportError:
        CLOUD_TRACE_AVAILABLE = False
        logger.warning("Cloud Trace exporter not available - install opentelemetry-exporter-gcp-trace")

    # Try to import OTLP exporter (for telemetry.googleapis.com endpoint)
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        OTLP_AVAILABLE = True
    except ImportError:
        OTLP_AVAILABLE = False
        logger.debug("OTLP exporter not available - install opentelemetry-exporter-otlp")

except ImportError:
    OTEL_AVAILABLE = False
    CLOUD_TRACE_AVAILABLE = False
    OTLP_AVAILABLE = False
    logger.warning("OpenTelemetry not available - tracing disabled. Install opentelemetry-sdk")


def init_tracing(
    service_name: str,
    enable_cloud_trace: bool = True,
    service_namespace: str = "freeciv3d"
) -> Optional[Any]:
    """
    Initialize OpenTelemetry tracing with optional Cloud Trace exporter.

    Args:
        service_name: Name of the service (e.g., "llm-gateway", "freeciv-proxy")
        enable_cloud_trace: Whether to export to GCP Cloud Trace (disable for local dev)
        service_namespace: Namespace for the service (default: "freeciv3d")

    Returns:
        Configured Tracer instance, or None if OpenTelemetry not available
    """
    global _tracer, _initialized

    if _initialized:
        logger.debug(f"Tracing already initialized for {service_name}")
        return _tracer

    if not OTEL_AVAILABLE:
        logger.warning(f"OpenTelemetry not available - tracing disabled for {service_name}")
        _initialized = True
        return None

    # Create resource with service metadata
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_NAMESPACE: service_namespace,
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Check for OTLP endpoint (matches agent-clash configuration)
    otlp_endpoint = os.getenv("OTLP_ENDPOINT")

    if enable_cloud_trace and otlp_endpoint and OTLP_AVAILABLE:
        # Prefer OTLP exporter if endpoint is configured (consistent with agent-clash)
        try:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=False)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OTLP exporter enabled for {service_name} -> {otlp_endpoint}")
        except Exception as e:
            logger.warning(f"Failed to initialize OTLP exporter: {e}")
    elif enable_cloud_trace and CLOUD_TRACE_AVAILABLE:
        # Fall back to GCP-specific Cloud Trace exporter
        try:
            exporter = CloudTraceSpanExporter()
            # Use BatchSpanProcessor for production (batches spans for efficiency)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"Cloud Trace exporter enabled for {service_name}")
        except Exception as e:
            logger.warning(f"Failed to initialize Cloud Trace exporter: {e}")
    elif enable_cloud_trace:
        logger.warning(f"Cloud Trace requested but no exporter available for {service_name}")
    else:
        logger.info(f"Cloud Trace export disabled for {service_name} (local development mode)")

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Get tracer instance
    _tracer = trace.get_tracer(service_name, "1.0.0")
    _initialized = True

    logger.info(f"Tracing initialized for {service_name} (cloud_trace={enable_cloud_trace and CLOUD_TRACE_AVAILABLE})")
    return _tracer


def get_tracer() -> Optional[Any]:
    """
    Get the global tracer instance.

    Returns:
        Tracer instance, or None if not initialized or OpenTelemetry not available
    """
    if not _initialized:
        logger.warning("Tracing not initialized - call init_tracing() first")
    return _tracer


def extract_trace_context(message: Dict[str, Any]) -> Optional[Any]:
    """
    Extract trace context from WebSocket message payload.

    The trace_context field in the message should contain W3C Trace Context fields:
    - trace_id: 32 hex characters (128-bit)
    - span_id: 16 hex characters (64-bit)
    - trace_flags: 2 hex characters ("01" = sampled)

    Args:
        message: WebSocket message containing optional trace_context field

    Returns:
        SpanContext if trace_context is present and valid, None otherwise
    """
    if not OTEL_AVAILABLE:
        return None

    trace_ctx = message.get("trace_context")
    if not trace_ctx or not isinstance(trace_ctx, dict):
        return None

    try:
        # Parse W3C Trace Context fields
        trace_id_str = trace_ctx.get("trace_id", "0")
        span_id_str = trace_ctx.get("span_id", "0")
        trace_flags_str = trace_ctx.get("trace_flags", "00")

        # Validate field lengths (W3C spec: trace_id=32 hex chars, span_id=16 hex chars)
        if len(trace_id_str) != 32 or len(span_id_str) != 16:
            logger.debug(f"Invalid trace context: incorrect field lengths (trace_id={len(trace_id_str)}, span_id={len(span_id_str)})")
            return None

        # Convert hex strings to integers
        trace_id = int(trace_id_str, 16)
        span_id = int(span_id_str, 16)
        trace_flags = int(trace_flags_str, 16)

        # Validate - trace_id and span_id must be non-zero
        if trace_id == 0 or span_id == 0:
            logger.debug("Invalid trace context: zero trace_id or span_id")
            return None

        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=TraceFlags(trace_flags)
        )

    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to parse trace context: {e}")
        return None


def inject_trace_context(span: Any) -> Dict[str, str]:
    """
    Create trace_context dict for WebSocket message injection.

    Args:
        span: Current span to extract context from

    Returns:
        Dictionary with trace_id, span_id, trace_flags for message injection
    """
    if not OTEL_AVAILABLE or span is None:
        return {}

    try:
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return {}

        return {
            "trace_id": format(ctx.trace_id, '032x'),
            "span_id": format(ctx.span_id, '016x'),
            "trace_flags": format(ctx.trace_flags, '02x')
        }
    except Exception as e:
        logger.debug(f"Failed to inject trace context: {e}")
        return {}


@contextmanager
def create_child_span(
    name: str,
    parent_context: Optional[Any] = None,
    attributes: Optional[Dict[str, Any]] = None,
    kind: Optional[Any] = None
):
    """
    Create a child span with optional parent context.

    Usage:
        with create_child_span("handle_message", parent_ctx, {"agent_id": "abc"}) as span:
            # ... do work ...
            span.set_attribute("result", "success")

    Args:
        name: Span name (e.g., "handle_state_query", "proxy_forward_message")
        parent_context: Parent SpanContext from incoming message (optional)
        attributes: Initial span attributes (optional)
        kind: SpanKind (default: INTERNAL)

    Yields:
        Span instance (or NoOpSpan if tracing disabled)
    """
    if not OTEL_AVAILABLE or _tracer is None:
        # Return a no-op context manager with a mock span
        yield _NoOpSpan()
        return

    # Default to INTERNAL kind
    if kind is None:
        kind = SpanKind.INTERNAL

    # Build context from parent if provided
    ctx = None
    if parent_context is not None:
        try:
            from opentelemetry.trace import NonRecordingSpan, set_span_in_context
            ctx = set_span_in_context(NonRecordingSpan(parent_context))
        except Exception as e:
            logger.debug(f"Failed to set parent context: {e}")

    # Create and start span
    span = _tracer.start_span(name, context=ctx, kind=kind, attributes=attributes)

    try:
        yield span
    except Exception as e:
        # Record exception on span
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        raise
    finally:
        span.end()


class _NoOpSpan:
    """No-op span for when tracing is disabled"""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        pass

    def get_span_context(self) -> None:
        return None

    def is_recording(self) -> bool:
        return False


def get_current_span() -> Optional[Any]:
    """
    Get the current active span from context.

    Returns:
        Current span if available, None otherwise
    """
    if not OTEL_AVAILABLE:
        return None

    try:
        return trace.get_current_span()
    except Exception:
        return None


def format_trace_id_for_logging(span: Any = None) -> Optional[str]:
    """
    Format trace ID for Cloud Logging integration.

    Cloud Logging uses the format: projects/{project}/traces/{trace_id}

    Args:
        span: Span to extract trace ID from (uses current span if None)

    Returns:
        Formatted trace ID string for logging, or None if not available
    """
    if not OTEL_AVAILABLE:
        return None

    try:
        if span is None:
            span = trace.get_current_span()

        if span is None:
            return None

        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None

        # Get project ID from environment
        project_id = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "unknown"))

        return f"projects/{project_id}/traces/{ctx.trace_id:032x}"
    except Exception:
        return None
