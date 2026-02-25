import sqlite3

def fix_database():
    conn = sqlite3.connect('absence_tracker.db')
    cursor = conn.cursor()

    # 1. Create the Config table if it's missing
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Config (
        sem_start TEXT,
        sem_end TEXT
    )
    """)

    # 2. Create the RattSessions table if it's missing (for your rattrapages)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RattSessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_ratt TEXT NOT NULL,
        Professeur TEXT NOT NULL,
        Lheure TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()
    print("Success! The missing tables (Config & RattSessions) have been created.")

if __name__ == '__main__':
    fix_database()