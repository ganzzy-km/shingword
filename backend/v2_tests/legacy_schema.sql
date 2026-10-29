CREATE TABLE activity_record (
	id VARCHAR(36) NOT NULL, 
	action VARCHAR(120) NOT NULL, 
	target_type VARCHAR(60) NOT NULL, 
	target_id VARCHAR(36), 
	details JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
CREATE TABLE analysis (
	id VARCHAR(36) NOT NULL, 
	writing_id VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	analysis_types JSON, 
	settings JSON, 
	metrics JSON, 
	disclaimer TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(writing_id) REFERENCES writing (id) ON DELETE CASCADE
);
CREATE TABLE analysis_finding (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	finding_type VARCHAR(60) NOT NULL, 
	severity VARCHAR(30), 
	title VARCHAR(240) NOT NULL, 
	current_text TEXT, 
	suggestion TEXT, 
	reason TEXT, 
	rule VARCHAR(240), 
	source_url VARCHAR(500), 
	confidence FLOAT, 
	start_offset INTEGER, 
	end_offset INTEGER, 
	status VARCHAR(40) NOT NULL, 
	metadata_json JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE
);
CREATE TABLE analysis_job (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	progress INTEGER NOT NULL, 
	current_step VARCHAR(120), 
	completed_steps JSON, 
	error_message TEXT, 
	cancel_requested BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (analysis_id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE
);
CREATE TABLE analysis_sentence (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	paragraph_number INTEGER NOT NULL, 
	sentence_number INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	start_offset INTEGER NOT NULL, 
	end_offset INTEGER NOT NULL, 
	auto_role VARCHAR(40), 
	user_role VARCHAR(40), 
	confidence FLOAT, 
	rationale TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE
);
CREATE TABLE argument_link (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	claim_sentence_id VARCHAR(36) NOT NULL, 
	evidence_sentence_id VARCHAR(36) NOT NULL, 
	score INTEGER NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	details JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE, 
	FOREIGN KEY(claim_sentence_id) REFERENCES analysis_sentence (id), 
	FOREIGN KEY(evidence_sentence_id) REFERENCES analysis_sentence (id)
);
CREATE TABLE backup_record (
	id VARCHAR(36) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	size INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	include_uploads BOOLEAN NOT NULL, 
	schema_version VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (filename)
);
CREATE TABLE draft_autosave (
	id VARCHAR(36) NOT NULL, 
	writing_id VARCHAR(36) NOT NULL, 
	revision_number INTEGER NOT NULL, 
	content TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(writing_id) REFERENCES writing (id) ON DELETE CASCADE
);
CREATE TABLE finding_action (
	id VARCHAR(36) NOT NULL, 
	finding_id VARCHAR(36) NOT NULL, 
	action VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(finding_id) REFERENCES analysis_finding (id) ON DELETE CASCADE
);
CREATE TABLE language_rule (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(240) NOT NULL, 
	pattern VARCHAR(300) NOT NULL, 
	replacement VARCHAR(300), 
	status VARCHAR(40) NOT NULL, 
	explanation TEXT NOT NULL, 
	clause VARCHAR(240) NOT NULL, 
	source_id VARCHAR(36), 
	auto_fixable BOOLEAN NOT NULL, 
	context_required BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES official_source (id) ON DELETE SET NULL
);
CREATE TABLE ocr_run (
	id VARCHAR(36) NOT NULL, 
	target_type VARCHAR(30) NOT NULL, 
	target_id VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	language VARCHAR(40), 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE official_source (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(240) NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	checked_at DATE NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE peel_result (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	paragraph_number INTEGER NOT NULL, 
	elements JSON, 
	rationale TEXT, 
	guidance TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE
);
CREATE TABLE quote_card (
	id VARCHAR(36) NOT NULL, 
	workspace_id VARCHAR(64) NOT NULL, 
	document_id VARCHAR(36), 
	selected_text TEXT NOT NULL, 
	quote_text TEXT NOT NULL, 
	work VARCHAR(240), 
	author VARCHAR(160), 
	page VARCHAR(60), 
	scene TEXT, 
	characters JSON, 
	keywords JSON, 
	inquiry_question TEXT, 
	verification_status VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(document_id) REFERENCES source_document (id) ON DELETE RESTRICT
);
CREATE TABLE quote_check_result (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	student_quote TEXT NOT NULL, 
	source_quote TEXT, 
	status VARCHAR(60) NOT NULL, 
	confidence FLOAT, 
	differences JSON, 
	source_document_id VARCHAR(36), 
	source_page VARCHAR(60), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_document_id) REFERENCES source_document (id) ON DELETE SET NULL
);
CREATE TABLE quote_verification (
	id VARCHAR(36) NOT NULL, 
	quote_card_id VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	difference JSON, 
	reason TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(quote_card_id) REFERENCES quote_card (id) ON DELETE CASCADE
);
CREATE TABLE revision (
	id VARCHAR(36) NOT NULL, 
	writing_id VARCHAR(36) NOT NULL, 
	base_version_id VARCHAR(36) NOT NULL, 
	result_version_id VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(writing_id) REFERENCES writing (id) ON DELETE CASCADE, 
	FOREIGN KEY(base_version_id) REFERENCES writing_version (id), 
	FOREIGN KEY(result_version_id) REFERENCES writing_version (id)
);
CREATE TABLE revision_change (
	id VARCHAR(36) NOT NULL, 
	revision_id VARCHAR(36) NOT NULL, 
	finding_id VARCHAR(36), 
	before_text TEXT NOT NULL, 
	after_text TEXT NOT NULL, 
	start_offset INTEGER NOT NULL, 
	end_offset INTEGER NOT NULL, 
	undone BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(revision_id) REFERENCES revision (id) ON DELETE CASCADE, 
	FOREIGN KEY(finding_id) REFERENCES analysis_finding (id) ON DELETE SET NULL
);
CREATE TABLE rubric (
	id VARCHAR(36) NOT NULL, 
	workspace_id VARCHAR(64) NOT NULL, 
	name VARCHAR(240) NOT NULL, 
	subject VARCHAR(120), 
	activity VARCHAR(120), 
	status VARCHAR(40) NOT NULL, 
	description TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE TABLE rubric_file (
	id VARCHAR(36) NOT NULL, 
	rubric_id VARCHAR(36) NOT NULL, 
	original_name VARCHAR(255) NOT NULL, 
	stored_name VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(120) NOT NULL, 
	size INTEGER NOT NULL, 
	page_count INTEGER NOT NULL, 
	ocr_text TEXT, 
	corrected_text TEXT, 
	ocr_confidence FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(rubric_id) REFERENCES rubric (id) ON DELETE CASCADE, 
	UNIQUE (stored_name)
);
CREATE TABLE rubric_item (
	id VARCHAR(36) NOT NULL, 
	rubric_id VARCHAR(36) NOT NULL, 
	name VARCHAR(240) NOT NULL, 
	description TEXT, 
	check_type VARCHAR(60), 
	source_location VARCHAR(200), 
	position INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(rubric_id) REFERENCES rubric (id) ON DELETE CASCADE
);
CREATE TABLE rubric_result (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	rubric_item_id VARCHAR(36), 
	status VARCHAR(40) NOT NULL, 
	rationale TEXT, 
	related_sentences JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE, 
	FOREIGN KEY(rubric_item_id) REFERENCES rubric_item (id) ON DELETE SET NULL
);
CREATE TABLE source_document (
	id VARCHAR(36) NOT NULL, 
	workspace_id VARCHAR(64) NOT NULL, 
	title VARCHAR(240) NOT NULL, 
	author VARCHAR(160), 
	edition VARCHAR(200), 
	original_name VARCHAR(255) NOT NULL, 
	stored_name VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(120) NOT NULL, 
	size INTEGER NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	page_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	UNIQUE (stored_name)
);
CREATE TABLE source_page (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	page_number INTEGER NOT NULL, 
	original_text TEXT, 
	corrected_text TEXT, 
	confidence FLOAT, 
	extraction_method VARCHAR(40), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (document_id, page_number), 
	FOREIGN KEY(document_id) REFERENCES source_document (id) ON DELETE CASCADE
);
CREATE TABLE spelling_result (
	id VARCHAR(36) NOT NULL, 
	analysis_id VARCHAR(36) NOT NULL, 
	finding_id VARCHAR(36) NOT NULL, 
	auto_fixable BOOLEAN NOT NULL, 
	context_question TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analysis (id) ON DELETE CASCADE, 
	FOREIGN KEY(finding_id) REFERENCES analysis_finding (id) ON DELETE CASCADE
);
CREATE TABLE workspace (
	id VARCHAR(64) NOT NULL, 
	user_name VARCHAR(120) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE workspace_setting (
	id VARCHAR(36) NOT NULL, 
	workspace_id VARCHAR(64) NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	value JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (workspace_id, "key"), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);
CREATE TABLE writing (
	id VARCHAR(36) NOT NULL, 
	workspace_id VARCHAR(64) NOT NULL, 
	title VARCHAR(240), 
	work VARCHAR(240), 
	author VARCHAR(160), 
	inquiry_question TEXT, 
	subject VARCHAR(120), 
	conditions TEXT, 
	due_date DATE, 
	content TEXT, 
	status VARCHAR(40) NOT NULL, 
	revision_number INTEGER NOT NULL, 
	original_version_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE TABLE writing_resource (
	id VARCHAR(36) NOT NULL, 
	writing_id VARCHAR(36) NOT NULL, 
	resource_type VARCHAR(40) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (writing_id, resource_type, resource_id), 
	FOREIGN KEY(writing_id) REFERENCES writing (id) ON DELETE CASCADE
);
CREATE TABLE writing_version (
	id VARCHAR(36) NOT NULL, 
	writing_id VARCHAR(36) NOT NULL, 
	parent_id VARCHAR(36), 
	name VARCHAR(200) NOT NULL, 
	content TEXT, 
	version_number INTEGER NOT NULL, 
	change_count INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(writing_id) REFERENCES writing (id) ON DELETE CASCADE, 
	FOREIGN KEY(parent_id) REFERENCES writing_version (id)
);
CREATE INDEX ix_activity_record_action ON activity_record (action);
CREATE INDEX ix_analysis_finding_analysis_id ON analysis_finding (analysis_id);
CREATE INDEX ix_analysis_finding_finding_type ON analysis_finding (finding_type);
CREATE INDEX ix_analysis_job_status ON analysis_job (status);
CREATE INDEX ix_analysis_sentence_analysis_id ON analysis_sentence (analysis_id);
CREATE INDEX ix_analysis_status ON analysis (status);
CREATE INDEX ix_analysis_writing_id ON analysis (writing_id);
CREATE INDEX ix_ocr_run_target_id ON ocr_run (target_id);
CREATE INDEX ix_ocr_run_target_type ON ocr_run (target_type);
CREATE INDEX ix_quote_card_verification_status ON quote_card (verification_status);
CREATE INDEX ix_rubric_name ON rubric (name);
CREATE INDEX ix_rubric_status ON rubric (status);
CREATE INDEX ix_source_document_author ON source_document (author);
CREATE INDEX ix_source_document_status ON source_document (status);
CREATE INDEX ix_source_document_title ON source_document (title);
CREATE INDEX ix_source_page_text ON source_page (corrected_text);
CREATE INDEX ix_writing_status ON writing (status);
CREATE INDEX ix_writing_title ON writing (title);
CREATE INDEX ix_writing_version_writing_id ON writing_version (writing_id);
CREATE INDEX ix_writing_work ON writing (work);
