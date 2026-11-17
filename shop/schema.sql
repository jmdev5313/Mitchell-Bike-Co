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

-- What a bike model ships with. Fit is checked against bike_standards, not this.
CREATE TABLE bike_model_standards (
  bike_model_id  INTEGER NOT NULL REFERENCES bike_models(id),
  standard_id    INTEGER NOT NULL REFERENCES standards(id),
  PRIMARY KEY (bike_model_id, standard_id)
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

-- What has been done to a customer bike before, newest last.
CREATE TABLE service_records (
  id                INTEGER PRIMARY KEY,
  customer_bike_id  INTEGER NOT NULL REFERENCES customer_bikes(id),
  serviced_on       TEXT NOT NULL,      -- YYYY-MM-DD
  odometer_km       INTEGER,
  summary           TEXT NOT NULL
);

-- Service ---------------------------------------------------------------------

CREATE TABLE work_orders (
  id                INTEGER PRIMARY KEY,
  customer_id       INTEGER NOT NULL REFERENCES customers(id),
  customer_bike_id  INTEGER NOT NULL REFERENCES customer_bikes(id),
  status            TEXT NOT NULL CHECK (status IN (
                      'intake', 'diagnosed', 'quoted', 'approved', 'declined',
                      'awaiting_parts', 'scheduled', 'in_progress', 'done', 'paid')),
  complaint         TEXT NOT NULL,
  diagnosis         TEXT,
  quoted_total_cents  INTEGER,    -- locked when the quote goes to the customer
  decided_at        TEXT,         -- when the customer approved or declined
  finished_at       TEXT,         -- when the repair was finished
  promised_ready_on TEXT,         -- the ready date the order plan backs up (YYYY-MM-DD)
  staff_seen_at     TEXT,         -- when a mechanic last opened it, for new-activity badges
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

-- Correspondence with the customer about a work order. The agent can only draft;
-- a mechanic sends. A message that carries the quote is what the customer approves.
CREATE TABLE customer_messages (
  id                  INTEGER PRIMARY KEY,
  work_order_id       INTEGER NOT NULL REFERENCES work_orders(id),
  direction           TEXT NOT NULL CHECK (direction IN ('to_customer', 'from_customer')),
  status              TEXT NOT NULL CHECK (status IN ('draft', 'sent', 'received')),
  author              TEXT NOT NULL CHECK (author IN ('agent', 'mechanic', 'customer')),
  body                TEXT NOT NULL,
  quoted_total_cents  INTEGER,          -- set when the message carries the quote
  created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  sent_at             TEXT,
  CHECK ((direction = 'to_customer') = (status IN ('draft', 'sent'))),
  CHECK (quoted_total_cents IS NULL OR direction = 'to_customer')
);

-- A payment is started (for example, a Stripe checkout) and completed when the
-- money is confirmed. A work order can have abandoned pending payments.
CREATE TABLE payments (
  id                 INTEGER PRIMARY KEY,
  work_order_id      INTEGER NOT NULL REFERENCES work_orders(id),
  stripe_session_id  TEXT UNIQUE,
  amount_cents       INTEGER NOT NULL,
  status             TEXT NOT NULL CHECK (status IN (
                       'pending', 'paid', 'failed', 'refunded')),
  created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  paid_at            TEXT
);

-- The private link a customer uses to see their work order. No accounts.
CREATE TABLE customer_links (
  token          TEXT PRIMARY KEY,
  work_order_id  INTEGER NOT NULL UNIQUE REFERENCES work_orders(id),
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_visit_at  TEXT            -- when the customer last opened it
);

-- What the agent plans to order if the customer approves: one supplier per part.
-- The shop places these orders itself when the customer approves.
CREATE TABLE order_plan_lines (
  work_order_id  INTEGER NOT NULL REFERENCES work_orders(id),
  part_id        INTEGER NOT NULL REFERENCES parts(id),
  supplier_id    INTEGER NOT NULL REFERENCES suppliers(id),
  qty            INTEGER NOT NULL,
  PRIMARY KEY (work_order_id, part_id)
);

-- A work order's history: who did what, and when. Written where each action happens.
CREATE TABLE work_order_events (
  id             INTEGER PRIMARY KEY,
  work_order_id  INTEGER NOT NULL REFERENCES work_orders(id),
  at             TEXT NOT NULL,
  actor          TEXT NOT NULL CHECK (actor IN ('agent', 'mechanic', 'customer', 'shop')),
  kind           TEXT NOT NULL,        -- e.g. tool:add_part, message_sent, approved, order_placed
  summary        TEXT NOT NULL,
  detail_json    TEXT,                 -- e.g. which MCP server a tool call went to
  is_error       INTEGER NOT NULL DEFAULT 0
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

-- Parts are ordered for a work order, and only after the customer approves its quote.
CREATE TABLE purchase_orders (
  id             INTEGER PRIMARY KEY,
  supplier_id    INTEGER NOT NULL REFERENCES suppliers(id),
  work_order_id  INTEGER NOT NULL REFERENCES work_orders(id),
  status         TEXT NOT NULL CHECK (status IN ('ordered', 'received', 'cancelled')),
  total_cents    INTEGER NOT NULL,
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  received_at    TEXT
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
  key    TEXT PRIMARY KEY,
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

-- Agent conversations -----------------------------------------------------------
-- Written by agents/, never read by shop rules. One conversation is one chat between
-- a mechanic and the agent; it is linked to a work order once the agent opens one.
CREATE TABLE agent_conversations (
  id             TEXT PRIMARY KEY,     -- also CONVERSATION_ID in audit_log
  runtime        TEXT NOT NULL,        -- anthropic, dust
  model          TEXT,
  work_order_id  INTEGER REFERENCES work_orders(id),
  external_id    TEXT,                 -- the runtime's own conversation id, if it keeps one
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The exact message history sent to the model, append-only.
CREATE TABLE agent_messages (
  id               INTEGER PRIMARY KEY,
  conversation_id  TEXT NOT NULL REFERENCES agent_conversations(id),
  role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content_json     TEXT NOT NULL,
  usage_json       TEXT,                -- token usage, for assistant messages
  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
