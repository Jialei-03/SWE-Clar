CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS profiles(sequence INTEGER PRIMARY KEY AUTOINCREMENT,profile_id TEXT NOT NULL UNIQUE,user_id TEXT NOT NULL REFERENCES users(user_id),role TEXT NOT NULL CHECK(role IN ('mentor','mentee')));
CREATE TABLE IF NOT EXISTS matches(sequence INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT NOT NULL UNIQUE,mentor_id TEXT NOT NULL REFERENCES profiles(profile_id),mentee_id TEXT NOT NULL REFERENCES profiles(profile_id),status TEXT NOT NULL DEFAULT 'suggested');
CREATE TABLE IF NOT EXISTS outbox(sequence INTEGER PRIMARY KEY AUTOINCREMENT,notice_id TEXT NOT NULL UNIQUE,match_id TEXT NOT NULL REFERENCES matches(match_id));
CREATE TABLE IF NOT EXISTS automations(automation_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
INSERT OR IGNORE INTO automations VALUES ('canonical_intake',1),('canonical_matching',1),('canonical_communication',1),('legacy_mentor',1),('legacy_mentee',1),('duplicate_match',1),('duplicate_notice',1);
