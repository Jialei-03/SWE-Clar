import sqlite3

def connect(path):
 db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
 db.executescript('''CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,phone TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS shifts(id TEXT PRIMARY KEY,starts_at TEXT NOT NULL,location TEXT NOT NULL,address TEXT NOT NULL,map_url TEXT NOT NULL,manager_email TEXT NOT NULL,capacity INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'Open');
 CREATE TABLE IF NOT EXISTS signups(id TEXT PRIMARY KEY,employee_id TEXT NOT NULL REFERENCES employees(id),shift_id TEXT NOT NULL REFERENCES shifts(id),status TEXT NOT NULL DEFAULT 'New',checked_in INTEGER NOT NULL DEFAULT 0,UNIQUE(employee_id,shift_id));
 CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,signup_id TEXT NOT NULL,channel TEXT NOT NULL,recipient TEXT NOT NULL,body TEXT NOT NULL);
 ''');return db
