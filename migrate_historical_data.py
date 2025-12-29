import pandas as pd
import sqlite3

DATABASE_NAME = 'absence_tracker.db'
HISTORICAL_FILE = 'Absence.csv'

def migrate_data():
    try:
        # 1. Load the historical absence data
        # We use the semicolon separator and latin-1 encoding found earlier
        df = pd.read_csv(HISTORICAL_FILE, sep=';', encoding='latin-1')
        
        # 2. Normalize columns (lowercase and remove whitespace)
        df.columns = df.columns.str.strip().str.lower()
        
        # 3. Handle the specific column names
        # Map 'filiÃ©re' or 'filiére' to 'filiere' and 'date' to 'date_absent'
        df = df.rename(columns={
            'filiére': 'filiere',
            'filiÃ©re': 'filiere',
            'date': 'date_absent'
        })

        # 4. Standardize the Date Format
        # Your CSV uses DD/MM/YYYY, but our app uses YYYY-MM-DD. 
        # We convert it so the sorting works correctly in the dashboard.
        df['date_absent'] = pd.to_datetime(df['date_absent'], dayfirst=True).dt.strftime('%Y-%m-%d')

        # 5. Connect to the Database
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        # 6. CLEAR THE OLD DATA (Empty the table as requested)
        cursor.execute("DELETE FROM AbsenceRecords")
        print("Deleted existing records from AbsenceRecords.")

        # 7. Prepare and Insert the new data
        # We add a default reason for these historical records
        df['absence_reason'] = 'Historique (Importé)'
        
        # Select and order columns to match the database exactly
        data_to_insert = df[[
            'date_absent', 'professeur', 'semestre', 'filiere', 
            'groupe', 'jour', 'lheure', 'salle', 'absence_reason'
        ]]

        # Rename to match Database casing exactly
        data_to_insert.columns = [
            'date_absent', 'Professeur', 'Semestre', 'Filiere', 
            'Groupe', 'Jour', 'Lheure', 'Salle', 'absence_reason'
        ]

        data_to_insert.to_sql('AbsenceRecords', conn, if_exists='append', index=False)
        
        conn.commit()
        conn.close()
        print(f"Successfully imported {len(df)} historical records into the database.")

    except Exception as e:
        print(f"An error occurred during migration: {e}")

if __name__ == '__main__':
    migrate_data()