-- Mitchell Bike Co. schema (SQLite)
-- Money is stored as integer cents.

-- Reference: interface standards --------------------------------------------

CREATE TABLE standards (
  id    INTEGER PRIMARY KEY,
  kind  TEXT NOT NULL,   -- freehub, bb_shell, rear_axle, front_axle,
                         -- brake_mount, rotor_mount, drivetrain_speed,
                         -- chain_type, seatpost_diameter, wheel_size
  name  TEXT NOT NULL,
  UNIQUE (kind, name)
);

-- A requirement for `required_id` is also met by `satisfied_by_id`.
CREATE TABLE standard_compat (
  required_id      INTEGER NOT NULL REFERENCES standards(id),
  satisfied_by_id  INTEGER NOT NULL REFERENCES standards(id),
  note             TEXT,          -- e.g. "needs 1.85 mm spacer"
  PRIMARY KEY (required_id, satisfied_by_id)
);

-- Catalog ---------------------------------------------------------------------

CREATE TABLE parts (
  id             INTEGER PRIMARY KEY,
  sku            TEXT NOT NULL UNIQUE,
  name           TEXT NOT NULL,
  brand          TEXT NOT NULL,
  category       TEXT NOT NULL,   -- cassette, chain, brake_pad, rotor, tire, ...
  price_cents    INTEGER NOT NULL,
  stock_qty      INTEGER NOT NULL DEFAULT 0,
  reorder_point  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE part_requirements (
  part_id      INTEGER NOT NULL REFERENCES parts(id),
  standard_id  INTEGER NOT NULL REFERENCES standards(id),
  PRIMARY KEY (part_id, standard_id)
);

CREATE TABLE bike_models (
  id           INTEGER PRIMARY KEY,
  brand        TEXT NOT NULL,
  model        TEXT NOT NULL,
  year         INTEGER NOT NULL,
  category     TEXT NOT NULL,     -- road, gravel
  price_cents  INTEGER NOT NULL,
  stock_qty    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE services (           -- labor catalog
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL,
  minutes      INTEGER NOT NULL,
  price_cents  INTEGER NOT NULL
);

-- Customers and their garage --------------------------------------------------

CREATE TABLE customers (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL,
  email  TEXT NOT NULL UNIQUE
);

CREATE TABLE customer_bikes (
  id             INTEGER PRIMARY KEY,
  customer_id    INTEGER NOT NULL REFERENCES customers(id),
  bike_model_id  INTEGER REFERENCES bike_models(id),  -- null if bought elsewhere
  nickname       TEXT,
  notes          TEXT
);

-- What a specific customer bike actually has, including upgrades.
CREATE TABLE bike_standards (
  customer_bike_id  INTEGER NOT NULL REFERENCES customer_bikes(id),
  standard_id       INTEGER NOT NULL REFERENCES standards(id),
  PRIMARY KEY (customer_bike_id, standard_id)
);

-- Service ---------------------------------------------------------------------

CREATE TABLE work_orders (
  id                INTEGER PRIMARY KEY,
  customer_id       INTEGER NOT NULL REFERENCES customers(id),
  customer_bike_id  INTEGER NOT NULL REFERENCES customer_bikes(id),
  status            TEXT NOT NULL CHECK (status IN (
                      'intake', 'diagnosed', 'awaiting_parts', 'quoted',
                      'scheduled', 'in_progress', 'done', 'paid')),
  complaint         TEXT NOT NULL,
  diagnosis         TEXT,
  scheduled_for     TEXT,
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE work_order_lines (
  id                INTEGER PRIMARY KEY,
  work_order_id     INTEGER NOT NULL REFERENCES work_orders(id),
  part_id           INTEGER REFERENCES parts(id),
  service_id        INTEGER REFERENCES services(id),
  qty               INTEGER NOT NULL DEFAULT 1,
  unit_price_cents  INTEGER NOT NULL,
  CHECK ((part_id IS NULL) <> (service_id IS NULL))   -- exactly one of the two
);

CREATE TABLE payments (
  id                 INTEGER PRIMARY KEY,
  work_order_id      INTEGER NOT NULL REFERENCES work_orders(id),
  stripe_session_id  TEXT,
  amount_cents       INTEGER NOT NULL,
  status             TEXT NOT NULL CHECK (status IN (
                       'pending', 'paid', 'failed', 'refunded'))
);

-- Procurement -----------------------------------------------------------------

CREATE TABLE suppliers (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  lead_time_days  INTEGER NOT NULL
);

CREATE TABLE supplier_parts (
  supplier_id      INTEGER NOT NULL REFERENCES suppliers(id),
  part_id          INTEGER NOT NULL REFERENCES parts(id),
  unit_cost_cents  INTEGER NOT NULL,
  available_qty    INTEGER NOT NULL,
  PRIMARY KEY (supplier_id, part_id)
);

-- The approval queue is purchase orders with status 'pending_approval'.
CREATE TABLE purchase_orders (
  id             INTEGER PRIMARY KEY,
  supplier_id    INTEGER NOT NULL REFERENCES suppliers(id),
  work_order_id  INTEGER REFERENCES work_orders(id),
  status         TEXT NOT NULL CHECK (status IN (
                   'draft', 'pending_approval', 'approved',
                   'rejected', 'sent', 'received')),
  total_cents    INTEGER NOT NULL,
  reason         TEXT,            -- the agent's justification, shown to the approver
  decided_by     TEXT,
  decided_at     TEXT,
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE purchase_order_lines (
  purchase_order_id  INTEGER NOT NULL REFERENCES purchase_orders(id),
  part_id            INTEGER NOT NULL REFERENCES parts(id),
  qty                INTEGER NOT NULL,
  unit_cost_cents    INTEGER NOT NULL,
  PRIMARY KEY (purchase_order_id, part_id)
);

-- Governance ------------------------------------------------------------------

CREATE TABLE settings (
  key    TEXT PRIMARY KEY,        -- e.g. po_approval_limit_cents
  value  TEXT NOT NULL
);

-- Every tool call, written by the MCP servers so it is the same for any runtime.
CREATE TABLE audit_log (
  id               INTEGER PRIMARY KEY,
  at               TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  conversation_id  TEXT,
  runtime          TEXT,          -- anthropic, dust
  tool             TEXT NOT NULL,
  args_json        TEXT NOT NULL,
  result_summary   TEXT
);
