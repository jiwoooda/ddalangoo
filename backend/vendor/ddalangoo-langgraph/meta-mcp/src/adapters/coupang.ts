import { createHmac } from "node:crypto";
import type { Product } from "../schemas.js";

const DEFAULT_API_BASE_URL = "https://api-gateway.coupang.com";
const DEFAULT_SEARCH_PATH =
  "/v2/providers/affiliate_open_api/apis/openapi/products/search";
const TIMEOUT_MS = 8_000;

interface CoupangSearchProduct {
  productId?: number | string;
  productImage?: string;
  productName?: string;
  productPrice?: number | string;
  productUrl?: string;
  categoryName?: string;
  isRocket?: boolean;
  isFreeShipping?: boolean;
}

interface CoupangSearchResponse {
  rCode?: string;
  rMessage?: string;
  data?: {
    productData?: CoupangSearchProduct[];
  } | CoupangSearchProduct[];
}

export function coupangSignedDate(now: Date = new Date()): string {
  const year = String(now.getUTCFullYear()).slice(-2);
  const month = String(now.getUTCMonth() + 1).padStart(2, "0");
  const day = String(now.getUTCDate()).padStart(2, "0");
  const hour = String(now.getUTCHours()).padStart(2, "0");
  const minute = String(now.getUTCMinutes()).padStart(2, "0");
  const second = String(now.getUTCSeconds()).padStart(2, "0");
  return `${year}${month}${day}T${hour}${minute}${second}Z`;
}

export function createCoupangAuthorization(
  method: string,
  path: string,
  query: string,
  accessKey: string,
  secretKey: string,
  now: Date = new Date()
): string {
  const signedDate = coupangSignedDate(now);
  const message = `${signedDate}${method.toUpperCase()}${path}${query}`;
  const signature = createHmac("sha256", secretKey)
    .update(message, "utf8")
    .digest("hex");
  return [
    "CEA algorithm=HmacSHA256",
    `access-key=${accessKey}`,
    `signed-date=${signedDate}`,
    `signature=${signature}`,
  ].join(", ");
}

function responseProducts(response: CoupangSearchResponse): CoupangSearchProduct[] {
  if (Array.isArray(response.data)) return response.data;
  return response.data?.productData ?? [];
}

export function normalizeCoupangProducts(
  response: CoupangSearchResponse
): Product[] {
  return responseProducts(response).flatMap((item) => {
    const name = String(item.productName ?? "").trim();
    const url = String(item.productUrl ?? "").trim();
    const price = Number(item.productPrice ?? 0);
    if (!name || !url || !Number.isFinite(price) || price < 0) return [];

    const deliveryInfo = item.isRocket
      ? "로켓배송"
      : item.isFreeShipping
        ? "무료배송"
        : "일반배송";

    return [{
      platform: "coupang" as const,
      name,
      price,
      price_formatted: `${price.toLocaleString("ko-KR")}원`,
      delivery_info: deliveryInfo,
      url,
      image_url: String(item.productImage ?? ""),
      external_product_id:
        item.productId === undefined ? undefined : String(item.productId),
      category_name: item.categoryName,
      is_rocket: item.isRocket ?? false,
      is_free_shipping: item.isFreeShipping ?? false,
    }];
  });
}

export class CoupangAdapter {
  private accessKey = "";
  private secretKey = "";

  async init(): Promise<void> {
    this.accessKey = process.env.COUPANG_ACCESS_KEY?.trim() ?? "";
    this.secretKey = process.env.COUPANG_SECRET_KEY?.trim() ?? "";
    if (!this.accessKey || !this.secretKey) {
      throw new Error(
        "Coupang credentials missing: set COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY"
      );
    }
  }

  async searchProducts(query: string, limit: number): Promise<Product[]> {
    if (!this.accessKey || !this.secretKey) {
      throw new Error("CoupangAdapter not initialized");
    }

    const keyword = query.trim();
    if (!keyword) return [];

    const path = process.env.COUPANG_PRODUCT_SEARCH_PATH?.trim()
      || DEFAULT_SEARCH_PATH;
    const searchParams = new URLSearchParams({
      keyword,
      limit: String(Math.min(10, Math.max(1, Math.trunc(limit)))),
    });
    const encodedQuery = searchParams.toString();
    const authorization = createCoupangAuthorization(
      "GET",
      path,
      encodedQuery,
      this.accessKey,
      this.secretKey
    );
    const baseUrl = process.env.COUPANG_API_BASE_URL?.trim()
      || DEFAULT_API_BASE_URL;

    const response = await fetch(`${baseUrl}${path}?${encodedQuery}`, {
      method: "GET",
      headers: {
        Authorization: authorization,
        Accept: "application/json",
      },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });

    const body = await response.text();
    let payload: CoupangSearchResponse;
    try {
      payload = JSON.parse(body) as CoupangSearchResponse;
    } catch {
      throw new Error(`Coupang API returned non-JSON response (${response.status})`);
    }

    if (!response.ok || (payload.rCode && payload.rCode !== "0")) {
      throw new Error(
        `Coupang API failed (${response.status}, ${payload.rCode ?? "unknown"}): ${payload.rMessage ?? "unknown error"}`
      );
    }

    return normalizeCoupangProducts(payload);
  }

  async close(): Promise<void> {
    // Official API uses stateless HTTP; kept for the shared adapter lifecycle.
  }
}
