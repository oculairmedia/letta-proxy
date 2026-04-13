import { serve } from "@hono/node-server";
import type { Context } from "hono";
import { Hono } from "hono";
import { cors } from "hono/cors";
import dotenv from "dotenv";

// Load environment variables from .env file
dotenv.config();

const app = new Hono();

// Configuration
const PORT = parseInt(process.env.LETTA_PROXY_PORT || "8283", 10);
const LETTA_API_URL = process.env.LETTA_API_URL;
const LETTA_API_KEY = process.env.LETTA_API_KEY;
const REGISTRY_API_URL = process.env.REGISTRY_API_URL || "http://192.168.50.90:3099";
const UPSTREAM_LETTA_API_KEY = process.env.UPSTREAM_LETTA_API_KEY || LETTA_API_KEY;
const REQUIRE_PUBLIC_AUTH = process.env.REQUIRE_PUBLIC_AUTH === "true";
const PUBLIC_AUTH_TOKEN = process.env.PUBLIC_AUTH_TOKEN || process.env.LETTA_PASSWORD;
const WEBHOOK_URL = process.env.WEBHOOK_URL;
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET;

if (!LETTA_API_URL) {
  throw new Error("LETTA_API_URL is not set");
}

app.use(
  "*",
  cors({
    origin: "*",
    allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allowHeaders: ["*"],
    exposeHeaders: ["*"],
    credentials: true,
    maxAge: 86400,
  })
);

/**
 * Sends a webhook notification when a message is sent
 * @param payload The data to send to the webhook
 */
async function sendWebhook(payload: any) {
  if (!WEBHOOK_URL) {
    console.log("Webhook URL not configured, skipping webhook");
    return;
  }

  try {
    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };

    // Add webhook secret if configured
    if (WEBHOOK_SECRET) {
      headers["X-Webhook-Secret"] = WEBHOOK_SECRET;
    }

    const response = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      console.error(`Webhook failed with status ${response.status}: ${await response.text()}`);
    } else {
      console.log(`Webhook sent successfully: ${response.status}`);
    }
  } catch (error) {
    console.error("Error sending webhook:", error);
  }
}

/**
 * Determines if the request is a message-sending request
 * @param path The request path
 * @param method The HTTP method
 * @returns True if this is a message-sending request
 */
function isMessageSendRequest(path: string, method: string): boolean {
  // Check for agent message endpoints (including stream)
  if (path.match(/\/v1\/agents\/[^\/]+\/messages(?:\/stream)?\/?$/) && method === "POST") {
    return true;
  }
  
  // Check for group message endpoints (including stream)
  if (path.match(/\/v1\/groups\/[^\/]+\/messages(?:\/stream)?\/?$/) && method === "POST") {
    return true;
  }
  
  // Check for batch message endpoints
  if (path.match(/\/v1\/messages\/batches\/?$/) && method === "POST") {
    return true;
  }
  
  return false;
}

function hasValidPublicAuth(headers: Headers): boolean {
  if (!REQUIRE_PUBLIC_AUTH) return true;
  if (!PUBLIC_AUTH_TOKEN) {
    console.error("REQUIRE_PUBLIC_AUTH is enabled but PUBLIC_AUTH_TOKEN/LETTA_PASSWORD is not set");
    return false;
  }

  const authorization = headers.get("Authorization");
  const barePassword = headers.get("X-BARE-PASSWORD");

  return (
    authorization === `Bearer ${PUBLIC_AUTH_TOKEN}` ||
    barePassword === `password ${PUBLIC_AUTH_TOKEN}`
  );
}

async function forwardRequest(c: Context) {
  const req = c.req.raw.clone();
  const path = c.req.path;
  const method = req.method;
  const isRegistryRequest = path === "/api/registry" || path.startsWith("/api/registry/");
  
  // Add debug logging
  console.log(`Request received:`, {
    path,
    method,
    origin: req.headers.get('origin'),
    host: req.headers.get('host'),
    url: req.url
  });
  
  // Flag to track if this is a message-sending request
  const isMessageRequest = isMessageSendRequest(path, method);
  console.log(`Is message request: ${isMessageRequest}`, {
    matches: {
      agentMessage: !!path.match(/\/v1\/agents\/[^\/]+\/messages\/?$/),
      groupMessage: !!path.match(/\/v1\/groups\/[^\/]+\/messages\/?$/),
      batchMessage: !!path.match(/\/v1\/messages\/batches\/?$/)
    }
  });

  if (!hasValidPublicAuth(req.headers)) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  
  try {
    const requestUrl = new URL(req.url);
    const targetBaseUrl = isRegistryRequest ? REGISTRY_API_URL : LETTA_API_URL;
    const targetUrl = new URL(requestUrl.pathname + requestUrl.search, targetBaseUrl);
    console.log(`Forwarding to: ${targetUrl.toString()}`);

    // remove headers
    if (req.headers.get("host")) {
      req.headers.delete("host");
    }

    if (req.headers.get("connection")) {
      req.headers.delete("connection");
    }

    if (req.headers.get("content-length")) {
      req.headers.delete("content-length");
    }

    if (!isRegistryRequest && UPSTREAM_LETTA_API_KEY) {
      if (req.headers.has("Authorization")) {
        req.headers.delete("Authorization");
      }
      if (req.headers.has("X-BARE-PASSWORD")) {
        req.headers.delete("X-BARE-PASSWORD");
      }
      req.headers.set("Authorization", `Bearer ${UPSTREAM_LETTA_API_KEY}`);
    }

    let body;
    let bodyText;
    if (req.method !== "GET" && req.method !== "HEAD") {
      const contentType = req.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        // Store a copy of the original request body for the webhook
        const clonedReq = req.clone();
        bodyText = await clonedReq.text();
        
        if (bodyText && bodyText.trim()) {
          body = JSON.parse(bodyText);
          body = JSON.stringify(body);
        }
      } else if (contentType.includes("multipart/form-data")) {
        body = await req.arrayBuffer();
      } else {
        body = await req.arrayBuffer();
      }
    }

    const response = await fetch(targetUrl, {
      method: req.method,
      headers: req.headers,
      body,
      redirect: "follow",
    });
    
    // If this was a message request and it was successful, trigger the webhook
    if (isMessageRequest && response.ok && bodyText) {
      try {
        const responseClone = response.clone();
        let responseBody;

        // Check if this is a streaming response
        const isStreamResponse = path.includes('/stream');
        if (isStreamResponse) {
          // For streaming responses, just use the initial request data
          responseBody = {
            type: "stream_started",
            timestamp: new Date().toISOString()
          };
        } else {
          // For regular responses, parse the JSON as before
          responseBody = await responseClone.json();
        }

        // Extract relevant information for the webhook
        const requestBody = JSON.parse(bodyText);
        
        // Extract the prompt/message content from the request body
        const userMessage = requestBody?.messages?.[0]?.content || '';

        // Send webhook with combined information
        sendWebhook({
          type: isStreamResponse ? "stream_started" : "message_sent",
          timestamp: new Date().toISOString(),
          prompt: userMessage, // Add the required prompt field
          request: {
            path,
            method,
            body: requestBody
          },
          response: responseBody
        });
      } catch (error) {
        console.error("Error processing webhook data:", error);
      }
    }

    return response;
  } catch (error) {
    console.error("Proxy request error:", error);
    return new Response(JSON.stringify({ error: "Proxy error", details: error instanceof Error ? error.message : String(error) }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }
}

app.all("*", async (c: Context) => {
  if (c.req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }
  return forwardRequest(c);
});

serve(
  {
    fetch: app.fetch,
    port: PORT,
  },
  (info) => {
    console.log(`Proxy server is running on http://localhost:${info.port}`);
    console.log(`Proxying requests to: ${LETTA_API_URL}`);
    if (WEBHOOK_URL) {
      console.log(`Webhook notifications enabled: ${WEBHOOK_URL}`);
    }
  }
);
