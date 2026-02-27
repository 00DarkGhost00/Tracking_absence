import sqlite3
import pandas as pd

def assign_statuses():
    # 1. Connect to your existing database
    conn = sqlite3.connect('absence_tracker.db')
    cursor = conn.cursor()

    # 2. Create the new Professors table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Professors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'Vacataire'
    )
    """)

    try:
        # 3. Get all unique professors from your schedule
        all_profs = pd.read_sql("SELECT DISTINCT Professeur FROM MasterSchedule", conn)['Professeur'].str.strip().tolist()
        
        # 4. FOOLPROOF METHOD: Read the text file line by line directly
        perm_names = []
        # We try UTF-8 first, and if it fails due to accents, we fall back to Latin-1
        try:
            with open('Prof permanents.xlsx', 'r', encoding='utf-8') as f:
                perm_names = [line.strip() for line in f.readlines()]
        except UnicodeDecodeError:
            with open('Prof permanents.xlsx ', 'r', encoding='latin-1') as f:
                perm_names = [line.strip() for line in f.readlines()]

        # 5. Insert them into the new table with the correct status
        for name in all_profs:
            status = 'Permanent' if name in perm_names else 'Vacataire'
            cursor.execute("INSERT OR REPLACE INTO Professors (name, status) VALUES (?, ?)", (name, status))
        
        conn.commit()
        print(f"Success! Added {len(all_profs)} professors to the database.")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        conn.close()

if __name__ == '__main__':
    assign_statuses()