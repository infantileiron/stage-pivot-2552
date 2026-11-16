
CREATE TABLE audits (
	id INTEGER NOT NULL AUTO_INCREMENT,
	actor VARCHAR(100),
	action VARCHAR(200),
	created VARCHAR(40),
	PRIMARY KEY (id)
)

;


CREATE TABLE pivots (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(100),
	row_dim VARCHAR(30),
	col_dim VARCHAR(30),
	state VARCHAR(20),
	result JSON,
	error TEXT,
	PRIMARY KEY (id)
)

;


CREATE TABLE settlements (
	id INTEGER NOT NULL AUTO_INCREMENT,
	code VARCHAR(60) NOT NULL,
	day VARCHAR(10),
	venue VARCHAR(40),
	play VARCHAR(60),
	channel VARCHAR(30),
	gross_cents BIGINT,
	refund_cents BIGINT,
	fee_cents BIGINT,
	seats INTEGER,
	checked INTEGER,
	PRIMARY KEY (id),
	UNIQUE (code)
)

;


CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT,
	email VARCHAR(100) NOT NULL,
	password VARCHAR(200),
	`role` VARCHAR(20),
	PRIMARY KEY (id),
	UNIQUE (email)
)

;


CREATE TABLE reviews (
	id INTEGER NOT NULL AUTO_INCREMENT,
	pivot_id INTEGER,
	row_key VARCHAR(100),
	col_key VARCHAR(100),
	book_cents BIGINT,
	expected_cents BIGINT,
	difference_cents BIGINT,
	note TEXT,
	status VARCHAR(20),
	PRIMARY KEY (id),
	FOREIGN KEY(pivot_id) REFERENCES pivots (id)
)

;

CREATE TABLE pivot_runs (
	pivot_id INTEGER NOT NULL,
	snapshot JSON,
	snapshot_checksum VARCHAR(64),
	claim_token VARCHAR(64),
	worker_id VARCHAR(100),
	lease_until BIGINT NOT NULL,
	attempt INTEGER NOT NULL,
	retry_count INTEGER NOT NULL,
	queued_at VARCHAR(40),
	started_at VARCHAR(40),
	published_at VARCHAR(40),
	finished_at VARCHAR(40),
	artifact_sha256 VARCHAR(64),
	artifact_size BIGINT,
	last_error TEXT,
	PRIMARY KEY (pivot_id),
	FOREIGN KEY(pivot_id) REFERENCES pivots (id)
)

;

CREATE TABLE pivot_events (
	id INTEGER NOT NULL AUTO_INCREMENT,
	pivot_id INTEGER NOT NULL,
	from_state VARCHAR(20),
	to_state VARCHAR(20) NOT NULL,
	attempt INTEGER,
	actor VARCHAR(100),
	detail TEXT,
	created VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(pivot_id) REFERENCES pivots (id)
)

;

CREATE INDEX ix_pivot_events_pivot_id ON pivot_events (pivot_id)
;
