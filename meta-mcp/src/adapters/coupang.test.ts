import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";
import {
  coupangSignedDate,
  createCoupangAuthorization,
  normalizeCoupangProducts,
} from "./coupang.js";

test("creates Coupang HMAC from encoded path and query", () => {
  const now = new Date("2026-08-13T01:02:03Z");
  const path = "/v2/providers/affiliate_open_api/apis/openapi/products/search";
  const query = "keyword=%EA%B3%84%EB%9E%80&limit=5";
  const expected = createHmac("sha256", "secret")
    .update(`260813T010203ZGET${path}${query}`, "utf8")
    .digest("hex");

  assert.equal(coupangSignedDate(now), "260813T010203Z");
  assert.equal(
    createCoupangAuthorization("GET", path, query, "access", "secret", now),
    `CEA algorithm=HmacSHA256, access-key=access, signed-date=260813T010203Z, signature=${expected}`
  );
});

test("normalizes official product-search response", () => {
  const products = normalizeCoupangProducts({
    rCode: "0",
    data: {
      productData: [{
        productId: 123,
        productName: "신선한 계란 30구",
        productPrice: 8990,
        productImage: "https://image.example/egg.jpg",
        productUrl: "https://link.coupang.com/a/example",
        categoryName: "계란",
        isRocket: true,
        isFreeShipping: true,
      }],
    },
  });

  assert.deepEqual(products, [{
    platform: "coupang",
    name: "신선한 계란 30구",
    price: 8990,
    price_formatted: "8,990원",
    delivery_info: "로켓배송",
    url: "https://link.coupang.com/a/example",
    image_url: "https://image.example/egg.jpg",
    external_product_id: "123",
    category_name: "계란",
    is_rocket: true,
    is_free_shipping: true,
  }]);
});

test("drops malformed candidates that cannot be recommended or automated", () => {
  const products = normalizeCoupangProducts({
    data: { productData: [{ productName: "URL 없는 상품", productPrice: 1000 }] },
  });
  assert.deepEqual(products, []);
});
