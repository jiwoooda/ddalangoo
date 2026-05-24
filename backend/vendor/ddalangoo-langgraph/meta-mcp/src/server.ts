import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { NaverAdapter } from "./adapters/naver.js";
import { CoupangAdapter } from "./adapters/coupang.js";
import type { Product, SearchResult } from "./schemas.js";

const server = new McpServer({
  name: "meta-shopping-mcp",
  version: "1.0.0",
});

server.tool(
  "search_products",
  {
    query: z.string().describe("검색어"),
    platforms: z
      .array(z.enum(["naver", "coupang", "kurly"]))
      .default(["naver", "coupang"])
      .describe("검색할 플랫폼 목록. kurly는 네이버 쇼핑에서 컬리N마트 상품만 검색"),
    min_price: z.number().optional().describe("최소 가격 (원)"),
    max_price: z.number().optional().describe("최대 가격 (원)"),
    limit: z.number().default(5).describe("플랫폼당 최대 결과 개수"),
    sort: z
      .enum(["price_low", "price_high", "recent"])
      .default("price_low")
      .describe("정렬 기준"),
  },
  async (params) => {
    const naver = new NaverAdapter();
    const coupang = new CoupangAdapter();

    const needsNaver = params.platforms.some((p) => p === "naver" || p === "kurly");
    const needsCoupang = params.platforms.includes("coupang");

    // ── 필요한 어댑터만 초기화 (병렬) ──
    const initTasks: Promise<void>[] = [];
    if (needsNaver) initTasks.push(naver.init());
    if (needsCoupang) initTasks.push(coupang.init());
    await Promise.allSettled(initTasks);

    // ── 플랫폼별 검색 (병렬) ──
    const searchTasks = params.platforms.map((platform) => {
      if (platform === "naver") {
        return naver
          .searchProducts(params.query, params.limit, params.sort)
          .catch((e) => {
            console.error("[naver] search failed:", e);
            return [] as Product[];
          });
      } else if (platform === "kurly") {
        return naver
          .searchKurlyNmart(params.query, params.limit, params.sort)
          .catch((e) => {
            console.error("[kurly] search failed:", e);
            return [] as Product[];
          });
      } else {
        return coupang
          .searchProducts(params.query, params.limit)
          .catch((e) => {
            console.error("[coupang] search failed:", e);
            return [] as Product[];
          });
      }
    });

    const settled = await Promise.allSettled(searchTasks);
    let products: Product[] = settled
      .filter((r): r is PromiseFulfilledResult<Product[]> => r.status === "fulfilled")
      .flatMap((r) => r.value);

    // ── 가격 필터 ──
    if (params.min_price !== undefined) {
      products = products.filter((p) => p.price >= params.min_price!);
    }
    if (params.max_price !== undefined) {
      products = products.filter((p) => p.price <= params.max_price!);
    }

    // ── 정렬 ──
    if (params.sort === "price_low") {
      products.sort((a, b) => a.price - b.price);
    } else if (params.sort === "price_high") {
      products.sort((a, b) => b.price - a.price);
    }

    // ── 연결 정리 ──
    await Promise.allSettled([naver.close(), coupang.close()]);

    const result: SearchResult = { total: products.length, products };

    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    };
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[meta-shopping-mcp] server started");
}

main().catch((err) => {
  console.error("[meta-shopping-mcp] fatal error:", err);
  process.exit(1);
});
