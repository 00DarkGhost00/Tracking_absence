import sqlite3

def upgrade_absence_table():
    conn = sqlite3.connect('absence_tracker.db')
    cursor = conn.cursor()
    
    try:
        # On ajoute la colonne "Module" à la table AbsenceRecords
        cursor.execute("ALTER TABLE AbsenceRecords ADD COLUMN Module TEXT DEFAULT ''")
        print("✅ Succès : La colonne 'Module' a été ajoutée à l'historique des absences !")
    except sqlite3.OperationalError:
        # Si la colonne existe déjà, SQLite renverra une erreur, on la gère ici
        print("⚠️ La colonne 'Module' existe déjà dans AbsenceRecords. Tout est prêt !")
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    upgrade_absence_table()