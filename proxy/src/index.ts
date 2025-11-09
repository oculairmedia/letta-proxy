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

async function forwardRequest(c: Context) {
  const req = c.req.raw.clone();
  const path = c.req.path;
  const method = req.method;
  
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
  
  try {
    const targetUrl = new URL(path, LETTA_API_URL);

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

    if (req.headers.has("Authorization")) {
      req.headers.delete("Authorization");
    }

    // Ensure API key is set if LETTA_API_KEY is present
    if (LETTA_API_KEY) {
      req.headers.set("Authorization", `Bearer ${LETTA_API_KEY}`);
    }

    let body;
    let bodyText;
    if (req.method !== "GET" && req.method !== "HEAD") {
      const contentType = req.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        // Store a copy of the original request body for the webhook
        const clonedReq = req.clone();
        bodyText = await clonedReq.text();
        
        body = JSON.parse(bodyText);
        body = JSON.stringify(body);
      } else if (contentType.includes("multipart/form-data")) {
        body = await req.formData();
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
