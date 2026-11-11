const ALLOWED_PATHS = [
  /^\/parent\/verify\/[^/]+(?:\/[A-Za-z]+)?$/,
  /^\/parent\/resend\/[^/]+$/,
  /^\/parent\/report\/[^/]+$/,
];

const ALLOWED_METHODS = new Set(["GET", "POST"]);
const MAX_CLOCK_SKEW_MS = 5 * 60 * 1000;
const TUNNEL_KEY = "current_tunnel_destination";
const META_KEY = "current_tunnel_meta";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function isAllowedPath(pathname) {
  return ALLOWED_PATHS.some((re) => re.test(pathname));
}

function validateDestination(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  if (!url.hostname.endsWith(".trycloudflare.com")) return null;
  if (url.port && url.port !== "443") return null;
  if (url.username || url.password) return null;
  if (url.search || url.hash) return null;
  if (url.pathname && url.pathname !== "/") return null;
  return url.origin;
}

async function hmacSha256Hex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
}

async function handleRegister(request, env) {
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const secret = env.TUNNEL_UPDATE_SECRET;
  if (!secret) return json({ error: "registration_not_configured" }, 503);

  const timestampHeader = request.headers.get("X-Tunnel-Timestamp");
  const signatureHeader = request.headers.get("X-Tunnel-Signature");
  if (!timestampHeader || !signatureHeader) return json({ error: "missing_registration_credentials" }, 401);

  const timestamp = Number(timestampHeader);
  if (!Number.isFinite(timestamp)) return json({ error: "invalid_timestamp" }, 400);
  const now = Date.now();
  if (Math.abs(now - timestamp) > MAX_CLOCK_SKEW_MS) return json({ error: "expired_registration" }, 401);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const destination = validateDestination(body && body.destination);
  if (!destination) return json({ error: "invalid_destination" }, 400);

  const message = `${timestamp}.${destination}`;
  const expected = await hmacSha256Hex(secret, message);
  if (!constantTimeEqual(expected, signatureHeader)) return json({ error: "invalid_signature" }, 401);

  const storedRaw = await env.TUNNEL_KV.get(META_KEY);
  if (storedRaw) {
    try {
      const stored = JSON.parse(storedRaw);
      if (typeof stored.updatedAt === "number" && timestamp <= stored.updatedAt) {
        return json({ error: "stale_registration" }, 409);
      }
    } catch {
      // Ignore corrupt metadata and allow replacement.
    }
  }

  await env.TUNNEL_KV.put(TUNNEL_KEY, destination);
  await env.TUNNEL_KV.put(META_KEY, JSON.stringify({ destination, updatedAt: timestamp }));

  return json({ ok: true, registeredAt: timestamp }, 200);
}

async function handleProxy(request, env) {
  if (!ALLOWED_METHODS.has(request.method)) return json({ error: "method_not_allowed" }, 405);

  const url = new URL(request.url);
  if (!isAllowedPath(url.pathname)) return json({ error: "route_not_allowed" }, 403);

  const destination = await env.TUNNEL_KV.get(TUNNEL_KEY);
  if (!destination) return json({ error: "tunnel_not_registered" }, 503);

  const validated = validateDestination(destination);
  if (!validated) return json({ error: "invalid_registered_destination" }, 503);

  const targetUrl = validated + url.pathname + url.search;
  const headers = new Headers();
  for (const [key, value] of request.headers) {
    const lower = key.toLowerCase();
    if (lower === "host" || lower === "origin" || lower === "connection" || lower === "content-length") continue;
    headers.set(key, value);
  }

  let body = null;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.arrayBuffer();
  }

  const upstream = await fetch(targetUrl, {
    method: request.method,
    headers,
    body,
    redirect: "manual",
  });

  if (upstream.status >= 300 && upstream.status < 400) {
    return json({ error: "redirect_not_allowed" }, 502);
  }

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.set("cache-control", "no-store");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/register-tunnel") {
      return handleRegister(request, env);
    }
    return handleProxy(request, env);
  },
};
