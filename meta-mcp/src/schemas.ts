export interface Product {
  platform: "naver" | "coupang" | "kurly";
  name: string;
  price: number;
  price_formatted: string;
  delivery_info: string;
  url: string;
  image_url: string;
  shop_name?: string;
  external_product_id?: string;
  category_name?: string;
  brand?: string;
  rating?: number;
  review_count?: number;
  is_sold_out?: boolean;
  is_rocket?: boolean;
  is_free_shipping?: boolean;
  impression_url?: string;
}

export interface SearchResult {
  total: number;
  products: Product[];
}
