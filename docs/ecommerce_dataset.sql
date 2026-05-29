-- ============================================================
--  E-Commerce Dataset  — Cloudera Quickstart VM
--  VM IP : 192.168.47.129
-- ============================================================

CREATE DATABASE IF NOT EXISTS ecommerce;
USE ecommerce;

-- ─────────────────────────────────────────
-- 1. TABLE : customers
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
  customer_id   INT,
  full_name     STRING,
  email         STRING,
  country       STRING,
  city          STRING,
  signup_date   STRING,
  age           INT,
  gender        STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
TBLPROPERTIES ("skip.header.line.count"="1");

-- ─────────────────────────────────────────
-- 2. TABLE : products
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
  product_id    INT,
  product_name  STRING,
  category      STRING,
  sub_category  STRING,
  brand         STRING,
  unit_price    DOUBLE,
  stock_qty     INT
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
TBLPROPERTIES ("skip.header.line.count"="1");

-- ─────────────────────────────────────────
-- 3. TABLE : orders
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
  order_id      INT,
  customer_id   INT,
  order_date    STRING,
  status        STRING,
  payment_method STRING,
  shipping_country STRING,
  total_amount  DOUBLE
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
TBLPROPERTIES ("skip.header.line.count"="1");

-- ─────────────────────────────────────────
-- 4. TABLE : order_items
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
  item_id       INT,
  order_id      INT,
  product_id    INT,
  quantity      INT,
  unit_price    DOUBLE,
  discount_pct  DOUBLE,
  subtotal      DOUBLE
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
TBLPROPERTIES ("skip.header.line.count"="1");

-- ─────────────────────────────────────────
-- 5. TABLE : reviews
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
  review_id     INT,
  order_id      INT,
  product_id    INT,
  customer_id   INT,
  rating        INT,
  review_date   STRING,
  comment       STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
TBLPROPERTIES ("skip.header.line.count"="1");

-- ─────────────────────────────────────────
-- CHARGEMENT DES CSV (après dépôt sur la VM)
-- ─────────────────────────────────────────
LOAD DATA LOCAL INPATH '/home/cloudera/data/customers.csv'   OVERWRITE INTO TABLE customers;
LOAD DATA LOCAL INPATH '/home/cloudera/data/products.csv'    OVERWRITE INTO TABLE products;
LOAD DATA LOCAL INPATH '/home/cloudera/data/orders.csv'      OVERWRITE INTO TABLE orders;
LOAD DATA LOCAL INPATH '/home/cloudera/data/order_items.csv' OVERWRITE INTO TABLE order_items;
LOAD DATA LOCAL INPATH '/home/cloudera/data/reviews.csv'     OVERWRITE INTO TABLE reviews;

-- ─────────────────────────────────────────
-- VÉRIFICATIONS
-- ─────────────────────────────────────────
SELECT 'customers'   AS tbl, COUNT(*) AS nb FROM customers
UNION ALL
SELECT 'products',  COUNT(*) FROM products
UNION ALL
SELECT 'orders',    COUNT(*) FROM orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL
SELECT 'reviews',   COUNT(*) FROM reviews;
