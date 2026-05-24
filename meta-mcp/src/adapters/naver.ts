import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { Product } from "../schemas.js";

// 네이버 search_shop 허용 값: "sim"(관련도순) | "date"(날짜순)
// 가격순은 API 미지원 → sim으로 fallback, 가격 정렬은 server.ts에서 처리
const SORT_MAP: Record<string, string> = {
  price_low: "sim",
  price_high: "sim",
  recent: "date",
};

// 컬리N마트 결과 검증에 사용하는 키워드
const KURLY_SHOP_KEYWORDS = ["컬리", "마켓컬리", "kurly", "컬리n마트", "컬리 n마트"];

const ALLOWED_TOOLS = ["search_shop"] as const;
type AllowedTool = (typeof ALLOWED_TOOLS)[number];

export class NaverAdapter {
  private client: Client | null = null;

  private async callTool(
    toolName: AllowedTool,
    args: Record<string, unknown>
  ): Promise<unknown> {
    if (!this.client) throw new Error("NaverAdapter not initialized");
    return this.client.callTool({ name: toolName, arguments: args });
  }

  async init(): Promise<void> {
    const transport = new StdioClientTransport({
      command: "npx",
      args: ["-y", "@isnow890/naver-search-mcp"],
      env: {
        ...process.env,
        NAVER_CLIENT_ID: process.env.NAVER_CLIENT_ID ?? "",
        NAVER_CLIENT_SECRET: process.env.NAVER_CLIENT_SECRET ?? "",
      },
    });

    this.client = new Client(
      { name: "naver-client", version: "1.0.0" },
      { capabilities: {} }
    );

    await this.client.connect(transport);
  }

  async searchProducts(
    query: string,
    limit: number,
    sort: string
  ): Promise<Product[]> {

    const result = await this.callTool("search_shop", {
      query,
      display: limit,
      sort: SORT_MAP[sort] ?? "sim",
    });

    return this.normalize(result, "naver");
  }

  /**
   * 컬리N마트 전용 검색.
   * 1) query에 '컬리N마트'를 붙여 검색 (더 많이 가져와서 필터 후 limit 맞춤)
   * 2) 결과에서 컬리 관련 상점/상품만 남김
   */
  async searchKurlyNmart(
    query: string,
    limit: number,
    sort: string
  ): Promise<Product[]> {
    const kurlyQuery = buildKurlyQuery(query);
    const raw = await this.searchProducts(kurlyQuery, limit * 3, sort);
    const filtered = filterKurlyProducts(raw);
    // 필터 후 결과가 없으면 원본 결과를 플랫폼만 바꿔 반환 (fallback)
    const results = filtered.length > 0 ? filtered : raw;
    // Kurly는 샛별배송 고정 (Naver API는 배송 정보를 별도 제공하지 않음)
    return results.slice(0, limit).map((p) => ({
      ...p,
      platform: "kurly" as const,
      delivery_info: "샛별배송 내일 아침 7시 전",
    }));
  }

  async close(): Promise<void> {
    await this.client?.close();
    this.client = null;
  }

  private normalize(result: unknown, platform: Product["platform"]): Product[] {
    try {
      const content = (result as any)?.content;
      const text = Array.isArray(content) ? content[0]?.text : null;
      if (!text) return [];

      const data = JSON.parse(text);
      const items: unknown[] = data.items ?? [];

      return items.map((item: any): Product => ({
        platform,
        name: (item.title ?? "").replace(/<\/?b>/g, ""),
        price: parseInt(item.lprice ?? "0", 10),
        price_formatted: `${parseInt(item.lprice ?? "0", 10).toLocaleString("ko-KR")}원`,
        delivery_info: "일반배송",
        url: item.link ?? "",
        image_url: item.image ?? "",
        shop_name: item.mallName,
      }));
    } catch (e) {
      console.error("[naver] normalize error:", e);
      return [];
    }
  }
}

/**
 * 컬리N마트 검색용 쿼리 생성.
 * 이미 '컬리'가 들어간 경우 중복 추가하지 않는다.
 */
function buildKurlyQuery(query: string): string {
  const lower = query.toLowerCase();
  if (lower.includes("컬리") || lower.includes("kurly")) return query;
  return `${query} 컬리N마트`;
}

/**
 * 네이버 쇼핑 결과에서 컬리N마트 상품만 걸러낸다.
 * mallName 또는 상품명에 컬리 관련 키워드가 포함된 경우만 통과.
 */
function filterKurlyProducts(products: Product[]): Product[] {
  return products.filter((p) => {
    const shopName = (p.shop_name ?? "").toLowerCase();
    const name = p.name.toLowerCase();
    return KURLY_SHOP_KEYWORDS.some(
      (kw) => shopName.includes(kw) || name.includes(kw)
    );
  });
}
