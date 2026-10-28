// Loaded only while the server exports traces. Spans go to the server's own
// /api/v1/telemetry/traces, which forwards them to the collector: the browser never needs the
// collector's address or token, and the server takes out ids and query strings on the way.
import { context, propagation, type Span, SpanStatusCode, trace } from '@opentelemetry/api';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { DocumentLoadInstrumentation } from '@opentelemetry/instrumentation-document-load';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { BatchSpanProcessor, StackContextManager, TracerProvider } from '@opentelemetry/sdk-trace';
import { template } from './tracing';

const TELEMETRY = /\/api\/v1\/telemetry/;
const tracer = trace.getTracer('immich-memories-web');
// The action or page change in flight. Without zone.js the context does not survive an
// `await`, so requests made while one is open are parented to it explicitly.
let open: Span | null = null;
// Requests still running under each open span: a page change ends when its page's own loads
// do, not when the router is done (a page mounts, then asks for its data).
const pending = new Map<Span, number>();
const settled = new Map<Span, () => void>();
// A page that polls forever must not hold its page-change span open forever.
const SETTLE_LIMIT_MS = 10_000;

function finished(span: Span): void {
  const left = (pending.get(span) ?? 1) - 1;
  pending.set(span, left);
  if (left <= 0) settled.get(span)?.();
}

export function start(): void {
  const provider = new TracerProvider({
    resource: resourceFromAttributes({ 'service.name': 'immich-memories-web' }),
    spanProcessors: [
      new BatchSpanProcessor({
        exporter: new OTLPTraceExporter({ url: new URL('/api/v1/telemetry/traces', location.origin).href }),
      }),
    ],
  });
  trace.setGlobalTracerProvider(provider);
  context.setGlobalContextManager(new StackContextManager().enable());
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  registerInstrumentations({
    tracerProvider: provider,
    instrumentations: [
      new DocumentLoadInstrumentation(),
      // Same-origin requests carry traceparent, so the server's route span joins this trace.
      new FetchInstrumentation({
        ignoreUrls: [TELEMETRY],
        clearTimingResources: true,
        applyCustomAttributesOnSpan: (span) => {
          // The SDK span already holds the request's URL and method; the API type hides them.
          const recorded = (span as unknown as { attributes?: Record<string, unknown> }).attributes ?? {};
          const url = String(recorded['url.full'] ?? recorded['http.url'] ?? '');
          const method = String(recorded['http.request.method'] ?? recorded['http.method'] ?? 'GET');
          if (url) span.updateName(`${method} ${template(new URL(url, location.origin).pathname)}`);
        },
      }),
    ],
  });
  // Outermost, so the instrumented fetch it calls starts its span under the open action.
  const instrumented = window.fetch;
  window.fetch = (input, init) => {
    const parent = open;
    if (!parent) return instrumented(input, init);
    pending.set(parent, (pending.get(parent) ?? 0) + 1);
    return context.with(trace.setSpan(context.active(), parent), () => instrumented(input, init)).finally(() => finished(parent));
  };
  // A closing tab still sends what it has.
  addEventListener('pagehide', () => void provider.forceFlush());
}

export function action<T>(name: string, run: () => Promise<T>): Promise<T> {
  const span = tracer.startSpan(`ui ${name}`);
  const previous = open;
  open = span;
  const close = () => {
    if (open === span) open = previous;
    span.end();
  };
  return run().then(
    (value) => {
      close();
      return value;
    },
    (error: unknown) => {
      span.setStatus({ code: SpanStatusCode.ERROR, message: error instanceof Error ? error.name : 'Error' });
      close();
      throw error;
    },
  );
}

export function navigating(from: string | null, to: string | null): () => void {
  const span = tracer.startSpan(`route ${to ?? 'unknown'}`, { attributes: { 'route.from': from ?? '', 'route.to': to ?? '' } });
  open = span;
  return () => {
    // The router is done; the page it mounted is now asking for its data. Close once that
    // settles, or at the limit.
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      if (open === span) open = null;
      pending.delete(span);
      settled.delete(span);
      span.end();
    };
    settled.set(span, close);
    setTimeout(close, SETTLE_LIMIT_MS);
    // Give the mounted page a tick to start its requests before deciding nothing is pending.
    setTimeout(() => {
      if ((pending.get(span) ?? 0) <= 0) close();
    }, 0);
  };
}
