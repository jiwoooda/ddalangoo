import http from "node:http";
import { URL } from "node:url";
import { SearchProductsParamsSchema, searchProducts } from "./search.js";

const PORT = Number.parseInt(process.env.PORT ?? "8080", 10);

function sendJson(response: http.ServerResponse, statusCode: number, body: unknown): void {
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function writeSse(response: http.ServerResponse, event: string, data: unknown): void {
  response.write(`event: ${event}\n`);
  response.write(`data: ${JSON.stringify(data)}\n\n`);
}

function parsePlatforms(raw: string | null): Array<"naver" | "coupang" | "kurly"> {
  const platforms = (raw ?? "naver,coupang")
    .split(",")
    .map((value) => value.trim())
    .filter((value): value is "naver" | "coupang" | "kurly" =>
      value === "naver" || value === "coupang" || value === "kurly"
    );
  return platforms.length > 0 ? platforms : ["naver", "coupang"];
}

function parseNumber(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseSearchParams(requestUrl: URL): unknown {
  return {
    query: requestUrl.searchParams.get("query") ?? "",
    platforms: parsePlatforms(requestUrl.searchParams.get("platforms")),
    min_price: parseNumber(requestUrl.searchParams.get("min_price")),
    max_price: parseNumber(requestUrl.searchParams.get("max_price")),
    limit: parseNumber(requestUrl.searchParams.get("limit")) ?? 5,
    sort: requestUrl.searchParams.get("sort") ?? "price_low",
  };
}

const server = http.createServer(async (request, response) => {
  const requestUrl = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);

  if (request.method === "GET" && requestUrl.pathname === "/health") {
    sendJson(response, 200, { ok: true, service: "meta-shopping-mcp" });
    return;
  }

  if (request.method === "GET" && requestUrl.pathname === "/sse") {
    response.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });

    try {
      const params = SearchProductsParamsSchema.parse(parseSearchParams(requestUrl));
      writeSse(response, "progress", {
        status: "running",
        step: "searching",
        query: params.query,
        platforms: params.platforms,
      });

      const result = await searchProducts(params);
      writeSse(response, "search_result", result);
      writeSse(response, "done", { status: "completed" });
    } catch (error) {
      writeSse(response, "error", {
        status: "failed",
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      response.end();
    }
    return;
  }

  sendJson(response, 404, { error: "not_found" });
});

server.listen(PORT, "0.0.0.0", () => {
  console.error(`[meta-shopping-mcp] HTTP/SSE server listening on ${PORT}`);
});
