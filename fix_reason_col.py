
import sqlite3

def add_reason_column():
    conn = sqlite3.connect('absence_tracker.db')
    cursor = conn.cursor()
    
    try:
        # On ajoute la colonne "absence_reason" à la table
        cursor.execute("ALTER TABLE AbsenceRecords ADD COLUMN absence_reason TEXT DEFAULT 'Non justifiée'")
        print("✅ Succès : La colonne 'absence_reason' a été ajoutée !")
    except sqlite3.OperationalError as e:
        print(f"⚠️ Info : {e}")
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    add_reason_column()