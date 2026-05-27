/**
 * Cloudflare Worker — Render Keep-Alive Pinger
 * Pings your Render app every 10 minutes so it never sleeps.
 *
 * Deploy steps:
 * 1. Go to https://workers.cloudflare.com → Create Worker
 * 2. Paste this entire file
 * 3. Set RENDER_URL in Settings → Variables:
 *    RENDER_URL = https://your-app-name.onrender.com
 * 4. Go to Triggers → Add Cron Trigger: */10 * * * *
 */

export default {
  // Cron trigger — runs every 10 minutes
  async scheduled(event, env, ctx) {
    await pingRender(env);
  },

  // HTTP trigger — lets you manually ping by visiting the worker URL
  async fetch(request, env, ctx) {
    const result = await pingRender(env);
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

async function pingRender(env) {
  const renderUrl = env.RENDER_URL || "https://your-app-name.onrender.com";
  const pingUrl = `${renderUrl}/webhook`;

  const startTime = Date.now();

  try {
    const response = await fetch(pingUrl, {
      method: "GET",
      headers: { "User-Agent": "Cloudflare-KeepAlive-Worker/1.0" },
      // 20 second timeout
      signal: AbortSignal.timeout(20000),
    });

    const elapsed = Date.now() - startTime;

    console.log(`Ping OK: ${response.status} in ${elapsed}ms`);

    return {
      success: true,
      status: response.status,
      url: pingUrl,
      response_time_ms: elapsed,
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    const elapsed = Date.now() - startTime;
    console.error(`Ping FAILED: ${error.message}`);

    return {
      success: false,
      error: error.message,
      url: pingUrl,
      response_time_ms: elapsed,
      timestamp: new Date().toISOString(),
    };
  }
}
