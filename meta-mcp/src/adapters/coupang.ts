import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import type { Product } from "../schemas.js";

const COUPANG_MCP_URL = "https://yuju777-coupang-mcp.hf.space/mcp";
const TIMEOUT_MS = 8000;

export class CoupangAdapter {
  private client: Client | null = null;

  async init(): Promise<void> {
    const transport = new SSEClientTransport(new URL(COUPANG_MCP_URL));

    this.client = new Client(
      { name: "coupang-client", version: "1.0.0" },
      { capabilities: {} }
    );

    await this.client.connect(transport);
  }

  async searchProducts(
    query: string,
    limit: number
  ): Promise<Product[]> {
    if (!this.client) throw new Error("CoupangAdapter not initialized");

    // Actual tool name is search_coupang_products with keyword (not query)
    const result = await Promise.race([
      this.client.callTool({
        name: "search_coupang_products",
        arguments: { keyword: query, limit },
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("coupang timeout")), TIMEOUT_MS)
      ),
    ]);

    return this.normalize(result);
  }

  async close(): Promise<void> {
    await this.client?.close();
    this.client = null;
  }

  private normalize(result: unknown): Product[] {
    try {
      const content = (result as any)?.content;
      const text = Array.isArray(content) ? content[0]?.text : null;
      if (!text || typeof text !== "string") return [];

      // Response is markdown, not JSON.
      // Format per product block:
      //   ### N. Product Name
      //   ![name](image_url)
      //   - **가격**: 12,345원 🚀 로켓배송
      //   - **구매링크**: [name...](url)
      return this.parseMarkdown(text);
    } catch (e) {
      console.error("[coupang] normalize error:", e);
      return [];
    }
  }

  private parseMarkdown(markdown: string): Product[] {
    const products: Product[] = [];

    // Split into per-product blocks by "### N."
    const blocks = markdown.split(/\n(?=###\s+\d+\.)/).filter((b) => b.trim());

    for (const block of blocks) {
      try {
        // Name: "### 1. Product Name"
        const nameMatch = block.match(/###\s+\d+\.\s+(.+)/);
        if (!nameMatch) continue;
        const name = nameMatch[1].trim();

        // Image: "![...](image_url)"
        const imageMatch = block.match(/!\[.*?\]\((https?:\/\/[^)]+)\)/);
        const image_url = imageMatch ? imageMatch[1] : "";

        // Price: "**가격**: 12,345원"
        const priceMatch = block.match(/\*\*가격\*\*[:\s]+([0-9,]+)원/);
        const price = priceMatch
          ? parseInt(priceMatch[1].replace(/,/g, ""), 10)
          : 0;

        // Delivery badges
        const isRocket = block.includes("🚀") || block.includes("로켓배송");
        const isFreeShipping = block.includes("📦") || block.includes("무배송") || block.includes("무료배송");

        // URL: "**구매링크**: [...](url)"
        const urlMatch = block.match(/\*\*구매링크\*\*[:\s]+\[.*?\]\((https?:\/\/[^)]+)\)/);
        const url = urlMatch ? urlMatch[1] : "";

        if (!url) continue;

        products.push({
          platform: "coupang",
          name,
          price,
          price_formatted: `${price.toLocaleString("ko-KR")}원`,
          delivery_info: isRocket ? "로켓배송" : "일반배송",
          url,
          image_url,
        });
      } catch (e) {
        console.error("[coupang] block parse error:", e);
      }
    }

    return products;
  }
}
