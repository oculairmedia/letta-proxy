const directBaseUrl = process.env.LETTA_DIRECT_BASE_URL ?? "http://192.168.50.90:8283";
const proxyBaseUrl = process.env.LETTA_PROXY_BASE_URL ?? "http://192.168.50.90:8289";
const authToken = process.env.LETTA_COMPARE_TOKEN ?? process.env.LETTA_PASSWORD ?? "lettaSecurePass123";
const timeoutMs = Number(process.env.LETTA_COMPARE_TIMEOUT_MS ?? "5000");
const query = process.env.LETTA_COMPARE_QUERY ?? "hello";

const payload = {
  query,
  search_mode: "hybrid",
  roles: ["user", "assistant"],
  limit: 20,
};

async function request(name: string, baseUrl: string) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();

  try {
    const response = await fetch(`${baseUrl}/v1/agents/messages/search`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const text = await response.text();
    return {
      name,
      status: response.status,
      elapsedMs: Date.now() - started,
      bodyPreview: text.slice(0, 1000),
    };
  } catch (error) {
    return {
      name,
      elapsedMs: Date.now() - started,
      error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  const [direct, proxy] = await Promise.all([
    request("direct", directBaseUrl),
    request("proxy", proxyBaseUrl),
  ]);

  console.log(JSON.stringify({
    payload,
    direct,
    proxy,
    identicalOutcome:
      JSON.stringify({ status: (direct as { status?: number }).status, error: (direct as { error?: string }).error }) ===
      JSON.stringify({ status: (proxy as { status?: number }).status, error: (proxy as { error?: string }).error }),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
