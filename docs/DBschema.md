// 딸랑구 DB Schema v0.5
Table users {
  id bigint [pk, increment]
  name varchar [not null]
  phone_number varchar
  age_group varchar
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table user_naver_accounts {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  naver_user_id varchar
  access_token_encrypted text
  refresh_token_encrypted text
  token_expires_at datetime
  connected_at datetime [not null]
  disconnected_at datetime
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table user_addresses {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  address_label varchar
  recipient_name varchar [not null]
  recipient_phone varchar [not null]
  zip_code varchar
  address_line1 text [not null]
  address_line2 text
  delivery_request text
  is_default boolean [not null]
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table crawled_product_snapshots {
  id bigint [pk, increment]
  platform varchar [not null]
  external_product_id varchar
  external_product_url text
  crawl_keyword varchar
  crawl_source varchar
  raw_product_name text [not null]
  raw_brand varchar
  raw_category varchar
  raw_price varchar
  raw_original_price varchar
  raw_discount_rate varchar
  raw_delivery_info varchar
  raw_rating varchar
  raw_review_count varchar
  raw_image_url text
  raw_is_sold_out varchar
  raw_payload json
  normalized_name varchar
  normalized_brand varchar
  normalized_category varchar
  normalized_sub_category varchar
  normalized_volume varchar
  normalized_price int
  normalized_original_price int
  normalized_discount_rate float
  normalized_delivery_type varchar
  normalized_rating float
  normalized_review_count int
  normalized_is_available boolean
  product_id bigint [ref: > products.id]
  normalization_status varchar
  normalization_error text
  crawled_at datetime [not null]
  created_at datetime [not null]
}
Table products {
  id bigint [pk, increment]
  name varchar [not null]
  normalized_name varchar
  brand varchar
  category varchar [not null]
  sub_category varchar
  description text
  volume varchar
  unit varchar
  image_url text
  current_price int
  original_price int
  discount_rate float
  rating float
  review_count int
  is_available boolean [not null]
  delivery_type varchar
  current_delivery_info varchar
  last_crawled_snapshot_id bigint [ref: > crawled_product_snapshots.id]
  last_crawled_at datetime
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table product_options {
  id bigint [pk, increment]
  product_id bigint [not null, ref: > products.id]
  option_name varchar
  option_value varchar
  volume varchar
  additional_price int
  stock_quantity int
  is_available boolean [not null]
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table external_product_mappings {
  id bigint [pk, increment]
  product_id bigint [not null, ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  platform varchar [not null]
  external_product_id varchar
  external_option_id varchar
  external_product_url text
  external_product_url_hash varchar
  mall_name varchar
  seller_name varchar
  metadata json
  last_synced_at datetime
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table purchase_histories {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  product_id bigint [ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  conversation_id bigint [ref: > conversations.id]
  order_id bigint [ref: > orders.id]
  payment_id bigint [ref: > payments.id]
  external_order_id varchar
  external_product_order_id varchar
  platform varchar
  keyword varchar
  product_name_snapshot varchar [not null]
  option_snapshot varchar
  brand_snapshot varchar
  category_snapshot varchar
  price_at_purchase int [not null]
  product_url_snapshot text
  selected_options json
  quantity int [not null]
  total_price int [not null]
  purchased_at datetime [not null]
  satisfaction int
  memo text
  created_at datetime [not null]
}
Table conversations {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  langgraph_thread_id varchar
  status varchar [not null]
  stage varchar [not null]
  keyword varchar
  summary text
  summary_message_count int
  started_at datetime [not null]
  ended_at datetime
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table conversation_messages {
  id bigint [pk, increment]
  conversation_id bigint [not null, ref: > conversations.id]
  role varchar [not null]
  content text [not null]
  created_at datetime [not null]
}
Table agent_intents {
  id bigint [pk, increment]
  conversation_id bigint [not null, ref: > conversations.id]
  user_id bigint [not null, ref: > users.id]
  raw_user_request text [not null]
  intent varchar [not null]
  intent_type varchar [not null]
  stage varchar
  pending_action_type varchar
  target_category varchar
  target_product_name varchar
  extracted_keywords text
  confidence float
  needs_clarification boolean
  clarification_reason text
  created_at datetime [not null]
}
Table recommendations {
  id bigint [pk, increment]
  conversation_id bigint [not null, ref: > conversations.id]
  user_id bigint [not null, ref: > users.id]
  intent_id bigint [ref: > agent_intents.id]
  recommendation_type varchar [not null]
  keyword varchar
  summary text
  status varchar [not null]
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table recommendation_items {
  id bigint [pk, increment]
  recommendation_id bigint [not null, ref: > recommendations.id]
  product_id bigint [ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  matched_purchase_history_id bigint [ref: > purchase_histories.id]
  rank int [not null]
  score float
  score_detail json
  reason text
  product_name_snapshot varchar [not null]
  brand_snapshot varchar
  category_snapshot varchar
  option_snapshot varchar
  platform varchar
  price_at_recommendation int
  original_price_snapshot int
  discount_rate_snapshot float
  delivery_fee int
  delivery_info_snapshot varchar
  rating_snapshot float
  review_count_snapshot int
  product_url_snapshot text
  image_url_snapshot text
  is_presented boolean [not null]
  presented_at datetime
  is_selected boolean [not null]
  is_orderable boolean [not null]
  order_block_reason varchar
  created_at datetime [not null]
}
Table agent_events {
  id bigint [pk, increment]
  conversation_id bigint [not null, ref: > conversations.id]
  agent_name varchar [not null]
  event_type varchar [not null]
  input_summary text
  output_summary text
  error_message text
  latency_ms int
  created_at datetime [not null]
}
Table carts {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  conversation_id bigint [ref: > conversations.id]
  status varchar [not null]
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table cart_items {
  id bigint [pk, increment]
  cart_id bigint [not null, ref: > carts.id]
  product_id bigint [not null, ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  recommendation_item_id bigint [ref: > recommendation_items.id]
  quantity int [not null]
  unit_price_snapshot int [not null]
  product_name_snapshot varchar [not null]
  option_snapshot varchar
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table checkout_sessions {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  conversation_id bigint [ref: > conversations.id]
  cart_id bigint [not null, ref: > carts.id]
  delivery_address_snapshot text
  address_confirmed boolean [not null]
  total_product_price int
  delivery_fee int
  total_expected_amount int
  status varchar [not null]
  idempotency_key varchar
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table orders {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  conversation_id bigint [ref: > conversations.id]
  cart_id bigint [ref: > carts.id]
  checkout_session_id bigint [ref: > checkout_sessions.id]
  recommendation_id bigint [ref: > recommendations.id]
  shipping_address_id bigint [ref: > user_addresses.id]
  recipient_name_snapshot varchar
  recipient_phone_snapshot varchar
  shipping_address_snapshot text
  delivery_request_snapshot text
  platform varchar [not null]
  order_type varchar [not null]
  status varchar [not null]
  total_product_price int [not null]
  delivery_fee int
  total_payment_amount int [not null]
  confirmed_by_user boolean [not null]
  confirmed_at datetime
  ordered_at datetime
  idempotency_key varchar
  failed_reason text
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table order_items {
  id bigint [pk, increment]
  order_id bigint [not null, ref: > orders.id]
  product_id bigint [not null, ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  recommendation_item_id bigint [ref: > recommendation_items.id]
  product_name_snapshot varchar [not null]
  option_snapshot varchar
  product_url_snapshot text
  selected_options json
  unit_price int [not null]
  total_price int [not null]
  quantity int [not null]
  external_product_order_id varchar
  created_at datetime [not null]
}
Table payments {
  id bigint [pk, increment]
  order_id bigint [not null, ref: > orders.id]
  payment_provider varchar [not null]
  payment_method varchar
  payment_status varchar [not null]
  payment_amount int [not null]
  external_payment_id varchar
  approval_number varchar
  payment_url text
  paid_at datetime
  cancelled_at datetime
  failure_reason text
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table naver_order_mappings {
  id bigint [pk, increment]
  order_id bigint [not null, ref: > orders.id]
  payment_id bigint [ref: > payments.id]
  naver_order_id varchar
  naver_product_order_id varchar
  naver_payment_id varchar
  naver_pay_order_key varchar
  naver_status varchar
  last_synced_at datetime
  created_at datetime [not null]
  updated_at datetime [not null]
}
Table user_preferences {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  keyword varchar  // NULL = 전체 구매이력 기반 일반 선호도 / 값 있으면 키워드별 선호도
  preferred_brands json  // [{brand, count}, ...]
  price_range json  // {avg, min, max}
  repurchase_patterns json  // [product_name, ...]
  preferred_platform varchar
  summary text
  computed_at datetime [not null]
  created_at datetime [not null]
  updated_at datetime [not null]
}
// unique index: (user_id) WHERE keyword IS NULL  → 일반 선호도 1건/유저
// unique index: (user_id, keyword) WHERE keyword IS NOT NULL → 키워드별 1건
Table external_api_logs {
  id bigint [pk, increment]
  user_id bigint [ref: > users.id]
  conversation_id bigint [ref: > conversations.id]
  provider varchar [not null]
  api_name varchar [not null]
  request_summary text
  response_summary text
  status_code int
  success boolean [not null]
  error_message text
  latency_ms int
  created_at datetime [not null]
}