import { z } from "zod";
import { NaverAdapter } from "./adapters/naver.js";
import { CoupangAdapter } from "./adapters/coupang.js";
import type { Product, SearchResult } from "./schemas.js";

export const SearchProductsParamsSchema = z.object({
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
});

export type SearchProductsParams = z.infer<typeof SearchProductsParamsSchema>;

export async function searchProducts(params: SearchProductsParams): Promise<SearchResult> {
  const naver = new NaverAdapter();
  const coupang = new CoupangAdapter();

  const needsNaver = params.platforms.some((platform) => platform === "naver" || platform === "kurly");
  const needsCoupang = params.platforms.includes("coupang");

  const initTasks: Promise<void>[] = [];
  if (needsNaver) initTasks.push(naver.init());
  if (needsCoupang) initTasks.push(coupang.init());
  await Promise.allSettled(initTasks);

  const searchTasks = params.platforms.map((platform) => {
    if (platform === "naver") {
      return naver.searchProducts(params.query, params.limit, params.sort).catch((error) => {
        console.error("[naver] search failed:", error);
        return [] as Product[];
      });
    }
    if (platform === "kurly") {
      return naver.searchKurlyNmart(params.query, params.limit, params.sort).catch((error) => {
        console.error("[kurly] search failed:", error);
        return [] as Product[];
      });
    }
    return coupang.searchProducts(params.query, params.limit).catch((error) => {
      console.error("[coupang] search failed:", error);
      return [] as Product[];
    });
  });

  const settled = await Promise.allSettled(searchTasks);
  let products: Product[] = settled
    .filter((result): result is PromiseFulfilledResult<Product[]> => result.status === "fulfilled")
    .flatMap((result) => result.value);

  if (params.min_price !== undefined) {
    products = products.filter((product) => product.price >= params.min_price!);
  }
  if (params.max_price !== undefined) {
    products = products.filter((product) => product.price <= params.max_price!);
  }

  if (params.sort === "price_low") {
    products.sort((left, right) => left.price - right.price);
  } else if (params.sort === "price_high") {
    products.sort((left, right) => right.price - left.price);
  }

  await Promise.allSettled([naver.close(), coupang.close()]);

  return { total: products.length, products };
}
