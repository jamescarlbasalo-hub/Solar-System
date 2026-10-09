import sqlite3

conn = sqlite3.connect("schoolsync.db")
conn.execute("UPDATE users SET role = 'admin' WHERE email = ?", ("admin@schoolsync.edu",))
conn.commit()
conn.close()
print("Done — role restored to admin.")