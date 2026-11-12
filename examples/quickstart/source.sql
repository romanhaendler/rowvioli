-- the source: a small shop
CREATE TABLE customers (id int PRIMARY KEY, name text, city text, since date);
INSERT INTO customers
SELECT g, 'customer ' || g, (ARRAY['Berlin', 'Hamburg', 'Munich'])[1 + g % 3], date '2020-01-01' + g
  FROM generate_series(1, 1000) g;

CREATE TABLE orders (id int PRIMARY KEY, customer_id int REFERENCES customers, amount numeric(10, 2),
                     ordered_at timestamptz);
INSERT INTO orders
SELECT g, 1 + g % 1000, g % 500 + 0.99, timestamptz '2024-01-01' + g * interval '1 hour'
  FROM generate_series(1, 10000) g;
