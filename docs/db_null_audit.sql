-- 주요 비즈니스 테이블의 컬럼별 NULL 비율 점검 SQL
-- 실행 위치: Railway PostgreSQL Query 또는 psql

WITH target_tables(table_name) AS (
  VALUES
    ('recommendations'),
    ('recommendation_items'),
    ('cart_items'),
    ('orders'),
    ('order_items'),
    ('payments'),
    ('purchase_histories'),
    ('conversation_messages'),
    ('agent_intents'),
    ('agent_events'),
    ('external_api_logs')
),
column_stats_sql AS (
  SELECT
    c.table_name,
    c.column_name,
    format(
      'SELECT %L AS table_name, %L AS column_name, count(*) AS total_rows, count(*) FILTER (WHERE %I IS NULL) AS null_rows, round((count(*) FILTER (WHERE %I IS NULL)::numeric / nullif(count(*), 0)) * 100, 2) AS null_pct FROM %I',
      c.table_name,
      c.column_name,
      c.column_name,
      c.column_name,
      c.table_name
    ) AS sql_text
  FROM information_schema.columns c
  JOIN target_tables t ON t.table_name = c.table_name
  WHERE c.table_schema = 'public'
)
SELECT string_agg(sql_text, E'\nUNION ALL\n') || E'\nORDER BY table_name, null_pct DESC, column_name;' AS null_audit_sql
FROM column_stats_sql;

-- 위 쿼리가 생성한 SQL을 복사해서 실행하면 컬럼별 NULL 비율이 나온다.

-- 운영 DB migration version 확인
SELECT version_num FROM alembic_version;

-- LangGraph checkpointer 테이블은 비즈니스 ORM 관리 대상이 아니라 별도 관리 대상으로 본다.
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'checkpoints',
    'checkpoint_blobs',
    'checkpoint_writes',
    'checkpoint_migrations'
  )
ORDER BY table_name;
