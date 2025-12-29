import sqlite3

DATABASE_NAME = 'absence_tracker.db'

def create_tables():
    """Creates the MasterSchedule and AbsenceRecords tables."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # 1. Master Schedule Table (Stores all your schedule data)
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

    # 2. Absence Records Table (Stores the confirmed absences)
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

    conn.commit()
    conn.close()
    print(f"Database '{DATABASE_NAME}' and tables created successfully.")

if __name__ == '__main__':
    create_tables()