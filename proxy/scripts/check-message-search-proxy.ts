import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import { createProxyApp, type ProxyConfig } from "../src/index.js";

const payload = {
  query: "hello",
  search_mode: "hybrid",
  roles: ["user", "assistant"],
  limit: 20,
};

async function main() {
  const captured: {
    method?: string;
    path?: string;
    headers?: Record<string, string | string[] | undefined>;
    body?: string;
  } = {};

  const upstream = createServer(async (req, res) => {
    const chunks: Buffer[] = [];
    for await (const chunk of req) {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }

    captured.method = req.method;
    captured.path = req.url ?? undefined;
    captured.headers = req.headers;
    captured.body = Buffer.concat(chunks).toString("utf8");

    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify([{ embedded_text: "hello", message: { id: "msg-1" } }]));
  });

  upstream.listen(0, "127.0.0.1");
  await once(upstream, "listening");
  const upstreamPort = (upstream.address() as AddressInfo).port;

  const config: ProxyConfig = {
    port: 0,
    lettaApiUrl: `http://127.0.0.1:${upstreamPort}`,
    registryApiUrl: "http://127.0.0.1:3099",
    requirePublicAuth: true,
    publicAuthToken: "public-token",
    upstreamLettaApiKey: "upstream-token",
  };

  const app = createProxyApp(config);
  const response = await app.request("http://proxy.test/v1/agents/messages/search", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer public-token",
    },
    body: JSON.stringify(payload),
  });

  const responseText = await response.text();
  await new Promise<void>((resolve, reject) => {
    upstream.close((error) => (error ? reject(error) : resolve()));
  });

  assert.equal(response.status, 200, `Expected successful proxy response, got ${response.status}: ${responseText}`);
  assert.equal(captured.method, "POST");
  assert.equal(captured.path, "/v1/agents/messages/search");
  assert.equal(captured.headers?.authorization, "Bearer upstream-token");
  assert.equal(captured.headers?.["x-bare-password"], undefined);
  assert.equal(captured.headers?.["content-type"], "application/json");
  assert.deepEqual(JSON.parse(captured.body ?? "{}"), payload);

  console.log(JSON.stringify({
    ok: true,
    forwardedPath: captured.path,
    forwardedAuthorization: captured.headers?.authorization,
    forwardedBody: JSON.parse(captured.body ?? "{}"),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
