import sqlite3
import pandas as pd

def assign_professor_statuses():
    conn = sqlite3.connect('absence_tracker.db')
    
    # 1. Get all unique professors currently in the MasterSchedule
    all_profs = pd.read_sql("SELECT DISTINCT Professeur FROM MasterSchedule", conn)['Professeur'].tolist()
    
    # 2. Load the Permanent list (from your uploaded CSV)
    # Using the filename you provided
    perm_df = pd.read_csv('Prof permanents.xlsx - Feuil2.csv')
    # Assuming the column name is 'Professeurs permanents' based on file preview
    permanent_list = perm_df['Professeurs permanents'].str.strip().tolist()
    
    # 3. Insert into Professors table
    for prof in all_profs:
        status = 'Permanent' if prof.strip() in permanent_list else 'Vacataire'
        try:
            conn.execute("INSERT INTO Professors (name, status) VALUES (?, ?)", (prof.strip(), status))
        except sqlite3.IntegrityError:
            # If prof already exists, update their status instead
            conn.execute("UPDATE Professors SET status = ? WHERE name = ?", (status, prof.strip()))
            
    conn.commit()
    conn.close()
    print("Status assignment complete.")