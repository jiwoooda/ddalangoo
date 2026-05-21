export interface Product {
  platform: "naver" | "coupang" | "kurly";
  name: string;
  price: number;
  price_formatted: string;
  delivery_info: string;
  url: string;
  image_url: string;
  shop_name?: string;
}

export interface SearchResult {
  total: number;
  products: Product[];
}
