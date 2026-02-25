import sqlite3

DATABASE_NAME = 'absence_tracker.db'

def create_tables():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # --- NEW TABLE: Professors ---
    # Stores the status (Permanent/Vacataire) for each unique professor
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Professors (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'Vacataire'
    )
    """)

    # 1. Master Schedule Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MasterSchedule (
        id INTEGER PRIMARY KEY,
        Professeur TEXT NOT NULL,
        Semestre INTEGER,
        Filiere TEXT NOT NULL,
        Groupe TEXT,
        Jour TEXT NOT NULL,
        Lheure TEXT NOT NULL,
        Salle TEXT NOT NULL
    )
    """)

    # 2. Absence Records Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS AbsenceRecords (
        id INTEGER PRIMARY KEY,
        date_absent TEXT NOT NULL,
        Professeur TEXT NOT NULL,
        Semestre INTEGER,
        Filiere TEXT NOT NULL,
        Groupe TEXT,
        Jour TEXT NOT NULL,
        Lheure TEXT NOT NULL,
        Salle TEXT NOT NULL,
        absence_reason TEXT
    )
    """)
    
    # 3. Ratt Sessions Table (Ensuring it exists as per your app.py logic)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RattSessions (
        id INTEGER PRIMARY KEY,
        date_ratt TEXT NOT NULL,
        Professeur TEXT NOT NULL,
        Lheure TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()
    print(f"Database '{DATABASE_NAME}' updated with Professors table.")

if __name__ == '__main__':
    create_tables()

