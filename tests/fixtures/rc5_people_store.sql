PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO alembic_version VALUES('0012_annotation_assets_is_edited');
CREATE TABLE store_meta (
	"key" VARCHAR NOT NULL, 
	value JSON NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_store_meta PRIMARY KEY ("key")
);
CREATE TABLE people_registry (
	registry VARCHAR NOT NULL, 
	header JSON, 
	updated_at DATETIME, 
	CONSTRAINT pk_people_registry PRIMARY KEY (registry)
);
INSERT INTO people_registry VALUES('default','{"version": 1, "generated": "2026-10-01T09:00:00", "owner": {"person_id": "id-ana", "name": "Ana Example", "identified": "inferred"}}','2026-10-07 14:25:31.331092');
CREATE TABLE people (
	person_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	name TEXT, 
	birth_date VARCHAR, 
	origin VARCHAR, 
	inferred JSON, 
	confirmed JSON, 
	extra JSON, 
	CONSTRAINT pk_people PRIMARY KEY (person_id)
);
INSERT INTO people VALUES('id-ana',0,'Ana Example',NULL,NULL,'{"tier": "inner", "counts_reliable": true, "evidence": {"count": 400, "active_months": 2, "first_month": "2019-01", "last_month": "2019-02", "span_years": 0.1, "onset": null, "concentration": 200.0, "continuity": 1.0}, "links": [{"kind": "tight-dyad", "with": "id-luc", "confidence": 0.8, "via": "co-occurrence"}]}','{"role": null, "notes": null}','null');
INSERT INTO people VALUES('id-luc',1,'Luc Sample',NULL,NULL,'{"tier": "inner", "counts_reliable": true, "evidence": {"count": 400, "active_months": 2, "first_month": "2019-01", "last_month": "2019-02", "span_years": 0.1, "onset": null, "concentration": 200.0, "continuity": 1.0}, "links": [{"kind": "tight-dyad", "with": "id-ana", "confidence": 0.8, "via": "co-occurrence"}]}','{"role": null, "notes": null}','null');
CREATE TABLE people_aliases (
	alias_id VARCHAR NOT NULL, 
	person_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, account VARCHAR, 
	CONSTRAINT pk_people_aliases PRIMARY KEY (alias_id), 
	CONSTRAINT fk_people_aliases_person_id_people FOREIGN KEY(person_id) REFERENCES people (person_id) ON DELETE CASCADE
);
INSERT INTO people_aliases VALUES('id-ana','id-ana',0,NULL);
INSERT INTO people_aliases VALUES('id-luc','id-luc',0,NULL);
CREATE TABLE people_relationships (
	person_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	kind VARCHAR, 
	target_id VARCHAR, 
	reverse VARCHAR, 
	decision VARCHAR, 
	extra JSON, 
	CONSTRAINT pk_people_relationships PRIMARY KEY (person_id, position), 
	CONSTRAINT fk_people_relationships_person_id_people FOREIGN KEY(person_id) REFERENCES people (person_id) ON DELETE CASCADE
);
INSERT INTO people_relationships VALUES('id-ana',0,'tight-dyad','id-luc',NULL,'confirmed','null');
CREATE TABLE settings (
	"key" VARCHAR NOT NULL, 
	value JSON, 
	secret BOOLEAN NOT NULL, 
	ciphertext BLOB, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_settings PRIMARY KEY ("key")
);
CREATE TABLE annotation_assets (
	asset_id TEXT NOT NULL, 
	taken_at DATETIME, 
	media_kind TEXT, 
	favourite BOOLEAN, 
	original_file TEXT, 
	width INTEGER, 
	height INTEGER, 
	city TEXT, 
	state TEXT, 
	country TEXT, 
	latitude FLOAT, 
	longitude FLOAT, 
	live_photo_video_id TEXT, 
	duration_seconds FLOAT, is_edited BOOLEAN, 
	CONSTRAINT pk_annotation_assets PRIMARY KEY (asset_id)
);
CREATE TABLE asset_flags (
	asset_id TEXT NOT NULL, 
	flag TEXT NOT NULL, 
	source TEXT NOT NULL, 
	evidence TEXT, 
	written_at DATETIME, 
	CONSTRAINT pk_asset_flags PRIMARY KEY (asset_id, flag, source)
);
CREATE TABLE asset_people (
	asset_id TEXT NOT NULL, 
	person_name TEXT NOT NULL, 
	person_id TEXT, 
	birth_date TEXT, 
	written_at DATETIME, 
	CONSTRAINT pk_asset_people PRIMARY KEY (asset_id, person_name)
);
CREATE TABLE caption_provenance (
	asset_id TEXT NOT NULL, 
	model TEXT NOT NULL, 
	origin TEXT NOT NULL, 
	CONSTRAINT pk_caption_provenance PRIMARY KEY (asset_id, model)
);
CREATE TABLE description_fields (
	asset_id TEXT NOT NULL, 
	model TEXT NOT NULL, 
	field TEXT NOT NULL, 
	value TEXT, 
	written_at DATETIME, 
	CONSTRAINT pk_description_fields PRIMARY KEY (asset_id, model, field)
);
CREATE TABLE description_unavailable (
	asset_id TEXT NOT NULL, 
	model TEXT NOT NULL, 
	source TEXT NOT NULL, 
	version TEXT NOT NULL, 
	producer_key TEXT NOT NULL, 
	preview_sha256 TEXT NOT NULL, 
	image_sha256 TEXT NOT NULL, 
	request_sha256 TEXT NOT NULL, 
	request_json TEXT NOT NULL, 
	attempts_json TEXT NOT NULL, 
	written_at DATETIME NOT NULL, 
	CONSTRAINT pk_description_unavailable PRIMARY KEY (asset_id, model)
);
CREATE TABLE descriptions (
	asset_id TEXT NOT NULL, 
	model TEXT NOT NULL, 
	text TEXT, 
	source TEXT, 
	written_at DATETIME, 
	CONSTRAINT pk_descriptions PRIMARY KEY (asset_id, model)
);
CREATE TABLE editorial_episode_readings (
	group_id TEXT NOT NULL, 
	producer_key TEXT NOT NULL, 
	evidence_key TEXT NOT NULL, 
	full_asset_ids TEXT NOT NULL, 
	what_happened TEXT NOT NULL, 
	representatives TEXT NOT NULL, 
	cull_decisions TEXT NOT NULL, 
	notable_moments TEXT NOT NULL, 
	answered_at DATETIME NOT NULL, 
	CONSTRAINT pk_editorial_episode_readings PRIMARY KEY (group_id, producer_key, evidence_key)
);
CREATE TABLE editorial_episode_refusals (
	group_id TEXT NOT NULL, 
	producer_key TEXT NOT NULL, 
	evidence_key TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	answered_at DATETIME NOT NULL, 
	CONSTRAINT pk_editorial_episode_refusals PRIMARY KEY (group_id, producer_key, evidence_key)
);
CREATE TABLE editorial_verdicts (
	asset_id TEXT NOT NULL, 
	pass_version TEXT NOT NULL, 
	bucket TEXT NOT NULL, 
	decided_at DATETIME NOT NULL, 
	CONSTRAINT pk_editorial_verdicts PRIMARY KEY (asset_id, pass_version)
);
CREATE TABLE face_boxes (
	asset_id TEXT NOT NULL, 
	ordinal INTEGER NOT NULL, 
	named BOOLEAN, 
	x1 FLOAT, 
	y1 FLOAT, 
	x2 FLOAT, 
	y2 FLOAT, 
	person_id TEXT, 
	CONSTRAINT pk_face_boxes PRIMARY KEY (asset_id, ordinal)
);
CREATE TABLE face_reads (
	asset_id TEXT NOT NULL, 
	producer TEXT NOT NULL, 
	read_at DATETIME, 
	CONSTRAINT pk_face_reads PRIMARY KEY (asset_id, producer)
);
CREATE TABLE head_facts (
	asset_id TEXT NOT NULL, 
	head TEXT NOT NULL, 
	version TEXT NOT NULL, 
	label TEXT, 
	confidence FLOAT, 
	encoder_key TEXT, 
	decided_at DATETIME, 
	CONSTRAINT pk_head_facts PRIMARY KEY (asset_id, head, version)
);
CREATE TABLE judgments (
	"key" TEXT NOT NULL, 
	answer TEXT NOT NULL, 
	answered_at DATETIME NOT NULL, 
	CONSTRAINT pk_judgments PRIMARY KEY ("key")
);
CREATE TABLE library_overviews (
	node_key TEXT NOT NULL, 
	kind TEXT NOT NULL, 
	period TEXT NOT NULL, 
	account TEXT NOT NULL, 
	children TEXT NOT NULL, 
	CONSTRAINT pk_library_overviews PRIMARY KEY (node_key)
);
CREATE TABLE live_clock_offsets (
	asset_id TEXT NOT NULL, 
	producer TEXT NOT NULL, 
	source_digest TEXT NOT NULL, 
	measured TEXT NOT NULL, 
	written_at DATETIME NOT NULL, 
	CONSTRAINT pk_live_clock_offsets PRIMARY KEY (asset_id, producer)
);
CREATE TABLE motion_bursts (
	asset_id TEXT NOT NULL, 
	burst_id TEXT, 
	still_ids TEXT, 
	video_ids TEXT, 
	duration_seconds FLOAT, 
	beats_a_still BOOLEAN, 
	minimum_seconds FLOAT, 
	computed_at DATETIME, 
	CONSTRAINT pk_motion_bursts PRIMARY KEY (asset_id)
);
CREATE TABLE motion_lines (
	asset_id TEXT NOT NULL, 
	producer TEXT NOT NULL, 
	source_digest TEXT NOT NULL, 
	status TEXT NOT NULL, 
	text TEXT NOT NULL, 
	frames INTEGER NOT NULL, 
	bytes_read INTEGER NOT NULL, 
	written_at DATETIME NOT NULL, 
	provenance TEXT, 
	CONSTRAINT pk_motion_lines PRIMARY KEY (asset_id, producer)
);
CREATE TABLE motion_residuals (
	asset_id TEXT NOT NULL, 
	producer TEXT NOT NULL, 
	source_digest TEXT NOT NULL, 
	measured TEXT NOT NULL, 
	written_at DATETIME NOT NULL, 
	CONSTRAINT pk_motion_residuals PRIMARY KEY (asset_id, producer)
);
CREATE TABLE pixel_facts (
	asset_id TEXT NOT NULL, 
	producer_key TEXT, 
	sharpness FLOAT, 
	brightness FLOAT, 
	contrast FLOAT, 
	dark_fraction FLOAT, 
	bright_fraction FLOAT, 
	width INTEGER, 
	height INTEGER, 
	orientation TEXT, 
	needs_rotation BOOLEAN, 
	computed_at DATETIME, 
	CONSTRAINT pk_pixel_facts PRIMARY KEY (asset_id)
);
CREATE TABLE pixel_facts_thresholds (
	name TEXT NOT NULL, 
	value FLOAT, 
	producer_key TEXT, 
	n INTEGER, 
	computed_at DATETIME, 
	CONSTRAINT pk_pixel_facts_thresholds PRIMARY KEY (name)
);
CREATE TABLE speech_regions (
	asset_id TEXT NOT NULL, 
	producer TEXT NOT NULL, 
	source_digest TEXT NOT NULL, 
	measured TEXT NOT NULL, 
	written_at DATETIME NOT NULL, 
	CONSTRAINT pk_speech_regions PRIMARY KEY (asset_id, producer)
);
CREATE TABLE text_completion_failures (
	"key" TEXT NOT NULL, 
	record TEXT NOT NULL, 
	recorded_at DATETIME NOT NULL, 
	CONSTRAINT pk_text_completion_failures PRIMARY KEY ("key")
);
CREATE TABLE pipeline_runs (
	run_id VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	status VARCHAR NOT NULL, 
	memory_type VARCHAR, 
	memory_key VARCHAR, 
	memory_category VARCHAR, 
	memory_people JSON NOT NULL, 
	source VARCHAR NOT NULL, 
	automation_attempt_id VARCHAR, 
	last_phase VARCHAR, 
	phase_events JSON NOT NULL, 
	person_name TEXT, 
	person_id VARCHAR, 
	date_range_start VARCHAR, 
	date_range_end VARCHAR, 
	target_duration_seconds INTEGER, 
	output_path TEXT, 
	output_size_bytes BIGINT NOT NULL, 
	output_duration_seconds FLOAT NOT NULL, 
	clips_analyzed INTEGER NOT NULL, 
	clips_selected INTEGER NOT NULL, 
	errors_count INTEGER NOT NULL, 
	system_info JSON, 
	delivery_status VARCHAR NOT NULL, 
	delivery_attempts INTEGER NOT NULL, 
	delivery_error TEXT, 
	immich_asset_id VARCHAR, 
	delivery_album TEXT, 
	warnings JSON NOT NULL, 
	llm_metrics JSON, 
	title_source VARCHAR, film_timeline JSON, 
	CONSTRAINT pk_pipeline_runs PRIMARY KEY (run_id)
);
CREATE TABLE phase_stats (
	id INTEGER NOT NULL, 
	run_id VARCHAR NOT NULL, 
	phase_name VARCHAR NOT NULL, 
	started_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	duration_seconds FLOAT NOT NULL, 
	items_processed INTEGER NOT NULL, 
	items_total INTEGER NOT NULL, 
	errors JSON, 
	extra_metrics JSON, 
	CONSTRAINT pk_phase_stats PRIMARY KEY (id), 
	CONSTRAINT fk_phase_stats_run_id_pipeline_runs FOREIGN KEY(run_id) REFERENCES pipeline_runs (run_id) ON DELETE CASCADE
);
CREATE TABLE run_attempts (
	run_id VARCHAR NOT NULL, 
	attempt_dir TEXT NOT NULL, 
	output_path TEXT NOT NULL, 
	recorded_at DATETIME NOT NULL, 
	CONSTRAINT pk_run_attempts PRIMARY KEY (run_id)
);
CREATE TABLE automation_attempts (
	seq INTEGER NOT NULL, 
	id VARCHAR NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	outcome VARCHAR NOT NULL, 
	reason TEXT NOT NULL, 
	candidate_category VARCHAR, 
	memory_type VARCHAR, 
	memory_key VARCHAR, 
	run_id VARCHAR, 
	error TEXT, 
	last_phase VARCHAR, 
	phase_events JSON NOT NULL, 
	CONSTRAINT pk_automation_attempts PRIMARY KEY (seq), 
	CONSTRAINT uq_automation_attempts_id UNIQUE (id)
);
CREATE TABLE notification_health (
	id INTEGER NOT NULL, 
	last_attempt_at DATETIME, 
	last_success_at DATETIME, 
	last_failure_at DATETIME, 
	failure_category VARCHAR, 
	failure_message TEXT, 
	CONSTRAINT pk_notification_health PRIMARY KEY (id)
);
CREATE TABLE special_days (
	position INTEGER NOT NULL, 
	record JSON NOT NULL, 
	CONSTRAINT pk_special_days PRIMARY KEY (position)
);
CREATE TABLE asset_scores (
	asset_id VARCHAR NOT NULL, 
	model_version VARCHAR NOT NULL, 
	asset_type VARCHAR NOT NULL, 
	llm_interest FLOAT, 
	llm_quality FLOAT, 
	llm_emotion TEXT, 
	llm_description TEXT, 
	llm_category VARCHAR, 
	metadata_score FLOAT NOT NULL, 
	combined_score FLOAT NOT NULL, 
	analyzed_at DATETIME NOT NULL, 
	CONSTRAINT pk_asset_scores PRIMARY KEY (asset_id, model_version)
);
CREATE TABLE audience_answers (
	answerer TEXT NOT NULL, 
	evidence_key TEXT NOT NULL, 
	record JSON NOT NULL, 
	CONSTRAINT pk_audience_answers PRIMARY KEY (answerer, evidence_key)
);
CREATE TABLE audience_holds (
	asset_id TEXT NOT NULL, 
	slot TEXT NOT NULL, 
	hold JSON NOT NULL, 
	CONSTRAINT pk_audience_holds PRIMARY KEY (asset_id, slot)
);
CREATE TABLE vote_bank_entries (
	bank TEXT NOT NULL, 
	scope TEXT NOT NULL, 
	section TEXT NOT NULL, 
	entry_key TEXT NOT NULL, 
	value JSON NOT NULL, 
	CONSTRAINT pk_vote_bank_entries PRIMARY KEY (bank, scope, section, entry_key)
);
CREATE TABLE owner_edits (
	edit_id TEXT NOT NULL, 
	film_stem TEXT NOT NULL, 
	attempt_id TEXT, 
	record JSON NOT NULL, 
	recorded_at DATETIME NOT NULL, 
	CONSTRAINT pk_owner_edits PRIMARY KEY (edit_id)
);
CREATE TABLE geocoded_places (
	cell VARCHAR NOT NULL, 
	language VARCHAR NOT NULL, 
	address JSON NOT NULL, 
	fetched_at DATETIME NOT NULL, 
	CONSTRAINT pk_geocoded_places PRIMARY KEY (cell, language)
);
CREATE TABLE run_spans (
	run_id VARCHAR NOT NULL, 
	span_id INTEGER NOT NULL, 
	record JSON NOT NULL, 
	CONSTRAINT pk_run_spans PRIMARY KEY (run_id, span_id), 
	CONSTRAINT fk_run_spans_run_id_pipeline_runs FOREIGN KEY(run_id) REFERENCES pipeline_runs (run_id) ON DELETE CASCADE
);
CREATE TABLE run_diagnostics (
	run_id VARCHAR NOT NULL, 
	record JSON NOT NULL, 
	CONSTRAINT pk_run_diagnostics PRIMARY KEY (run_id), 
	CONSTRAINT fk_run_diagnostics_run_id_pipeline_runs FOREIGN KEY(run_id) REFERENCES pipeline_runs (run_id) ON DELETE CASCADE
);
CREATE TABLE people_groups (
	label VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	expression JSON NOT NULL, 
	CONSTRAINT pk_people_groups PRIMARY KEY (label)
);
INSERT INTO people_groups VALUES('pair',0,'{"all": [{"person": "id-ana"}, {"person": "id-luc"}]}');
CREATE INDEX ix_people_aliases_person_id ON people_aliases (person_id);
CREATE INDEX ix_people_relationships_target_id ON people_relationships (target_id);
CREATE INDEX ix_judgments_answered_at ON judgments (answered_at);
CREATE INDEX ix_asset_scores_asset_type ON asset_scores (asset_type);
CREATE INDEX ix_automation_attempts_started_at ON automation_attempts (started_at);
CREATE INDEX ix_pipeline_runs_automation_attempt_id ON pipeline_runs (automation_attempt_id);
CREATE INDEX ix_pipeline_runs_created_at ON pipeline_runs (created_at);
CREATE INDEX ix_pipeline_runs_delivery_status_source_status ON pipeline_runs (delivery_status, source, status);
CREATE INDEX ix_pipeline_runs_memory_key ON pipeline_runs (memory_key);
CREATE INDEX ix_pipeline_runs_status ON pipeline_runs (status);
CREATE INDEX ix_phase_stats_run_id ON phase_stats (run_id);
CREATE INDEX ix_owner_edits_attempt_id ON owner_edits (attempt_id);
COMMIT;
